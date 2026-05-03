"""
Tests de las reglas determinísticas R01-R10.
"""

import pytest

from shared.enums import (
    CallEndReason,
    ErrorType,
    OutcomeCategory,
    ReasonForCalling,
    YesNo,
)
from shared.models import CallRecord
from classifier.rules import (
    apply_rules,
    rule_spam,
    rule_potential_bypass,
    rule_missing_transfer_complaint,
    rule_sms_mismatch,
    rule_csf_after_hours,
    rule_clean_resolution,
    rule_legitimate_transfer,
    rule_loop_signal_from_metadata,
    rule_incomplete_task,
    rule_ambiguous_reason,
)


# ─────────────────────────────────────────────────────────────────────────
# Helper para construir CallRecords mínimos en tests
# ─────────────────────────────────────────────────────────────────────────

def make_call(**kwargs) -> CallRecord:
    defaults = dict(
        conversationId="test_001",
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
# R01 — Spam
# ─────────────────────────────────────────────────────────────────────────

class TestRuleSpam:
    def test_spam_short_agent_hangup(self):
        """R01: AgentHangup + duration < 60 → spam con confidence=0.95."""
        call = make_call(
            callEndReason=CallEndReason.AGENT_HANGUP,
            callDuration="00:30",  # 30 seconds
        )
        hit = rule_spam(call)
        assert hit is not None
        assert hit.error_type == ErrorType.NO_ERROR
        assert hit.outcome_category == OutcomeCategory.SPAM
        assert hit.confidence == 0.95

    def test_no_spam_user_hangup(self):
        """UserHangup → no spam."""
        call = make_call(callEndReason=CallEndReason.USER_HANGUP, callDuration="00:30")
        assert rule_spam(call) is None

    def test_no_spam_agent_hangup_long(self):
        """AgentHangup pero duración >= 60 → no spam."""
        call = make_call(
            callEndReason=CallEndReason.AGENT_HANGUP,
            callDuration="01:30",  # 90 seconds
        )
        assert rule_spam(call) is None

    def test_spam_exactly_59_seconds(self):
        """59 segundos con AgentHangup → spam (< 60)."""
        call = make_call(
            callEndReason=CallEndReason.AGENT_HANGUP,
            callDuration="00:59",
        )
        assert rule_spam(call) is not None


# ─────────────────────────────────────────────────────────────────────────
# R04 — SMS mismatch
# ─────────────────────────────────────────────────────────────────────────

class TestRuleSMSMismatch:
    def test_wrong_sms_sent(self):
        """Reserva con SMS 'menu' enviado (no es reservation) → WRONG_SMS."""
        call = make_call(
            reasonForCalling=ReasonForCalling.RESERVATION.value,
            reasonForSendingText="menu",
            numberOfTextsSent=1,
        )
        hit = rule_sms_mismatch(call)
        assert hit is not None
        assert hit.error_type == ErrorType.WRONG_SMS
        assert hit.confidence >= 0.85

    def test_correct_sms_reservation(self):
        """Reserva con SMS 'reservation' → no mismatch."""
        call = make_call(
            reasonForCalling=ReasonForCalling.RESERVATION.value,
            reasonForSendingText="reservation",
            numberOfTextsSent=1,
        )
        assert rule_sms_mismatch(call) is None

    def test_csf_is_valid_fallback(self):
        """CSF enviado → válido como fallback (no es WRONG_SMS)."""
        call = make_call(
            reasonForCalling=ReasonForCalling.RESERVATION.value,
            reasonForSendingText="csf",
            numberOfTextsSent=1,
        )
        assert rule_sms_mismatch(call) is None

    def test_no_sms_expected(self):
        """Hours/Wait → no SMS en el mapa → no mismatch."""
        call = make_call(
            reasonForCalling=ReasonForCalling.HOURS_WAIT.value,
            reasonForSendingText="",
            numberOfTextsSent=0,
        )
        assert rule_sms_mismatch(call) is None


# ─────────────────────────────────────────────────────────────────────────
# R05 — CSF after hours
# ─────────────────────────────────────────────────────────────────────────

class TestRuleCSFAfterHours:
    def test_csf_after_hours_correct(self):
        """Fuera de horario + CSF enviado → NO_ERROR / Resolved."""
        call = make_call(
            callWithinOfficeHours=False,
            reasonForSendingText="csf",
            numberOfTextsSent=1,
        )
        hit = rule_csf_after_hours(call)
        assert hit is not None
        assert hit.error_type == ErrorType.NO_ERROR
        assert hit.outcome_category == OutcomeCategory.RESOLVED
        assert hit.confidence == 0.85

    def test_no_csf_within_hours(self):
        """Dentro de horario → no aplica."""
        call = make_call(
            callWithinOfficeHours=True,
            reasonForSendingText="csf",
            numberOfTextsSent=1,
        )
        assert rule_csf_after_hours(call) is None

    def test_after_hours_no_csf(self):
        """Fuera de horario sin CSF → no aplica."""
        call = make_call(
            callWithinOfficeHours=False,
            reasonForSendingText="",
            numberOfTextsSent=0,
        )
        assert rule_csf_after_hours(call) is None


# ─────────────────────────────────────────────────────────────────────────
# R06 — Clean resolution
# ─────────────────────────────────────────────────────────────────────────

class TestRuleCleanResolution:
    def test_clean_resolution(self):
        """UserHangup + no frustración + no error + duración >= 20 + SMS ok → Resolved."""
        call = make_call(
            callEndReason=CallEndReason.USER_HANGUP,
            callDuration="01:00",
            customerfrustration=YesNo.NO,
            detectederror="No Error Detected",
            reasonForCalling=ReasonForCalling.RESERVATION.value,
            numberOfTextsSent=1,  # RESERVATION espera 1 SMS
        )
        hit = rule_clean_resolution(call)
        assert hit is not None
        assert hit.error_type == ErrorType.NO_ERROR
        assert hit.outcome_category == OutcomeCategory.RESOLVED
        assert hit.confidence == 0.80

    def test_no_clean_with_frustration(self):
        """Frustración → no clean resolution."""
        call = make_call(
            callEndReason=CallEndReason.USER_HANGUP,
            callDuration="01:00",
            customerfrustration=YesNo.YES,
            detectederror="No Error Detected",
        )
        assert rule_clean_resolution(call) is None

    def test_no_clean_with_detected_error(self):
        """Error detectado → no clean."""
        call = make_call(
            callEndReason=CallEndReason.USER_HANGUP,
            callDuration="01:00",
            customerfrustration=YesNo.NO,
            detectederror="Wrong Information Provided",
        )
        assert rule_clean_resolution(call) is None

    def test_no_clean_too_short(self):
        """Duración < 20 s → no aplica."""
        call = make_call(
            callEndReason=CallEndReason.USER_HANGUP,
            callDuration="00:15",
            customerfrustration=YesNo.NO,
            detectederror="No Error Detected",
        )
        assert rule_clean_resolution(call) is None

    def test_no_clean_on_transfer(self):
        """CallTransfer → no es clean UserHangup."""
        call = make_call(
            callEndReason=CallEndReason.CALL_TRANSFER,
            callDuration="01:00",
            customerfrustration=YesNo.NO,
            detectederror="No Error Detected",
        )
        assert rule_clean_resolution(call) is None


# ─────────────────────────────────────────────────────────────────────────
# R08 — Loop signal
# ─────────────────────────────────────────────────────────────────────────

class TestRuleLoopSignal:
    def test_loop_from_highlights(self):
        """'loop' en callsHighlights → hit LOOP."""
        call = make_call(
            callsHighlights="AI loop — repeated same questions",
        )
        hit = rule_loop_signal_from_metadata(call)
        assert hit is not None
        assert hit.error_type == ErrorType.LOOP

    def test_loop_from_conversation(self):
        """'going in circles' en conversación → hit LOOP."""
        call = make_call(
            conversation="Customer: This is going in circles. Goodbye.",
            callsHighlights="No Highlight",
        )
        hit = rule_loop_signal_from_metadata(call)
        assert hit is not None
        assert hit.error_type == ErrorType.LOOP

    def test_no_loop_normal_call(self):
        """Llamada normal → no loop signal."""
        call = make_call(
            callsHighlights="No Highlight",
            friendlysummary="Clean resolution.",
            conversation="Assistant: Hi.\nCustomer: Hello.",
        )
        assert rule_loop_signal_from_metadata(call) is None


# ─────────────────────────────────────────────────────────────────────────
# apply_rules — tests de integración
# ─────────────────────────────────────────────────────────────────────────

class TestApplyRules:
    def test_spam_call_produces_hit(self):
        """AgentHangup + <60s → hits include R01_spam."""
        call = make_call(
            callEndReason=CallEndReason.AGENT_HANGUP,
            callDuration="00:20",
        )
        hits, markers = apply_rules(call)
        names = [h.rule_name for h in hits]
        assert "R01_spam" in names

    def test_clean_call_has_no_error_hit(self):
        """Llamada limpia → R06_clean_resolution con NO_ERROR."""
        call = make_call(
            callEndReason=CallEndReason.USER_HANGUP,
            callDuration="01:30",
            customerfrustration=YesNo.NO,
            detectederror="No Error Detected",
            reasonForSendingText="reservation",
            numberOfTextsSent=1,
        )
        hits, markers = apply_rules(call)
        no_error_hits = [h for h in hits if h.error_type == ErrorType.NO_ERROR]
        assert len(no_error_hits) > 0

    def test_markers_returned_for_loop(self):
        """Loop signal → marker 'loop_signal' en markers."""
        call = make_call(
            callsHighlights="AI loop — repeated same questions",
        )
        hits, markers = apply_rules(call)
        assert "loop_signal" in markers
