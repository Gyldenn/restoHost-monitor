"""
Capa 1: Reglas determinísticas (R01-R10).

Cada regla toma un CallRecord y devuelve RuleHit | None.
apply_rules() corre todas y devuelve (hits, markers).
"""

from dataclasses import dataclass

from shared.models import CallRecord
from shared.enums import (
    CallEndReason,
    ErrorType,
    OutcomeCategory,
    ReasonForCalling,
    YesNo,
    MANAGER_REQUEST_REASONS,
)
from shared.constants import (
    BYPASS_DURATION_THRESHOLD_SECONDS,
    SPAM_DURATION_THRESHOLD_SECONDS,
    SMS_EXPECTED_MAP,
)


@dataclass
class RuleHit:
    rule_name: str
    error_type: ErrorType | None
    outcome_category: OutcomeCategory | None
    confidence: float
    description: str
    expected: str


# ─────────────────────────────────────────────────────────────────────────
# R01 — Spam
# ─────────────────────────────────────────────────────────────────────────

def rule_spam(call: CallRecord) -> RuleHit | None:
    """
    AgentHangup + duración < 60 s → spam. Confianza alta porque es
    una señal estructural muy clara (nadie habló de verdad).
    """
    if (
        call.callEndReason == CallEndReason.AGENT_HANGUP
        and call.duration_seconds() < SPAM_DURATION_THRESHOLD_SECONDS
    ):
        return RuleHit(
            rule_name="R01_spam",
            error_type=ErrorType.NO_ERROR,
            outcome_category=OutcomeCategory.SPAM,
            confidence=0.95,
            description="Call ended by agent within 60 s — classified as spam/hang-up.",
            expected="No action required for spam calls.",
        )
    return None


# ─────────────────────────────────────────────────────────────────────────
# R02 — Potential bypass (marker only)
# ─────────────────────────────────────────────────────────────────────────

def rule_potential_bypass(call: CallRecord) -> RuleHit | None:
    """
    CallTransfer + MANAGER_REQUEST + duración ≤ 25 s → marker only.
    No concluye por sí sola: puede ser bypass O puede ser una queja real
    corta. mock_012 (2:15 min) no cae acá.
    """
    reason_enum = call.reason_enum()
    if (
        call.callEndReason == CallEndReason.CALL_TRANSFER
        and reason_enum in MANAGER_REQUEST_REASONS
        and call.duration_seconds() <= BYPASS_DURATION_THRESHOLD_SECONDS
    ):
        return RuleHit(
            rule_name="R02_potential_bypass",
            error_type=None,         # marker, no concluye
            outcome_category=None,
            confidence=0.0,
            description="Very short transfer on a manager-request call — possible bypass.",
            expected="Agent should confirm a real complaint before transferring.",
        )
    return None


# ─────────────────────────────────────────────────────────────────────────
# R03 — Missing transfer for complaint
# ─────────────────────────────────────────────────────────────────────────

_COMPLAINT_KEYWORDS = (
    "complain", "complaint", "terrible", "awful", "manager",
    "speak to someone", "speak to a person", "supervisor",
    "overcharged", "wrong charge", "bad experience",
)


def rule_missing_transfer_complaint(call: CallRecord) -> RuleHit | None:
    """
    Frustración + NO hubo CallTransfer + contexto de queja heurístico
    → marker WRONG_TRANSFER (Capa 2 confirma).
    mock_006: frustración + queja explícita + UserHangup → hit aquí.
    """
    if call.customerfrustration != YesNo.YES:
        return None
    if call.callEndReason == CallEndReason.CALL_TRANSFER:
        return None

    reason_enum = call.reason_enum()
    conv_lower = call.conversation.lower()
    summary_lower = call.friendlysummary.lower()

    has_complaint_keyword = any(kw in conv_lower for kw in _COMPLAINT_KEYWORDS)
    has_complaint_in_summary = any(kw in summary_lower for kw in _COMPLAINT_KEYWORDS)

    # Razones que implican queja o solicitud de persona
    implicit_complaint_reason = reason_enum in MANAGER_REQUEST_REASONS

    if has_complaint_keyword or has_complaint_in_summary or implicit_complaint_reason:
        return RuleHit(
            rule_name="R03_missing_transfer_complaint",
            error_type=ErrorType.WRONG_TRANSFER,
            outcome_category=OutcomeCategory.ERROR,
            confidence=0.80,
            description="Customer expressed frustration/complaint but call was not transferred.",
            expected="Agent should have escalated to a manager or human rep.",
        )
    return None


# ─────────────────────────────────────────────────────────────────────────
# R04 — SMS mismatch
# ─────────────────────────────────────────────────────────────────────────

def rule_sms_mismatch(call: CallRecord) -> RuleHit | None:
    """
    Compara SMS esperados (por reasonForCalling) con los enviados.
    Si se enviaron SMS que no corresponden → WRONG_SMS confidence=0.85.
    Si debía enviarse pero no se envió → marker (capa 2 confirma).
    """
    reason_enum = call.reason_enum()
    if reason_enum is None:
        return None

    expected_sms = SMS_EXPECTED_MAP.get(reason_enum, [])
    if not expected_sms:
        return None

    sent = call.sms_categories()
    sent_set = set(sent)
    expected_set = {s.value for s in expected_sms}

    # CSF es válido como fallback fuera de horario
    if "csf" in sent_set:
        return None

    # SMS enviado incorrecto
    if sent_set and not sent_set.intersection(expected_set):
        return RuleHit(
            rule_name="R04_sms_mismatch",
            error_type=ErrorType.WRONG_SMS,
            outcome_category=OutcomeCategory.ERROR,
            confidence=0.85,
            description=f"SMS sent ({sent}) does not match expected for reason '{reason_enum.value}' (expected one of {list(expected_set)}).",
            expected=f"Should have sent one of: {list(expected_set)}.",
        )

    # SMS faltante: dentro de horario, UserHangup, sin SMS enviado, con highlights
    if (
        not sent_set
        and call.callWithinOfficeHours
        and call.callEndReason == CallEndReason.USER_HANGUP
        and call.callsHighlights not in ("No Highlight", "")
    ):
        return RuleHit(
            rule_name="R04_sms_mismatch",
            error_type=ErrorType.WRONG_SMS,
            outcome_category=OutcomeCategory.ERROR,
            confidence=0.60,
            description=f"No SMS sent for reason '{reason_enum.value}' but one was expected ({list(expected_set)}). Capa 2 confirma.",
            expected=f"Should have sent one of: {list(expected_set)}.",
        )

    return None


# ─────────────────────────────────────────────────────────────────────────
# R05 — CSF after hours
# ─────────────────────────────────────────────────────────────────────────

def rule_csf_after_hours(call: CallRecord) -> RuleHit | None:
    """
    Si el restaurante está cerrado y se envió CSF → correcto.
    mock_002, mock_011.
    """
    if not call.callWithinOfficeHours and "csf" in call.sms_categories():
        return RuleHit(
            rule_name="R05_csf_after_hours",
            error_type=ErrorType.NO_ERROR,
            outcome_category=OutcomeCategory.RESOLVED,
            confidence=0.85,
            description="After-hours call correctly handled with CSF text.",
            expected="Agent correctly offered the customer support form when closed.",
        )
    return None


# ─────────────────────────────────────────────────────────────────────────
# R06 — Clean resolution
# ─────────────────────────────────────────────────────────────────────────

def rule_clean_resolution(call: CallRecord) -> RuleHit | None:
    """
    UserHangup + sin frustración + sin error detectado + duración ≥ 20 s
    + numberOfTextsSent coincide con esperados (o no hay SMS esperados)
    → Resolved, NO_ERROR, confidence=0.80.
    """
    reason_enum = call.reason_enum()
    expected_sms = SMS_EXPECTED_MAP.get(reason_enum, []) if reason_enum else []
    sms_ok = (not expected_sms) or (call.numberOfTextsSent == len(expected_sms))

    if (
        call.callEndReason == CallEndReason.USER_HANGUP
        and call.customerfrustration == YesNo.NO
        and call.detectederror == "No Error Detected"
        and call.duration_seconds() >= 20
        and sms_ok
    ):
        return RuleHit(
            rule_name="R06_clean_resolution",
            error_type=ErrorType.NO_ERROR,
            outcome_category=OutcomeCategory.RESOLVED,
            confidence=0.80,
            description="Call ended cleanly by user with no frustration or detected errors.",
            expected="Agent performed correctly throughout the call.",
        )
    return None


# ─────────────────────────────────────────────────────────────────────────
# R07 — Legitimate transfer
# ─────────────────────────────────────────────────────────────────────────

_LEGITIMATE_TRANSFER_REASONS = {
    "Large Party Reservations",
    "Manager Request",
    "Customer Request",
}


def rule_legitimate_transfer(call: CallRecord) -> RuleHit | None:
    """
    CallTransfer + razón legítima + duración > 25 s
    → Transferred, NO_ERROR, confidence=0.85.
    mock_001, mock_012.
    """
    if (
        call.callEndReason == CallEndReason.CALL_TRANSFER
        and call.reasonForTransfering in _LEGITIMATE_TRANSFER_REASONS
        and call.duration_seconds() > BYPASS_DURATION_THRESHOLD_SECONDS
    ):
        return RuleHit(
            rule_name="R07_legitimate_transfer",
            error_type=ErrorType.NO_ERROR,
            outcome_category=OutcomeCategory.TRANSFERRED,
            confidence=0.85,
            description=f"Call legitimately transferred for reason: '{call.reasonForTransfering}'.",
            expected="Transfer was appropriate given the complexity or explicit request.",
        )
    return None


# ─────────────────────────────────────────────────────────────────────────
# R08 — Loop signal from metadata (marker)
# ─────────────────────────────────────────────────────────────────────────

_LOOP_KEYWORDS_HIGHLIGHTS = ("loop", "circles", "repeated", "looped")
_LOOP_KEYWORDS_SUMMARY = ("loop", "circles", "repeated", "again", "looped")
_LOOP_KEYWORDS_CONV = ("going in circles", "i already told you", "i just told you",
                       "i said", "you already asked", "again")


def rule_loop_signal_from_metadata(call: CallRecord) -> RuleHit | None:
    """
    Señal de loop en highlights o summary → marker LOOP.
    Capa 2 confirma contando repeticiones en la conversación.
    """
    highlights_lower = call.callsHighlights.lower()
    summary_lower = call.friendlysummary.lower()
    conv_lower = call.conversation.lower()

    in_highlights = any(kw in highlights_lower for kw in _LOOP_KEYWORDS_HIGHLIGHTS)
    in_summary = any(kw in summary_lower for kw in _LOOP_KEYWORDS_SUMMARY)
    in_conv = any(kw in conv_lower for kw in _LOOP_KEYWORDS_CONV)

    if in_highlights or in_summary or in_conv:
        return RuleHit(
            rule_name="R08_loop_signal",
            error_type=ErrorType.LOOP,
            outcome_category=OutcomeCategory.ERROR,
            confidence=0.85,
            description="Loop signal detected: agent repeated questions already answered.",
            expected="Agent should track provided information and not re-ask.",
        )
    return None


# ─────────────────────────────────────────────────────────────────────────
# R08b — Wrong info signal from metadata
# ─────────────────────────────────────────────────────────────────────────
#
# Nota: WRONG_INFO suele ser un error silencioso (el cliente no sabe que la
# info es falsa, por eso no hay frustración). Por eso la única señal en la
# Capa 1 viene de los campos de metadatos ya procesados upstream
# (detectederror, errorCategory, callsHighlights). Confiamos en ellos como
# pista fuerte (confidence=0.85) porque fueron puestos por un sistema upstream
# auditado; Capa 2 puede confirmar si el LLM está disponible.

_WRONG_INFO_ERROR_STRINGS = (
    "wrong information",
    "incorrect information",
    "wrong info",
    "factual error",
    "incorrect answer",
)

_WRONG_INFO_HIGHLIGHT_STRINGS = (
    "incorrect",
    "wrong information",
    "factual error",
    "silent error",
    "wrong info",
)


def rule_wrong_info_from_metadata(call: CallRecord) -> RuleHit | None:
    """
    Señal de WRONG_INFO en detectederror / errorCategory / callsHighlights.
    Confianza 0.85: el sistema upstream marcó explícitamente un error factual.
    mock_019: "Wrong Information Provided" + "Factual Error" + "incorrect parking info".
    """
    detected_lower = call.detectederror.lower()
    error_cat_lower = call.errorCategory.lower()
    highlights_lower = call.callsHighlights.lower()

    in_detected = any(kw in detected_lower for kw in _WRONG_INFO_ERROR_STRINGS)
    in_category = any(kw in error_cat_lower for kw in _WRONG_INFO_ERROR_STRINGS)
    in_highlights = any(kw in highlights_lower for kw in _WRONG_INFO_HIGHLIGHT_STRINGS)

    if in_detected or in_category or in_highlights:
        return RuleHit(
            rule_name="R08b_wrong_info_metadata",
            error_type=ErrorType.WRONG_INFO,
            outcome_category=OutcomeCategory.ERROR,
            confidence=0.85,
            description="Metadata signals indicate the agent provided factually incorrect information.",
            expected="Agent should verify and provide accurate information about the restaurant.",
        )
    return None


# ─────────────────────────────────────────────────────────────────────────
# R09 — Incomplete task (marker)
# ─────────────────────────────────────────────────────────────────────────

_CANCEL_KEYWORDS = ("cancel", "cancelar", "cancellation", "drop", "remove reservation")
_INCOMPLETE_TASK_KEYWORDS = ("i've noted", "i've registered", "your request has been received",
                              "i've registered", "noted your request", "registered the information",
                              "noted", "received your", "i understand")


def rule_incomplete_task(call: CallRecord) -> RuleHit | None:
    """
    Reservación + UserHangup + numberOfTextsSent == 0 + hints de tarea incompleta
    → marker INCOMPLETE.
    mock_016: cancelación con respuestas vagas sin confirmar.
    """
    reason_enum = call.reason_enum()
    if reason_enum != ReasonForCalling.RESERVATION:
        return None
    if call.callEndReason != CallEndReason.USER_HANGUP:
        return None
    if call.numberOfTextsSent != 0:
        return None

    conv_lower = call.conversation.lower()
    has_cancel_intent = any(kw in conv_lower for kw in _CANCEL_KEYWORDS)
    has_vague_response = any(kw in conv_lower for kw in _INCOMPLETE_TASK_KEYWORDS)

    # También detectar si el detectederror indica algo no resuelto
    error_hints = call.detectederror not in ("No Error Detected", "")
    highlights_incomplete = any(
        kw in call.callsHighlights.lower()
        for kw in ("unconfirmed", "incomplete", "unresolved", "not confirm", "left uncertain")
    )

    if has_cancel_intent or (error_hints and has_vague_response) or highlights_incomplete:
        return RuleHit(
            rule_name="R09_incomplete_task",
            error_type=ErrorType.INCOMPLETE,
            outcome_category=OutcomeCategory.ERROR,
            confidence=0.85,
            description="Task appears incomplete: agent gave vague non-confirmations or failed to complete reservation action.",
            expected="Agent should have explicitly confirmed or denied the requested action.",
        )
    return None


# ─────────────────────────────────────────────────────────────────────────
# R10 — Ambiguous reason
# ─────────────────────────────────────────────────────────────────────────

def rule_ambiguous_reason(call: CallRecord) -> RuleHit | None:
    """
    Si reasonForCalling es vacío o no reconocido → marker Ambiguous.
    Otras reglas pueden sobreescribir.
    """
    if not call.reasonForCalling or call.reason_enum() is None:
        return RuleHit(
            rule_name="R10_ambiguous_reason",
            error_type=ErrorType.AMBIGUOUS,
            outcome_category=OutcomeCategory.AMBIGUOUS,
            confidence=0.40,
            description="Reason for calling is empty or unrecognized.",
            expected="Call should have a classified reason for calling.",
        )
    return None


# ─────────────────────────────────────────────────────────────────────────
# Combinador
# ─────────────────────────────────────────────────────────────────────────

# Reglas que solo producen markers (no concluyen por sí solas)
_MARKER_ONLY_RULES = {"R02_potential_bypass"}

# Reglas que producen markers pero también pueden concluir
_MARKER_RULES_MAP = {
    "R02_potential_bypass": "potential_bypass",
    "R03_missing_transfer_complaint": "missing_transfer_complaint",
    "R08_loop_signal": "loop_signal",
    "R09_incomplete_task": "incomplete_task",
    "R10_ambiguous_reason": "ambiguous_reason",
}


def apply_rules(call: CallRecord) -> tuple[list[RuleHit], list[str]]:
    """
    Aplica todas las reglas R01-R10 y devuelve (hits, markers).

    - hits: todos los RuleHit con error_type no None.
    - markers: strings que pasan info adicional a Capa 2.

    Si al menos un hit tiene confidence >= 0.85 y no hay markers
    contradictorios, Capa 1 es suficiente.
    """
    raw_results: list[RuleHit | None] = [
        rule_spam(call),
        rule_potential_bypass(call),
        rule_missing_transfer_complaint(call),
        rule_sms_mismatch(call),
        rule_csf_after_hours(call),
        rule_clean_resolution(call),
        rule_legitimate_transfer(call),
        rule_loop_signal_from_metadata(call),
        rule_wrong_info_from_metadata(call),
        rule_incomplete_task(call),
        rule_ambiguous_reason(call),
    ]

    hits: list[RuleHit] = []
    markers: list[str] = []

    for hit in raw_results:
        if hit is None:
            continue
        # Agregar marker si corresponde
        if hit.rule_name in _MARKER_RULES_MAP:
            markers.append(_MARKER_RULES_MAP[hit.rule_name])
        # Solo agregar a hits si tiene error_type y no es marker-only sin conclusión
        if hit.error_type is not None and hit.rule_name not in _MARKER_ONLY_RULES:
            hits.append(hit)

    return hits, markers
