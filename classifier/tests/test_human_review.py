"""
Tests de la política Human-in-the-loop (H1-H9).
"""

import pytest

from shared.enums import (
    CallEndReason,
    ErrorType,
    OutcomeCategory,
    Priority,
    ReasonForCalling,
    YesNo,
)
from shared.models import CallRecord
from classifier.human_review import needs_human_review


def make_call(**kwargs) -> CallRecord:
    defaults = dict(
        conversationId="test_hitl",
        restaurantName="BG Brickell",
        callStartTime="2026-04-01T19:00:00.000-04:00",
        callDuration="01:00",
        callEndReason=CallEndReason.USER_HANGUP,
        callWithinOfficeHours=True,
        reasonForCalling=ReasonForCalling.RESERVATION.value,
        reasonForTransfering="",
        reasonForSendingText="",
        numberOfTextsSent=0,
        detectederror="No Error Detected",
        errorCategory="No Error Detected",
        customerfrustration=YesNo.NO,
        speakInSpanish=YesNo.NO,
        menuMention=YesNo.NO,
        eventMention=YesNo.NO,
        callsHighlights="No Highlight",
        friendlysummary="Test call.",
        conversation="Assistant: Hi.\nCustomer: Hello.",
    )
    defaults.update(kwargs)
    return CallRecord.model_validate(defaults)


# ─────────────────────────────────────────────────────────────────────────
# H1 — WRONG_INFO → HIGH
# ─────────────────────────────────────────────────────────────────────────

class TestH1WrongInfo:
    def test_wrong_info_requires_high_review(self):
        """H1: WRONG_INFO siempre requiere revisión HIGH."""
        call = make_call()
        required, priority, reason = needs_human_review(
            call,
            error_type=ErrorType.WRONG_INFO,
            outcome_category=OutcomeCategory.ERROR,
            confidence=0.90,
        )
        assert required is True
        assert priority == Priority.HIGH
        assert "H1" in reason

    def test_wrong_info_even_without_frustration(self):
        """H1: WRONG_INFO requiere revisión incluso sin frustración (error silencioso)."""
        call = make_call(customerfrustration=YesNo.NO)
        required, priority, _ = needs_human_review(
            call,
            error_type=ErrorType.WRONG_INFO,
            outcome_category=OutcomeCategory.ERROR,
            confidence=0.95,
        )
        assert required is True
        assert priority == Priority.HIGH


# ─────────────────────────────────────────────────────────────────────────
# H2 — WRONG_TRANSFER + frustración → HIGH
# ─────────────────────────────────────────────────────────────────────────

class TestH2WrongTransferFrustration:
    def test_wrong_transfer_with_frustration(self):
        """H2: WRONG_TRANSFER + frustración → HIGH."""
        call = make_call(customerfrustration=YesNo.YES)
        required, priority, reason = needs_human_review(
            call,
            error_type=ErrorType.WRONG_TRANSFER,
            outcome_category=OutcomeCategory.ERROR,
            confidence=0.80,
        )
        assert required is True
        assert priority == Priority.HIGH
        assert "H2" in reason

    def test_wrong_transfer_no_frustration_no_h2(self):
        """WRONG_TRANSFER sin frustración → no H2 (puede activar H9)."""
        call = make_call(customerfrustration=YesNo.NO, reasonForTransfering="")
        required, priority, reason = needs_human_review(
            call,
            error_type=ErrorType.WRONG_TRANSFER,
            outcome_category=OutcomeCategory.ERROR,
            confidence=0.80,
        )
        # H9 debería activar (LOW) porque no hay frustración y no hay razón de transfer
        assert required is True
        assert priority != Priority.HIGH


# ─────────────────────────────────────────────────────────────────────────
# H3 — Ambiguous outcome → MEDIUM
# ─────────────────────────────────────────────────────────────────────────

class TestH3AmbiguousOutcome:
    def test_ambiguous_outcome_medium(self):
        """H3: outcome Ambiguous → MEDIUM."""
        call = make_call()
        required, priority, reason = needs_human_review(
            call,
            error_type=ErrorType.AMBIGUOUS,
            outcome_category=OutcomeCategory.AMBIGUOUS,
            confidence=0.30,
        )
        assert required is True
        assert priority == Priority.MEDIUM
        assert "H3" in reason


# ─────────────────────────────────────────────────────────────────────────
# H4 — LOOP + frustración → HIGH
# ─────────────────────────────────────────────────────────────────────────

class TestH4Loop:
    def test_loop_with_frustration(self):
        """H4: LOOP + frustración → HIGH."""
        call = make_call(customerfrustration=YesNo.YES)
        required, priority, reason = needs_human_review(
            call,
            error_type=ErrorType.LOOP,
            outcome_category=OutcomeCategory.ERROR,
            confidence=0.85,
        )
        assert required is True
        assert priority == Priority.HIGH
        assert "H4" in reason


# ─────────────────────────────────────────────────────────────────────────
# H5 — INCOMPLETE + Reservation → HIGH
# ─────────────────────────────────────────────────────────────────────────

class TestH5Incomplete:
    def test_incomplete_reservation(self):
        """H5: INCOMPLETE + 'Reservation' en reasonForCalling → HIGH."""
        call = make_call(
            reasonForCalling=ReasonForCalling.RESERVATION.value,  # contiene "Reservation"
        )
        required, priority, reason = needs_human_review(
            call,
            error_type=ErrorType.INCOMPLETE,
            outcome_category=OutcomeCategory.ERROR,
            confidence=0.85,
        )
        assert required is True
        assert priority == Priority.HIGH
        assert "H5" in reason


# ─────────────────────────────────────────────────────────────────────────
# H6 — Frustración + Error → MEDIUM
# ─────────────────────────────────────────────────────────────────────────

class TestH6FrustrationError:
    def test_frustration_with_error_outcome(self):
        """H6: cualquier error con frustración → MEDIUM."""
        call = make_call(customerfrustration=YesNo.YES)
        required, priority, reason = needs_human_review(
            call,
            error_type=ErrorType.WRONG_SMS,
            outcome_category=OutcomeCategory.ERROR,
            confidence=0.80,
        )
        assert required is True
        assert priority == Priority.MEDIUM
        assert "H6" in reason


# ─────────────────────────────────────────────────────────────────────────
# H7 — WRONG_SMS fuera de horario → MEDIUM
# ─────────────────────────────────────────────────────────────────────────

class TestH7WrongSMSAfterHours:
    def test_wrong_sms_after_hours(self):
        """H7: WRONG_SMS fuera de horario → MEDIUM."""
        call = make_call(callWithinOfficeHours=False)
        required, priority, reason = needs_human_review(
            call,
            error_type=ErrorType.WRONG_SMS,
            outcome_category=OutcomeCategory.ERROR,
            confidence=0.85,
        )
        assert required is True
        assert priority == Priority.MEDIUM
        assert "H7" in reason


# ─────────────────────────────────────────────────────────────────────────
# H8 — Baja confianza (no NO_ERROR) → MEDIUM
# ─────────────────────────────────────────────────────────────────────────

class TestH8LowConfidence:
    def test_low_confidence_non_no_error(self):
        """H8: confidence < 0.55 y no NO_ERROR → MEDIUM."""
        call = make_call()
        required, priority, reason = needs_human_review(
            call,
            error_type=ErrorType.WRONG_SMS,
            outcome_category=OutcomeCategory.ERROR,
            confidence=0.40,
        )
        assert required is True
        assert priority == Priority.MEDIUM
        assert "H8" in reason

    def test_low_confidence_no_error_not_triggered(self):
        """H8: confidence < 0.55 pero NO_ERROR → no aplica H8."""
        call = make_call()
        required, _, reason = needs_human_review(
            call,
            error_type=ErrorType.NO_ERROR,
            outcome_category=OutcomeCategory.RESOLVED,
            confidence=0.40,
        )
        # H8 no aplica porque error_type es NO_ERROR
        if required:
            assert "H8" not in reason

    def test_confidence_at_threshold(self):
        """H8: confidence == 0.55 → NO dispara (< 0.55)."""
        call = make_call()
        required, _, _ = needs_human_review(
            call,
            error_type=ErrorType.WRONG_INFO,
            outcome_category=OutcomeCategory.ERROR,
            confidence=0.55,
        )
        # Debe estar requerido pero por H1 (WRONG_INFO), no por H8
        assert required is True


# ─────────────────────────────────────────────────────────────────────────
# No review needed
# ─────────────────────────────────────────────────────────────────────────

class TestNoReview:
    def test_clean_no_error(self):
        """Llamada limpia NO_ERROR / Resolved → no review."""
        call = make_call(customerfrustration=YesNo.NO, callWithinOfficeHours=True)
        required, priority, reason = needs_human_review(
            call,
            error_type=ErrorType.NO_ERROR,
            outcome_category=OutcomeCategory.RESOLVED,
            confidence=0.90,
        )
        assert required is False
        assert priority is None
        assert reason == ""
