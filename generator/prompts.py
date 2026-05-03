"""Prompts para el generador de llamadas sintéticas."""

import json
import random
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from shared.models import CallRecord

SYSTEM_PROMPT = """\
Sos un generador de llamadas sintéticas que simula el agente de voz de RestoHost en restaurantes Baires Grill (BG Las Olas, BG Doral, BG Brickell).

## Valores válidos de reasonForCalling

| Valor exacto |
|---|
| Making a Reservation or Inquiring About Reservations |
| Questions about restaurant hours and wait times |
| General information and amenities |
| Special event or holiday inquiry |
| Placing an order for takeout or delivery |
| Menu inquiries and special dietary needs |
| Lost items inquiries |
| Employment opportunities or business inquiries |
| Assistance with online platforms and technical issues |
| Private event or client custom event inquiry |
| Catering request |
| Gift card request |
| Payment issues |
| Request to speak to a human, to a person, to customer service, to the host or the hostess |
| Request to speak to a human, to a person, to customer support, to the representative or to someone |
| NULL (sin clasificar) |

## Valores válidos de SmsCategory (campo reasonForSendingText)

reservation, csf, menu, directions, delivery, large party form, experiences, waitlist, private events, catering, giftcards, job form, careers web, social media, web, pickup

## Valores válidos de callEndReason

AgentHangup, UserHangup, UserInactivity, CallTransfer

## Schema de output

Debés devolver un JSON object con la siguiente estructura EXACTA:
{"calls": [<call>, <call>, ...]}

Cada call debe tener EXACTAMENTE estos campos (ninguno más, ninguno menos salvo los opcionales del seed):
- conversationId: string con prefijo "gen_" seguido de un UUID corto (ej: "gen_a1b2c3d4")
- restaurantName: uno de "BG Las Olas", "BG Doral", "BG Brickell"
- callStartTime: ISO 8601 con offset -04:00, dentro de las últimas 72 horas
- callDuration: formato "MM:SS" (ej: "02:34")
- callEndReason: uno de los valores válidos de callEndReason
- callWithinOfficeHours: boolean true o false
- reasonForCalling: uno de los valores exactos de la tabla de arriba
- reasonForTransfering: string (vacío si no hubo transferencia)
- reasonForSendingText: string CSV de SmsCategory (vacío si no se enviaron SMS)
- numberOfTextsSent: integer >= 0
- partySize: string (vacío, "Small party", "Large party", etc.)
- partysizenumber: string (número como string o vacío)
- detectederror: "No Error Detected" o descripción del error
- errorCategory: "No Error Detected" o categoría del error
- customerfrustration: "yes" o "no"
- speakInSpanish: "yes" o "no"
- menuMention: "yes" o "no"
- eventMention: "yes" o "no"
- callsHighlights: "No Highlight" o descripción breve del highlight
- friendlysummary: 1-2 oraciones desde la perspectiva de un revisor de calidad
- conversation: diálogo plausible en formato "Assistant: ...\nCustomer: ..." específico al motivo

## Instrucción de variedad

Cada batch debe incluir al menos los tipos problemáticos especificados en el user prompt.
Las llamadas normales deben variar sus reasonForCalling, restaurantName, callEndReason y conversación.
Las conversaciones deben ser específicas y plausibles — no genéricas.
"""


def build_user_prompt(
    seed_examples: "list[CallRecord]",
    batch_size: int,
    n_problematic: int,
    chosen_types: list[str],
) -> str:
    """Construye el user prompt para un batch de llamadas.

    Args:
        seed_examples: Ejemplos del seed para few-shot
        batch_size: Número total de llamadas a generar
        n_problematic: Número de llamadas problemáticas
        chosen_types: Lista de tipos problemáticos a incluir
    """
    n_normal = batch_size - n_problematic

    # Serializar ejemplos como JSON pretty
    examples_json = json.dumps(
        [ex.model_dump() for ex in seed_examples],
        indent=2,
        ensure_ascii=False,
    )

    types_str = ", ".join(chosen_types)

    prompt = f"""Generá {batch_size} llamadas siguiendo este schema. Acá tenés ejemplos reales:

{examples_json}

Distribución para este batch:
- {n_normal} llamadas normales (resoluciones limpias o transferencias correctas) variando reasonForCalling
- {n_problematic} llamadas problemáticas, una de cada uno de estos tipos: {types_str}

Tipos problemáticos disponibles (rotar por batch):
1. WRONG_SMS_SENT: SMS incorrecto. Ej: cliente pide reserva, se envía 'menu'.
2. WRONG_SMS_MISSING: tarea completada pero numberOfTextsSent=0 cuando debía haberse enviado.
3. UNNECESSARY_TRANSFER: cliente pide hablar con alguien sin razón compleja, AI transfiere en <25s.
4. MISSING_TRANSFER: queja seria + pedido de manager sin CallTransfer.
5. AI_LOOP: AI repite la misma pregunta 2+ veces ignorando info dada.
6. SILENT_WRONG_INFO: info incorrecta dada, customerfrustration='no'.
7. SPAM: AgentHangup, callDuration < 60s, sin interacción real.

Reglas estrictas:
- conversationId con prefijo 'gen_' y un UUID corto (ej: "gen_a1b2c3d4").
- restaurantName ∈ {{"BG Las Olas","BG Doral","BG Brickell"}}.
- callStartTime: ISO 8601 con offset -04:00, dentro de las últimas 72 horas.
- callDuration formato MM:SS.
- Cada campo del schema presente, sin campos extra inventados.
- conversation: diálogo Assistant/Customer plausible y específico al motivo.
- friendlysummary: 1-2 oraciones desde la perspectiva de un revisor.

Devolvé solo JSON: {{"calls": [<call>, <call>, ...]}}."""

    return prompt
