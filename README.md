# RestoHost Quality Monitoring System

Sistema de monitoreo de calidad para el agente de voz de RestoHost en los restaurantes Baires Grill (BG Las Olas, BG Doral, BG Brickell).

El sistema genera llamadas sintéticas con un LLM, las clasifica automáticamente en capas (reglas determinísticas + LLM + HITL), calcula métricas de calidad en tiempo real y expone un dashboard de monitoreo.

---

## Setup

### 1. Crear y activar entorno virtual

```bash
cd restohost-monitor
python3 -m venv .venv
source .venv/bin/activate
```

### 2. Instalar dependencias

```bash
pip install -r requirements.txt
```

### 3. Configurar credenciales

```bash
cp .env.example .env
# Editar .env y completar GROQ_API_KEY
```

El archivo `.env` debe tener:

```
GROQ_API_KEY=gsk_...
GROQ_MODEL=llama-3.3-70b-versatile   # opcional, este es el default
GENERATOR_BATCH_SIZE=5               # opcional
GENERATOR_TEMPERATURE=0.9            # opcional
```

---

## Cómo correr

### Modo batch (secuencial)

Genera N llamadas, las clasifica y calcula métricas, todo en secuencia:

```bash
python main.py --mode batch --n 30
```

### Modo stream (procesos paralelos)

Arranca generador, clasificador y motor de métricas como procesos separados. Cada módulo lee del JSONL del anterior en tiempo real:

```bash
python main.py --mode stream --n 30
```

Luego, en otra terminal, abrir el dashboard:

```bash
streamlit run dashboard/app.py
```

o directamente correr 
```bash
streamlit run dashboard/app.py
```
y hacer click en "start" en "http://localhost:8501".



El dashboard estará disponible en `http://localhost:8501`.

### Correr módulos individualmente

```bash
# Generar llamadas
python -m generator.cli --n 20 --out data/generated_calls.jsonl

# Clasificar (modo batch)
python -m classifier.cli --input data/generated_calls.jsonl --output data/classified_calls.jsonl

# Clasificar (modo stream, sigue el archivo)
python -m classifier.cli --input data/generated_calls.jsonl --output data/classified_calls.jsonl --stream

# Calcular métricas
python -m metrics.cli --batch
```

---

## Cómo correr los tests

```bash
python3 -m pytest generator/tests/ classifier/tests/ metrics/tests/ dashboard/tests/ -v
```

Los tests no requieren `GROQ_API_KEY` — el clasificador se ejecuta en modo offline (solo Capa 1, sin LLM).

Para correr solo los tests de un módulo:

```bash
python3 -m pytest classifier/tests/ -v
python3 -m pytest metrics/tests/ -v
```

---

## Estructura del proyecto

```
restohost-monitor/
├── main.py                     # Orquestador del pipeline
├── requirements.txt
├── .env.example
├── DECISIONS.md                # Decisiones de diseño
│
├── data/
│   ├── calls_seed.json         # 20 llamadas reales anotadas
│   ├── generated_calls.jsonl   # Llamadas sintéticas generadas (creado en runtime)
│   ├── classified_calls.jsonl  # Clasificaciones (creado en runtime)
│   ├── alerts.jsonl            # Alertas disparadas (creado en runtime)
│   ├── current_metrics.json    # Snapshot de métricas actual (creado en runtime)
│   └── review_state.json       # Estado de revisión humana (creado en runtime)
│
├── shared/                     # Modelos, enums y utilidades compartidas
│   ├── models.py               # CallRecord, Classification, Alert, MetricsSnapshot, ReviewState
│   ├── enums.py                # ErrorType, OutcomeCategory, Priority, AlertSeverity, ...
│   ├── constants.py            # SMS_EXPECTED_MAP, THRESHOLDS, umbrales
│   ├── llm_client.py           # Wrapper Groq con JSON mode y backoff
│   └── io.py                   # append_event(), read_all(), tail_follow()
│
├── generator/                  # Módulo 1: generación de llamadas sintéticas
│   ├── generator.py            # generate() — función pura, itera CallRecord
│   ├── prompts.py              # SYSTEM_PROMPT y build_user_prompt()
│   └── cli.py                  # Punto de entrada CLI
│
├── classifier/                 # Módulo 2: clasificación en 3 capas
│   ├── classifier.py           # classify_call() — entry point
│   ├── rules.py                # Capa 1: reglas R01-R10
│   ├── llm_classifier.py       # Capa 2: análisis con LLM
│   ├── human_review.py         # Capa 3: política HITL H1-H9
│   └── cli.py
│
├── metrics/                    # Módulo 3: KPIs y alertas
│   ├── engine.py               # MetricsEngine (stateful, deque maxlen=500)
│   ├── kpis.py                 # Funciones puras: resolution_rate, error_rate, silent_error_ratio, ...
│   ├── alerts.py               # check_alerts(), ALERT_RULES, dedup 300s
│   └── cli.py
│
└── dashboard/                  # Módulo 4: Streamlit dashboard
    ├── app.py                  # Entry point: streamlit run dashboard/app.py
    ├── state.py                # Carga de datos, mark_reviewed(), start/stop pipeline
    ├── components.py           # get_kpi_status(), priority_badge(), severity_color()
    └── views/                  # health.py, errors.py, review_queue.py, explorer.py
```

---

## Arquitectura del pipeline

```
calls_seed.json
       │
       ▼
[generator] ──► generated_calls.jsonl
                        │
                        ▼
               [classifier] ──► classified_calls.jsonl
                                         │
                                         ▼
                                  [metrics engine] ──► current_metrics.json
                                                   └──► alerts.jsonl
                                                            │
                                                            ▼
                                                     [dashboard]
```

En modo stream, los módulos corren en paralelo y cada uno hace `tail_follow()` del JSONL del módulo anterior.

---

## Decisiones de diseño

Ver [DECISIONS.md](./DECISIONS.md) para justificaciones detalladas sobre:
- Stack (Groq, JSONL, Pydantic)
- Distribución del generador (60/40, temperatura 0.9, few-shot 4 ejemplos)
- Diseño del clasificador en 3 capas (reglas + LLM + HITL)
- Métrica propia `silent_error_ratio`
- Política de dedup de alertas (300 s)
- Limitaciones conocidas y mejoras futuras
