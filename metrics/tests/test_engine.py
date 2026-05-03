"""Tests for metrics/engine.py — stateful MetricsEngine."""

from __future__ import annotations

from datetime import datetime

import pytest

from shared.enums import AlertSeverity, ErrorType, OutcomeCategory, Priority, YesNo
from shared.models import Alert, CallRecord, Classification, MetricsSnapshot
from metrics.engine import MetricsEngine


# ──────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────


def _base_call(conv_id: str = "test_001", restaurant: str = "BG Las Olas") -> CallRecord:
    return CallRecord(
        conversationId=conv_id,
        restaurantName=restaurant,
        callStartTime="2026-04-01T10:00:00.000-04:00",
        callDuration="01:00",
        callEndReason="UserHangup",
        callWithinOfficeHours=True,
        reasonForCalling="General information and amenities",
        customerfrustration=YesNo.NO,
        friendlysummary="Test call.",
        conversation="Assistant: Hello.\nCustomer: Bye.",
    )


def _cls(
    conv_id: str = "test_001",
    outcome: OutcomeCategory = OutcomeCategory.RESOLVED,
    error: ErrorType = ErrorType.NO_ERROR,
    human_review: bool = False,
    priority: Priority | None = None,
    confidence: float = 0.9,
) -> Classification:
    return Classification(
        conversationId=conv_id,
        outcome_category=outcome,
        error_type=error,
        error_description="desc",
        expected_behavior="expected",
        human_review_required=human_review,
        human_review_priority=priority,
        confidence=confidence,
        classified_at=datetime(2026, 4, 21, 10, 0, 0),
    )


# ──────────────────────────────────────────────────────────────────
# Ingest and snapshot
# ──────────────────────────────────────────────────────────────────


def test_ingest_and_snapshot_valid(sample_records):
    """Ingesting 7 sample records produces a valid MetricsSnapshot."""
    engine = MetricsEngine()
    for call, classification in sample_records:
        engine.ingest(call, classification)

    snap = engine.snapshot()

    assert isinstance(snap, MetricsSnapshot)
    assert snap.total_calls == 7
    assert snap.timestamp is not None
    # Fields can be None if < 5 samples for some, but most with 7 records should work
    # error_rate: 4 errors / 7 non-spam = 0.57
    assert snap.error_rate is not None
    assert abs(snap.error_rate - 4 / 7) < 0.01
    # custom_metric_name set
    assert snap.custom_metric_name == "silent_error_ratio"
    # outcome_distribution has all keys
    from shared.enums import OutcomeCategory
    for cat in OutcomeCategory:
        assert cat.value in snap.outcome_distribution


def test_snapshot_empty_engine():
    """Empty engine snapshot has None for rate metrics and 0 total_calls."""
    engine = MetricsEngine()
    snap = engine.snapshot()

    assert snap.total_calls == 0
    assert snap.resolution_rate is None
    assert snap.error_rate is None
    assert snap.human_review_rate is None


def test_ingest_accumulates():
    """Records accumulate with each ingest call."""
    engine = MetricsEngine()
    assert engine.snapshot().total_calls == 0

    engine.ingest(_base_call("c1"), _cls("c1", OutcomeCategory.RESOLVED))
    assert engine.snapshot().total_calls == 1

    engine.ingest(_base_call("c2"), _cls("c2", OutcomeCategory.ERROR))
    assert engine.snapshot().total_calls == 2


def test_snapshot_always_valid_pydantic():
    """MetricsSnapshot from any ingest state passes Pydantic validation."""
    engine = MetricsEngine()

    # Add some mixed records
    for i in range(3):
        engine.ingest(_base_call(f"res_{i}"), _cls(f"res_{i}", OutcomeCategory.RESOLVED))
    for i in range(3):
        engine.ingest(_base_call(f"err_{i}"), _cls(f"err_{i}", OutcomeCategory.ERROR))
    for i in range(2):
        engine.ingest(_base_call(f"spam_{i}"), _cls(f"spam_{i}", OutcomeCategory.SPAM))

    snap = engine.snapshot()
    # Re-validate through Pydantic — should not raise
    validated = MetricsSnapshot.model_validate(snap.model_dump())
    assert validated.total_calls == 8


# ──────────────────────────────────────────────────────────────────
# check_alerts
# ──────────────────────────────────────────────────────────────────


def test_check_alerts_returns_valid_alerts():
    """With high error rate data, check_alerts returns valid Alert objects."""
    engine = MetricsEngine()

    # Ingest 30 errors + 5 resolved → error rate > 0.25 → CRITICAL
    for i in range(30):
        engine.ingest(
            _base_call(f"err_{i}"),
            _cls(f"err_{i}", OutcomeCategory.ERROR),
        )
    for i in range(5):
        engine.ingest(
            _base_call(f"res_{i}"),
            _cls(f"res_{i}", OutcomeCategory.RESOLVED),
        )

    snap = engine.snapshot()
    alerts = engine.check_alerts(snap)

    assert isinstance(alerts, list)
    assert len(alerts) > 0

    for alert in alerts:
        assert isinstance(alert, Alert)
        assert alert.alert_id
        assert alert.severity in (AlertSeverity.WARNING, AlertSeverity.CRITICAL)
        assert alert.metric
        assert alert.current_value >= 0
        assert alert.threshold >= 0
        assert alert.timestamp is not None
        assert len(alert.top_contributing_calls) <= 5
        assert 0 < len(alert.recommended_action) <= 400


def test_check_alerts_fires_critical_error_rate():
    """30 errors + 5 resolved → error_rate critical fires."""
    engine = MetricsEngine()

    for i in range(30):
        engine.ingest(_base_call(f"e_{i}"), _cls(f"e_{i}", OutcomeCategory.ERROR))
    for i in range(5):
        engine.ingest(_base_call(f"r_{i}"), _cls(f"r_{i}", OutcomeCategory.RESOLVED))

    snap = engine.snapshot()
    alerts = engine.check_alerts(snap)

    critical = [a for a in alerts if a.metric == "error_rate" and a.severity == AlertSeverity.CRITICAL]
    assert len(critical) >= 1


def test_check_alerts_dedup_via_engine():
    """Engine maintains fired_alerts cache — same alert won't fire twice in a row."""
    engine = MetricsEngine()

    for i in range(30):
        engine.ingest(_base_call(f"e_{i}"), _cls(f"e_{i}", OutcomeCategory.ERROR))
    for i in range(5):
        engine.ingest(_base_call(f"r_{i}"), _cls(f"r_{i}", OutcomeCategory.RESOLVED))

    snap = engine.snapshot()
    alerts1 = engine.check_alerts(snap)
    alerts2 = engine.check_alerts(snap)

    # All alerts in alerts1 should NOT appear in alerts2 (same IDs)
    ids1 = {a.alert_id for a in alerts1}
    ids2 = {a.alert_id for a in alerts2}
    assert ids1.isdisjoint(ids2), f"Duplicate alert IDs: {ids1 & ids2}"


def test_engine_error_rate_by_restaurant():
    """error_rate_by_restaurant groups by restaurantName."""
    engine = MetricsEngine()

    # 5 errors at BG Brickell, 5 resolved at BG Las Olas
    for i in range(5):
        engine.ingest(_base_call(f"brk_{i}", "BG Brickell"), _cls(f"brk_{i}", OutcomeCategory.ERROR))
    for i in range(5):
        engine.ingest(_base_call(f"las_{i}", "BG Las Olas"), _cls(f"las_{i}", OutcomeCategory.RESOLVED))

    snap = engine.snapshot()
    assert "BG Brickell" in snap.error_rate_by_restaurant
    assert "BG Las Olas" in snap.error_rate_by_restaurant
    assert snap.error_rate_by_restaurant["BG Brickell"] == 1.0
    assert snap.error_rate_by_restaurant["BG Las Olas"] == 0.0
