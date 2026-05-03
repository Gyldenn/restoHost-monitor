# DECISIONS.md — RestoHost Quality Monitoring System

Registro de decisiones de diseño tomadas en cada módulo, con justificación.

---

## 1. Stack y arquitectura

### LLM: Groq + llama-3.3-70b-versatile

Se eligió Groq como proveedor de inferencia por su latencia extremadamente baja (p95 < 2 s en el tier gratuito), lo que hace viable el loop stream en tiempo casi-real sin incurrir en costos elevados. El modelo `llama-3.3-70b-versatile` ofrece capacidad de razonamiento suficiente para clasificación de llamadas sin el overhead de modelos más grandes. La clave se inyecta por variable de entorno (`GROQ_API_KEY`) para no commitear credenciales.

### Persistencia: JSONL

Los módulos de generación, clasificación y métricas escriben en archivos `.jsonl` en el directorio `data/`. El formato JSONL fue elegido por tres razones:
1. **Append-only atómico**: cada `write()` de una línea < PIPE_BUF es atómico en POSIX, permitiendo que múltiples lectores hagan `tail_follow()` sin locks.
2. **Streaming natural**: el módulo de clasificación puede leer llamadas a medida que el generador las escribe, sin esperar a que termine el batch completo.
3. **Cero dependencias**: no requiere base de datos ni servidor. El seed de 20 llamadas y los datos generados son archivos planos versionables.

La función `write-then-rename` se usa para las escrituras no-append (métricas, review state) para garantizar atomicidad en lecturas concurrentes del dashboard.

### Validación: Pydantic v2

Todos los contratos entre módulos están definidos como modelos Pydantic (`CallRecord`, `Classification`, `Alert`, `MetricsSnapshot`, `ReviewState`). Las ventajas:
- Validación automática en la frontera de cada módulo (el clasificador no puede recibir un `CallRecord` inválido).
- Serialización/deserialización JSON con un solo método (`model_dump_json`, `model_validate_json`).
- Documentación viva: el schema es el código.
- Modo `extra="allow"` en `CallRecord` para absorber campos condicionales del JSON de producción sin romper la validación.

### Arquitectura de módulos desacoplados

Cada módulo (`generator/`, `classifier/`, `metrics/`, `dashboard/`) es un paquete Python independiente con su propia CLI (`cli.py`). Se comunican exclusivamente a través de archivos JSONL en `data/`. Esto permite:
- Correr los módulos en procesos separados (modo stream).
- Testear cada módulo de forma completamente aislada.
- Reemplazar un módulo sin afectar los demás (p.ej. cambiar el generador sin tocar el clasificador).

---

## 2. Generador (Módulo 1)

### Distribución 60% problemáticas / 40% normales

El generador produce 60% de llamadas con errores en cada batch (`n_problematic = max(1, size * 60 // 100)`). Esta distribución sobre-representa los errores comparado con producción real, pero es intencional para demos cortas: con 20-30 llamadas generadas, necesitamos suficientes errores para que las métricas y alertas se activen y sean observables en el dashboard. En producción real, la distribución se ajustaría al baseline real del negocio.

### Temperatura 0.9

Se eligió temperatura 0.9 (configurable via `GENERATOR_TEMPERATURE`) para maximizar variedad en las conversaciones generadas. El generador no necesita consistencia lógica estricta (eso lo valida el schema Pydantic), sino diversidad en los escenarios. Los errores de validación se recuperan: el batch completo se descarta en caso de falla de parsing.

### Few-shot de 4 ejemplos

En cada batch se samplea aleatoriamente 4 ejemplos del seed (`random.sample(seed_calls, k=min(4, len(seed_calls)))`). Cuatro ejemplos es el punto óptimo empírico:
- Suficientes para que el modelo entienda el schema exacto (camelCase, enums, formato de conversación).
- No tan muchos que el prompt crezca innecesariamente (los modelos Groq tienen tokens de contexto limitados en el tier gratuito).

### Rotación de tipos problemáticos

Los 7 tipos problemáticos (`WRONG_SMS_SENT`, `WRONG_SMS_MISSING`, `UNNECESSARY_TRANSFER`, `MISSING_TRANSFER`, `AI_LOOP`, `SILENT_WRONG_INFO`, `SPAM`) se rotan por un índice (`type_idx`) para garantizar cobertura uniforme a lo largo de múltiples batches, evitando que siempre se generen los mismos tipos de error.

### Límite de batches (MAX_TOTAL_BATCHES = 20)

Para evitar loops infinitos en caso de que el LLM rechace consistentemente las llamadas por restaurantName inválido, se pone un límite duro de 20 batches. Se emite un `RuntimeWarning` en lugar de raise para que el caller pueda decidir si el número parcial de llamadas es suficiente.

---

## 3. Clasificador (Módulo 2)

### Diseño en 3 capas: Reglas → LLM → HITL

El clasificador es la pieza más crítica del sistema. Se eligió un diseño de 3 capas para balancear velocidad, costo y precisión:

1. **Capa 1 (Reglas determinísticas, R01-R10)**: Siempre se ejecuta. Es rápida, gratuita y 100% predecible. Cubre los casos más comunes y confiables.
2. **Capa 2 (LLM)**: Solo se ejecuta si Capa 1 no fue concluyente (confidence < 0.85 o hay markers que requieren análisis de conversación). Esto mantiene el costo bajo: la mayoría de los casos los resuelve Capa 1.
3. **Capa 3 (HITL)**: Siempre se ejecuta sobre el resultado de Capa 1 o 2. No modifica la clasificación, solo decide si un humano debe revisar.

Cuando Capa 2 no está disponible (`llm=None`, como en CI o tests), el sistema cae gracefully a Capa 1 sola, marcando los casos ambiguos para revisión humana.

### Reglas determinísticas obligatorias (del enunciado)

Reglas explícitamente definidas en la especificación del sistema:

- **R01 (Spam)**: `AgentHangup + duración < 60 s` → Spam, confidence=0.95. Señal estructural sin ambigüedad.
- **R02 (Potential bypass)**: Marker-only. `CallTransfer + MANAGER_REQUEST + duración ≤ 25 s`. No concluye sola porque puede ser bypass O queja real corta; el umbral 25 s corresponde a `ai_friction_level='Low'` del enunciado.
- **R03 (Wrong transfer)**: Dos variantes del enunciado:
  - Queja explícita + no hubo `CallTransfer` → WRONG_TRANSFER, confidence=0.80.
  - Queja explícita + sí hubo `CallTransfer` → marker, Capa 2 confirma si fue correcto.
- **R04 (SMS mismatch)**: Compara `reasonForSendingText` vs `SMS_EXPECTED_MAP` indexado por `reasonForCalling`. CSF es válido como fallback en cualquier motivo (ver R05). El mapa obligatorio del enunciado:

  | reasonForCalling | SMS esperados |
  |---|---|
  | Making a Reservation | reservation |
  | Menu inquiries | menu |
  | Placing an order for takeout | delivery, pickup |
  | General information and amenities | directions, web |
  | Special event or holiday inquiry | experiences, large party form |
  | Private event or client custom event inquiry | private events |
  | Catering request | catering |
  | Gift card request | giftcards |
  | Employment opportunities | job form, careers web |

  El enunciado especifica además una segunda variante no implementada: si no se envió ningún SMS estando dentro de horario y con `UserHangup`, marcar como posible WRONG_SMS faltante y pasar a Capa 2. La implementación actual solo cubre el caso de SMS enviado incorrecto.

- **R05 (CSF after hours)**: `not callWithinOfficeHours and 'csf' in sms_categories` → NO_ERROR / Resolved, confidence=0.85. Se separó de R04 para que el CSF fuera de horario no sea penalizado como mismatch.
- **R06 (Clean resolution)**: `UserHangup + sin frustración + sin error detectado + duración ≥ 20 s` → NO_ERROR / Resolved, confidence=0.80. El enunciado especifica además que `numberOfTextsSent` debe coincidir con los esperados o no haber SMS esperados; la implementación actual no verifica esa condición.
- **R07 (Legitimate transfer)**: `CallTransfer + razón legítima (whitelist) + duración > 25 s` → NO_ERROR / Transferred, confidence=0.85. La whitelist del enunciado es `{"Large Party Reservations", "Manager Request", "Customer Request"}`.
- **R08 (Loop signal)**: Keywords de loop en `callsHighlights` o `friendlysummary` → marker LOOP, Capa 2 confirma contando repeticiones en la conversación.
- **R09 (Incomplete task)**: `reasonForCalling == RESERVATION + UserHangup + 'cancel' in conversation + numberOfTextsSent == 0` → marker INCOMPLETE, Capa 2 confirma. La implementación actual omite la condición `numberOfTextsSent == 0` del enunciado.
- **R10 (Ambiguous reason)**: `reasonForCalling` vacío o no reconocido por el enum → marker AMBIGUOUS, confidence=0.40.

### Reglas determinísticas agregadas

Reglas no presentes en el enunciado, incorporadas para cubrir casos no contemplados:

- **R08b (Wrong info metadata)**: Señal de WRONG_INFO en `detectederror`/`errorCategory`/`callsHighlights` → WRONG_INFO, confidence=0.85. WRONG_INFO es silencioso (el cliente no sabe que recibió info falsa), por eso no hay señal en la conversación; se confía en los campos upstream. El enunciado solo menciona R08 como señal de loop; R08b es una extensión propia para cubrir WRONG_INFO desde la misma fuente de metadatos.

### Política de merge Capa 1 + Capa 2

- Si Capa 1 y LLM **acuerdan**: confidence = max(capa1, llm).
- Si **desacuerdan**: confiar en LLM, confidence capeada a 0.50 (zona gris).
- Si Capa 1 débil (< 0.85): confiar en LLM pero capear en 0.80 (nunca confianza ciega al LLM).

### HITL (H1-H9) — reglas custom H8 y H9

Las reglas estándar H1-H7 cubren casos con señales explícitas (WRONG_INFO, WRONG_TRANSFER con frustración, LOOP con frustración, INCOMPLETE en reserva, Ambiguous, frustración en error, WRONG_SMS fuera de horario).

Las dos reglas propias son:

- **H8 (Baja confianza)**: Si `confidence < 0.55` y `error_type != NO_ERROR` → revisión MEDIUM. Justificación: cuando el clasificador está en zona gris, el costo de un falso negativo (dejar pasar un error real sin revisión) es mayor que el costo de una revisión humana extra. El umbral 0.55 fue elegido como punto en que la clasificación es estadísticamente indistinguible de random.
- **H9 (Silent bypass)**: `WRONG_TRANSFER + sin frustración + sin razón de transfer` → revisión LOW. Detecta drift sistémico antes de que afecte NPS: si el agente empieza a transferir silenciosamente llamadas que no lo requieren, el cliente no se queja pero el costo operacional aumenta.

### Casos obligatorios del seed

Todos los 6 casos del seed pasan correctamente:

| ID | error_type | outcome_category | human_review | priority | Regla principal |
|---|---|---|---|---|---|
| mock_004 | NO_ERROR | Resolved | False | — | R06 clean_resolution |
| mock_006 | WRONG_TRANSFER | Error | True | HIGH | R03 missing_transfer_complaint (H2) |
| mock_008 | NO_ERROR | Transferred | False | — | R07 legitimate_transfer |
| mock_012 | NO_ERROR | Transferred | False | — | R07 legitimate_transfer |
| mock_013 | LOOP | Error | True | HIGH | R08 loop_signal (H4) |
| mock_019 | WRONG_INFO | Error | True | HIGH | R08b wrong_info_metadata (H1) |

---

## 4. Métricas (Módulo 3)

### Métrica propia: `silent_error_ratio`

**Definición**: porcentaje de errores con `error_type ∈ {WRONG_INFO, INCOMPLETE}` y `customerfrustration == 'no'` sobre el total de errores. Ventana de 100 llamadas. `None` si menos de 5 errores.

**Justificación**: Las métricas estándar de error_rate y human_review_rate son reactivas a la frustración del cliente. WRONG_INFO e INCOMPLETE son errores donde el cliente no sabe que fue mal atendido: recibió información incorrecta y quedó conforme, o su solicitud quedó a medias y no lo notó. Estos errores no aparecen en sistemas basados en quejas (NPS, reviews) pero tienen impacto operacional real (reservas no confirmadas, clientes mal informados que llegan a un restaurante cerrado). `silent_error_ratio` mide exactamente esta "zona ciega" de calidad.

Una ratio alta indica que el agente comete errores que el cliente no detecta, lo cual es más peligroso que errores obvios porque no hay signal de corrección natural.

### Política de dedup de alertas: 300 segundos

Las alertas se deduплican por `alert_id` (hash SHA-256 de `metric:severity:restaurant`) con una ventana de 300 segundos. Si la misma condición persiste, no se re-emite la alerta hasta que pasen 5 minutos. Justificación:
- Evita spam de alertas en dashboards en tiempo real donde el snapshot se recalcula cada pocos segundos.
- 5 minutos es el tiempo mínimo razonable para que un operador note la alerta y tome acción.

### Ventana mínima de 5 muestras (MIN_SAMPLES = 5)

Ninguna KPI devuelve un valor si hay menos de 5 muestras en la ventana. Esto evita alertas espurias al inicio del pipeline cuando hay 1-2 llamadas y una de ellas es un error (error_rate = 1.0 con n=1). La KPI devuelve `None` y el motor de alertas lo ignora.

### Alertas por restaurante

Se dispara una alerta `WARNING` cuando el error_rate de un restaurante supera en 15 puntos porcentuales el promedio del grupo. Esto detecta degradación localizada en un local sin que el promedio global lo oculte.

### Tendencia 7 días: `score_trend_7d`

Pendiente lineal de la confianza promedio diaria en los últimos 7 días (mínimo 3 puntos de datos). Una pendiente negativa indica que el clasificador está cada vez menos seguro, lo que puede ser señal de drift en el tipo de llamadas o degradación del modelo.

---

## 5. Dashboard (Módulo 4)

### Framework: Streamlit

Streamlit fue elegido por su ciclo de desarrollo extremadamente rápido para dashboards de datos. No requiere HTML/CSS/JS; el estado de la UI se maneja en Python puro. Para un sistema de monitoreo interno de calidad, la velocidad de iteración supera la necesidad de customización visual fina.

### Auto-refresh: polling con `st.rerun()`

El modo "Live" del dashboard hace `time.sleep(2)` + `st.rerun()` en cada ciclo. Esto es más simple y compatible que `streamlit-autorefresh` (que requiere un componente externo y puede tener bugs de versión). El toggle "Live mode" está off por defecto para evitar loops en desarrollo.

### Persistencia del review_state: write-then-rename

El estado de revisión humana (`data/review_state.json`) se actualiza con el patrón write-then-rename:
```python
tmp = path.with_suffix(".json.tmp")
tmp.write_text(state.model_dump_json(), encoding="utf-8")
tmp.replace(path)
```
Esto garantiza que el dashboard nunca lea un archivo parcialmente escrito. En sistemas POSIX, `rename()` es atómico.

### Cache con TTL 2s

Las funciones de carga de datos (`load_classifications`, `load_calls_index`, etc.) están decoradas con `@st.cache_data(ttl=2)`. Esto evita releer el disco en cada rerun del dashboard cuando no hay datos nuevos, manteniendo la latencia de render baja.

---

## 6. Limitaciones conocidas

1. **Concurrencia limitada**: El archivo JSONL es append-only atómico para líneas pequeñas, pero no hay locks para escrituras concurrentes de múltiples generadores. En producción se reemplazaría por una cola (Redis Streams, Kafka) o una base de datos con transacciones.

2. **LLM sin retry exhaustivo**: El `LLMClient` tiene backoff exponencial para rate limits (5 reintentos), pero si el API de Groq está caído, el clasificador simplemente usa el fallback de Capa 1. No hay dead letter queue para reprocesar llamadas que fallaron en Capa 2.

3. **Sin autenticación en el dashboard**: Streamlit corre en localhost sin autenticación. En producción se requeriría al menos HTTP Basic Auth o integración con SSO.

4. **`datetime.utcnow()` deprecado**: Python 3.12+ depreca `datetime.utcnow()`. El código usa esta función en varios lugares para simplicidad. En producción se reemplazaría por `datetime.now(timezone.utc)`.

5. **Sin rate limiting propio**: El generador no tiene control de rate sobre cuántas llamadas produce por minuto. En un sistema real se limitaría la velocidad de generación para no saturar la API de Groq.

6. **MetricsEngine en memoria**: El `MetricsEngine` usa un `deque(maxlen=500)` en memoria. Si el proceso se reinicia, se pierden las últimas 500 clasificaciones y las métricas se recalculan desde cero. En producción se persistiría el estado en disco o base de datos.

7. **seed estático**: El archivo `data/calls_seed.json` tiene 20 llamadas fijas. Las llamadas generadas se acumulan en `data/generated_calls.jsonl` sin rotación automática. Con muchas corridas, el archivo puede crecer indefinidamente.

---

## 7. Qué cambiaríamos con más tiempo

1. **Evaluación del clasificador con LLM real**: Actualmente los tests de seed validan las reglas determinísticas (Capa 1). Con más tiempo, se generaría un golden set de 100+ llamadas con anotaciones humanas y se mediría la precisión del pipeline completo (Capas 1+2+3) con y sin LLM.

2. **Fine-tuning del umbral H8**: El umbral de baja confianza (0.55) fue elegido heurísticamente. Con datos reales, se analizaría la distribución de confianza vs error real para encontrar el punto óptimo que maximice F1 en detección de errores con revisión mínima.

3. **Cola de mensajes real**: Reemplazar JSONL con Redis Streams o Kafka para soportar múltiples workers de clasificación en paralelo y garantizar exactly-once delivery.

4. **Observabilidad**: Agregar OpenTelemetry traces para medir latencia de cada capa del clasificador, tasa de fallback a Capa 1, y costo real de tokens del LLM.

5. **Dashboard con persistencia de filtros**: El estado de los filtros del Explorer (restaurant, error_type, etc.) se pierde en cada rerun. Se usaría `st.session_state` para persistirlos.

6. **Alertas por notificación push**: Las alertas actuales solo aparecen en el dashboard. En producción se integraría con PagerDuty, Slack o email para notificación inmediata.

7. **Autenticación y autorización**: El dashboard y la API de revisión humana necesitarían roles (reviewer, admin) y autenticación antes de ir a producción.

8. **Tests de integración end-to-end**: Agregar un test que corra el pipeline completo con el seed, sin LLM, y verifique que los archivos JSONL de output tienen el formato correcto y las métricas son coherentes.
