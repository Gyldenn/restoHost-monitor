"""
Entry point del módulo clasificador.

classify_call(call, llm=None) → Classification
  - llm=None → solo capas 1 y 3 (modo offline/CI).
  - llm=LLMClient → capas 1 + 2 + 3.

Función pura: no escribe archivos, no tiene efectos secundarios.
"""

import logging
from datetime import datetime

from shared.enums import ErrorType, OutcomeCategory
from shared.llm_client import LLMClient
from shared.models import CallRecord, Classification
from classifier.rules import RuleHit, apply_rules
from classifier.llm_classifier import LLMClassification, analyze_with_llm
from classifier.human_review import needs_human_review

log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────
# Helpers internos
# ─────────────────────────────────────────────────────────────────────────

def _best_hit(hits: list[RuleHit]) -> RuleHit | None:
    """Devuelve el hit con mayor confidence."""
    if not hits:
        return None
    return max(hits, key=lambda h: h.confidence)


def _layer1_conclusive(hits: list[RuleHit], markers: list[str]) -> bool:
    """
    Capa 1 es suficiente si hay al menos un hit con confidence >= 0.85
    y no hay markers que requieran confirmación de Capa 2.
    """
    requires_llm_markers = {
        "potential_bypass",
        "loop_signal",
        "missing_transfer_complaint",   # confirmación por conversación recomendada
        "incomplete_task",              # confirmación por conversación recomendada
    }
    conclusive_hits = [h for h in hits if h.confidence >= 0.85]
    if not conclusive_hits:
        return False
    conflicting_markers = requires_llm_markers.intersection(set(markers))
    return len(conflicting_markers) == 0


def _merge_layers(
    hits: list[RuleHit],
    llm_result: LLMClassification,
    markers: list[str],
) -> tuple[ErrorType, OutcomeCategory, float, str, str, list[str]]:
    """
    Combina capa 1 y capa 2 según la política documentada.

    Devuelve (error_type, outcome_category, confidence, description, expected, rules_triggered).
    """
    best = _best_hit(hits)
    rules_triggered = [h.rule_name for h in hits if h.error_type == llm_result.error_type]

    if best is not None and best.confidence >= 0.85:
        if best.error_type == llm_result.error_type:
            # Acuerdo: tomar máximo de confidencias
            final_conf = max(best.confidence, llm_result.confidence)
        else:
            # Desacuerdo: confiar en LLM, bajar confianza
            log.info(
                "Layer 1 (%s conf=%.2f) disagrees with LLM (%s conf=%.2f) — using LLM at 0.5",
                best.error_type,
                best.confidence,
                llm_result.error_type,
                llm_result.confidence,
            )
            final_conf = 0.5
            rules_triggered = []
    else:
        # Capa 1 débil → confiar en LLM pero capear en 0.80
        final_conf = min(llm_result.confidence, 0.80)

    return (
        llm_result.error_type,
        llm_result.outcome_category,
        final_conf,
        llm_result.error_description,
        llm_result.expected_behavior,
        rules_triggered,
    )


def _classification_from_hit(
    call: CallRecord,
    hit: RuleHit,
    all_hits: list[RuleHit],
    markers: list[str],
) -> Classification:
    """Construye una Classification a partir del mejor RuleHit de Capa 1."""
    rules_triggered = [h.rule_name for h in all_hits if h.error_type is not None]

    required, priority, reason = needs_human_review(
        call,
        error_type=hit.error_type,
        outcome_category=hit.outcome_category,
        confidence=hit.confidence,
    )

    return Classification(
        conversationId=call.conversationId,
        outcome_category=hit.outcome_category,
        error_type=hit.error_type,
        error_description=hit.description,
        expected_behavior=hit.expected,
        human_review_required=required,
        human_review_reason=reason,
        human_review_priority=priority,
        confidence=hit.confidence,
        rules_triggered=rules_triggered,
        classified_at=datetime.utcnow(),
    )


def _fallback_classification(
    call: CallRecord,
    hits: list[RuleHit],
    markers: list[str],
) -> Classification:
    """
    Fallback cuando Capa 2 falla 2 veces.
    - Si hay hits: usar el de mayor confidence.
    - Si no: AMBIGUOUS, confidence=0.3, marker llm_unavailable.
    """
    best = _best_hit(hits)
    if best is not None:
        log.warning(
            "LLM unavailable for %s — falling back to best rule hit (conf=%.2f)",
            call.conversationId,
            best.confidence,
        )
        return _classification_from_hit(call, best, hits, markers)

    log.error("LLM unavailable and no rule hits for %s — full fallback", call.conversationId)
    error_type = ErrorType.AMBIGUOUS
    outcome = OutcomeCategory.AMBIGUOUS
    confidence = 0.3
    all_markers = list(markers) + ["llm_unavailable"]

    required, priority, reason = needs_human_review(
        call,
        error_type=error_type,
        outcome_category=outcome,
        confidence=confidence,
    )
    return Classification(
        conversationId=call.conversationId,
        outcome_category=outcome,
        error_type=error_type,
        error_description="Classification could not be determined: LLM unavailable and no deterministic rules matched.",
        expected_behavior="Manual review required.",
        human_review_required=required,
        human_review_reason=reason,
        human_review_priority=priority,
        confidence=confidence,
        rules_triggered=all_markers,
        classified_at=datetime.utcnow(),
    )


# ─────────────────────────────────────────────────────────────────────────
# Entry point público
# ─────────────────────────────────────────────────────────────────────────

def classify_call(call: CallRecord, llm: LLMClient | None = None) -> Classification:
    """
    Clasifica una llamada pasando por las 3 capas:

      Capa 1 → Reglas determinísticas (siempre se aplica)
      Capa 2 → LLM (solo si llm != None y Capa 1 no concluyó)
      Capa 3 → HITL (siempre se aplica sobre el resultado de 1 o 2)

    Si llm=None → solo capas 1 y 3 (modo offline).
    Función pura: no escribe archivos.
    """
    # ── Capa 1 ──────────────────────────────────────────────────────────
    hits, markers = apply_rules(call)
    log.debug(
        "%s → capa1 hits=%d markers=%s",
        call.conversationId,
        len(hits),
        markers,
    )

    # ── Decisión: ¿es suficiente Capa 1? ────────────────────────────────
    if _layer1_conclusive(hits, markers) or llm is None:
        # Usar Capa 1 directamente
        best = _best_hit(hits)
        if best is not None:
            return _classification_from_hit(call, best, hits, markers)
        # Sin hits → fallback mínimo sin LLM
        error_type = ErrorType.AMBIGUOUS
        outcome = OutcomeCategory.AMBIGUOUS
        confidence = 0.3
        required, priority, reason = needs_human_review(call, error_type, outcome, confidence)
        return Classification(
            conversationId=call.conversationId,
            outcome_category=outcome,
            error_type=error_type,
            error_description="No deterministic rule matched and LLM not available.",
            expected_behavior="Manual review required.",
            human_review_required=required,
            human_review_reason=reason,
            human_review_priority=priority,
            confidence=confidence,
            rules_triggered=list(markers),
            classified_at=datetime.utcnow(),
        )

    # ── Capa 2 (LLM) ────────────────────────────────────────────────────
    try:
        llm_result = analyze_with_llm(call, markers, llm)
    except Exception as e:
        log.error("LLM failed for %s: %s — using fallback", call.conversationId, e)
        return _fallback_classification(call, hits, markers)

    # ── Combinar Capas 1 + 2 ────────────────────────────────────────────
    error_type, outcome_cat, confidence, description, expected, rules_triggered = _merge_layers(
        hits, llm_result, markers
    )

    # ── Capa 3 (HITL) ───────────────────────────────────────────────────
    required, priority, reason = needs_human_review(call, error_type, outcome_cat, confidence)

    return Classification(
        conversationId=call.conversationId,
        outcome_category=outcome_cat,
        error_type=error_type,
        error_description=description,
        expected_behavior=expected,
        human_review_required=required,
        human_review_reason=reason,
        human_review_priority=priority,
        confidence=confidence,
        rules_triggered=rules_triggered,
        classified_at=datetime.utcnow(),
    )
