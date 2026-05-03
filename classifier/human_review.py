"""
Capa 3: política Human-in-the-loop (HITL).

Reglas H1-H9 aplicadas en orden de prioridad descendente.
Devuelve (required, priority, reason).
"""

from shared.enums import ErrorType, OutcomeCategory, Priority, YesNo
from shared.models import CallRecord


def needs_human_review(
    call: CallRecord,
    error_type: ErrorType,
    outcome_category: OutcomeCategory,
    confidence: float,
) -> tuple[bool, Priority | None, str]:
    """
    Aplica las reglas H1..H9 en orden de prioridad decreciente.
    Devuelve (required, priority, reason).
    Devuelve (False, None, "") si ninguna regla aplica.

    Orden de evaluación: HIGH primero, luego MEDIUM, luego LOW.
    Toma la primera que matchea (mayor prioridad primero).
    """

    # ── H1: WRONG_INFO → HIGH (error silencioso, sin revisión nunca se detecta) ──
    if error_type == ErrorType.WRONG_INFO:
        return (
            True,
            Priority.HIGH,
            "H1: WRONG_INFO — silent factual error; only human review can catch it.",
        )

    # ── H2: WRONG_TRANSFER + frustración → HIGH (impacto NPS directo) ──
    if error_type == ErrorType.WRONG_TRANSFER and call.customerfrustration == YesNo.YES:
        return (
            True,
            Priority.HIGH,
            "H2: WRONG_TRANSFER with customer frustration — direct NPS impact.",
        )

    # ── H4: LOOP + frustración → HIGH (problema sistémico en el prompt) ──
    if error_type == ErrorType.LOOP and call.customerfrustration == YesNo.YES:
        return (
            True,
            Priority.HIGH,
            "H4: LOOP with customer frustration — indicates systemic issue in agent prompt.",
        )

    # ── H5: INCOMPLETE + Reservation → HIGH (reserva no confirmada, riesgo operativo) ──
    if (
        error_type == ErrorType.INCOMPLETE
        and "Reservation" in call.reasonForCalling
    ):
        return (
            True,
            Priority.HIGH,
            "H5: INCOMPLETE on reservation call — unconfirmed reservation is an operational risk.",
        )

    # ── H3: outcome Ambiguous → MEDIUM (sistema no puede decidir) ──
    if outcome_category == OutcomeCategory.AMBIGUOUS:
        return (
            True,
            Priority.MEDIUM,
            "H3: Ambiguous outcome — human judgment required.",
        )

    # ── H6: frustración + Error → MEDIUM ──
    if call.customerfrustration == YesNo.YES and outcome_category == OutcomeCategory.ERROR:
        return (
            True,
            Priority.MEDIUM,
            "H6: Customer frustration on an error outcome — quality risk.",
        )

    # ── H7: WRONG_SMS fuera de horario → MEDIUM ──
    if error_type == ErrorType.WRONG_SMS and not call.callWithinOfficeHours:
        return (
            True,
            Priority.MEDIUM,
            "H7: WRONG_SMS outside office hours — customer left without adequate follow-up.",
        )

    # ── H8: baja confianza en clasificaciones no-NO_ERROR → MEDIUM ──
    # Justificación: cuando el clasificador no está seguro, un falso negativo
    # (dejar pasar un error real) es más costoso que una revisión humana extra.
    # Umbral 0.55: por debajo de este valor las reglas/LLM están en zona gris.
    if confidence < 0.55 and error_type != ErrorType.NO_ERROR:
        return (
            True,
            Priority.MEDIUM,
            f"H8: Low classification confidence ({confidence:.2f}) on non-NO_ERROR call — review recommended.",
        )

    # ── H9: WRONG_TRANSFER sin frustración y sin razón de transfer → LOW ──
    # Bypass silencioso: cliente no se quejó pero la transferencia fue innecesaria.
    # Detecta drift sistémico antes de que afecte NPS.
    if (
        error_type == ErrorType.WRONG_TRANSFER
        and call.customerfrustration == YesNo.NO
        and not call.reasonForTransfering.strip()
    ):
        return (
            True,
            Priority.LOW,
            "H9: Silent bypass — unnecessary transfer without customer complaint; potential systemic drift.",
        )

    return False, None, ""
