"""Tests for metrics/kpis.py — pure KPI functions."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from shared.enums import ErrorType, OutcomeCategory, Priority, YesNo
from shared.models import CallRecord, Classification
from metrics import kpis


# ──────────────────────────────────────────────────────────────────
# Helpers to build minimal records
# ──────────────────────────────────────────────────────────────────

SEED_PATH = Path(__file__).parent.parent.parent / "data" / "calls_seed.json"


def _base_call(conv_id: str = "test_001", restaurant: str = "BG Las Olas", frustration: YesNo = YesNo.NO) -> CallRecord:
    """Minimal valid CallRecord."""
    return CallRecord(
        conversationId=conv_id,
        restaurantName=restaurant,
        callStartTime="2026-04-01T10:00:00.000-04:00",
        callDuration="01:00",
        callEndReason="UserHangup",
        callWithinOfficeHours=True,
        reasonForCalling="General information and amenities",
        customerfrustration=frustration,
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
    classified_at: datetime | None = None,
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
        classified_at=classified_at or datetime(2026, 4, 21, 10, 0, 0),
    )


def _make_records(
    n_spam: int = 0,
    n_resolved: int = 0,
    n_error: int = 0,
    n_transferred: int = 0,
    error_type: ErrorType = ErrorType.NO_ERROR,
    restaurant: str = "BG Las Olas",
) -> list[tuple[CallRecord, Classification]]:
    records = []
    idx = 0

    for _ in range(n_spam):
        cid = f"spam_{idx}"
        records.append((_base_call(cid, restaurant), _cls(cid, OutcomeCategory.SPAM)))
        idx += 1

    for _ in range(n_resolved):
        cid = f"res_{idx}"
        records.append((_base_call(cid, restaurant), _cls(cid, OutcomeCategory.RESOLVED)))
        idx += 1

    for _ in range(n_error):
        cid = f"err_{idx}"
        records.append((_base_call(cid, restaurant), _cls(cid, OutcomeCategory.ERROR, error_type)))
        idx += 1

    for _ in range(n_transferred):
        cid = f"trans_{idx}"
        records.append((_base_call(cid, restaurant), _cls(cid, OutcomeCategory.TRANSFERRED)))
        idx += 1

    return records


# ──────────────────────────────────────────────────────────────────
# resolution_rate
# ──────────────────────────────────────────────────────────────────


def test_resolution_rate_excludes_spam():
    """3 spam + 5 resolved + 2 error → 5/7."""
    records = _make_records(n_spam=3, n_resolved=5, n_error=2)
    result = kpis.resolution_rate(records)
    assert result is not None
    assert abs(result - 5 / 7) < 1e-9


def test_resolution_rate_none_if_few_samples():
    """< 5 non-spam records → None."""
    records = _make_records(n_resolved=3, n_error=1)  # 4 non-spam
    result = kpis.resolution_rate(records)
    assert result is None


def test_resolution_rate_all_spam_returns_none():
    """Only spam → None."""
    records = _make_records(n_spam=10)
    assert kpis.resolution_rate(records) is None


def test_resolution_rate_empty_returns_none():
    assert kpis.resolution_rate([]) is None


# ──────────────────────────────────────────────────────────────────
# error_rate
# ──────────────────────────────────────────────────────────────────


def test_error_rate_correct():
    """5 resolved + 5 error + 3 spam → 5/10 = 0.5."""
    records = _make_records(n_spam=3, n_resolved=5, n_error=5)
    result = kpis.error_rate(records)
    assert result is not None
    assert abs(result - 0.5) < 1e-9


def test_error_rate_none_if_few_samples():
    records = _make_records(n_resolved=2, n_error=1)
    assert kpis.error_rate(records) is None


# ──────────────────────────────────────────────────────────────────
# silent_error_ratio
# ──────────────────────────────────────────────────────────────────


def test_silent_error_ratio():
    """WRONG_INFO with frustration='no' counts as silent; with 'yes' does not."""
    records = []
    # Silent: WRONG_INFO + no frustration → should count
    for i in range(3):
        cid = f"silent_{i}"
        records.append((
            _base_call(cid, frustration=YesNo.NO),
            _cls(cid, OutcomeCategory.ERROR, ErrorType.WRONG_INFO),
        ))
    # Not silent: WRONG_INFO + yes frustration → should NOT count
    for i in range(2):
        cid = f"noisy_{i}"
        records.append((
            _base_call(cid, frustration=YesNo.YES),
            _cls(cid, OutcomeCategory.ERROR, ErrorType.WRONG_INFO),
        ))
    # 5 total errors, 3 silent
    result = kpis.silent_error_ratio(records)
    assert result is not None
    assert abs(result - 3 / 5) < 1e-9


def test_silent_error_ratio_none_if_few_errors():
    """< 5 errors → None."""
    records = _make_records(n_error=3)
    assert kpis.silent_error_ratio(records) is None


def test_silent_error_ratio_incomplete_counts():
    """INCOMPLETE + no frustration also counts as silent."""
    records = []
    for i in range(5):
        cid = f"inc_{i}"
        records.append((
            _base_call(cid, frustration=YesNo.NO),
            _cls(cid, OutcomeCategory.ERROR, ErrorType.INCOMPLETE),
        ))
    result = kpis.silent_error_ratio(records)
    assert result == 1.0


# ──────────────────────────────────────────────────────────────────
# score_trend_7d
# ──────────────────────────────────────────────────────────────────


def test_score_trend_none_if_few_days():
    """< 3 different days → None."""
    base_dt = datetime(2026, 4, 21, 10, 0, 0)
    records = []
    for i in range(5):
        cid = f"t_{i}"
        records.append((
            _base_call(cid),
            _cls(cid, confidence=0.8, classified_at=base_dt),  # all same day
        ))
    assert kpis.score_trend_7d(records) is None


def test_score_trend_positive_slope():
    """Confidence increasing over days → positive slope."""
    records = []
    for day in range(5):
        dt = datetime(2026, 4, 20 + day, 10, 0, 0)
        conf = 0.7 + day * 0.05  # increasing
        cid = f"day_{day}"
        records.append((_base_call(cid), _cls(cid, confidence=conf, classified_at=dt)))

    slope = kpis.score_trend_7d(records)
    assert slope is not None
    assert slope > 0


def test_score_trend_negative_slope():
    """Confidence decreasing over days → negative slope."""
    records = []
    for day in range(5):
        dt = datetime(2026, 4, 20 + day, 10, 0, 0)
        conf = 0.9 - day * 0.05  # decreasing
        cid = f"day_{day}"
        records.append((_base_call(cid), _cls(cid, confidence=conf, classified_at=dt)))

    slope = kpis.score_trend_7d(records)
    assert slope is not None
    assert slope < 0


# ──────────────────────────────────────────────────────────────────
# Window applied
# ──────────────────────────────────────────────────────────────────


def test_window_applied():
    """With 60 records where first 10 are errors and last 50 are resolved,
    resolution_rate should use only last 50 (all resolved) → ~1.0."""
    records = []
    # First 10: errors
    for i in range(10):
        cid = f"early_err_{i}"
        records.append((_base_call(cid), _cls(cid, OutcomeCategory.ERROR)))
    # Last 50: resolved
    for i in range(50):
        cid = f"late_res_{i}"
        records.append((_base_call(cid), _cls(cid, OutcomeCategory.RESOLVED)))

    result = kpis.resolution_rate(records)
    assert result is not None
    assert result == 1.0  # all 50 in window are resolved


# ──────────────────────────────────────────────────────────────────
# outcome_distribution keys
# ──────────────────────────────────────────────────────────────────


def test_outcome_distribution_keys():
    """All OutcomeCategory values should be present as keys."""
    records = _make_records(n_resolved=3, n_error=2, n_spam=1)
    dist = kpis.outcome_distribution(records)
    from shared.enums import OutcomeCategory
    for cat in OutcomeCategory:
        assert cat.value in dist, f"Missing key: {cat.value}"


# ──────────────────────────────────────────────────────────────────
# Using fixture records
# ──────────────────────────────────────────────────────────────────


def test_sample_records_fixture(sample_records):
    """Verify fixture loads correctly and basic KPIs work."""
    assert len(sample_records) == 7
    # Should be: 2 resolved, 1 transferred, 4 errors — no spam
    rate = kpis.error_rate(sample_records)
    assert rate is not None
    # 4 errors out of 7 non-spam ≈ 0.571
    assert abs(rate - 4 / 7) < 0.01


def test_wrong_transfer_rate_from_fixture(sample_records):
    """mock_006 is WRONG_TRANSFER → wrong_transfer_rate = 1/7."""
    rate = kpis.wrong_transfer_rate(sample_records)
    assert rate is not None
    assert abs(rate - 1 / 7) < 0.01
