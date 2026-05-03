"""Stateful MetricsEngine: ingests (CallRecord, Classification) pairs,
computes snapshots on demand, checks alerts."""

from __future__ import annotations

from collections import deque
from datetime import datetime

from shared.models import Alert, CallRecord, Classification, MetricsSnapshot

from metrics import kpis
from metrics import alerts as alerts_module


class MetricsEngine:
    def __init__(self) -> None:
        self._records: deque[tuple[CallRecord, Classification]] = deque(maxlen=500)
        self._fired_alerts: dict[str, datetime] = {}

    def ingest(self, call: CallRecord, classification: Classification) -> None:
        self._records.append((call, classification))

    def snapshot(self) -> MetricsSnapshot:
        recs = list(self._records)

        return MetricsSnapshot(
            timestamp=datetime.utcnow(),
            total_calls=len(recs),
            resolution_rate=kpis.resolution_rate(recs),
            error_rate=kpis.error_rate(recs),
            human_review_rate=kpis.human_review_rate(recs),
            high_priority_review_rate=kpis.high_priority_review_rate(recs),
            wrong_transfer_rate=kpis.wrong_transfer_rate(recs),
            wrong_info_rate=kpis.wrong_info_rate(recs),
            loop_rate=kpis.loop_rate(recs),
            error_rate_by_restaurant=kpis.error_rate_by_restaurant(recs),
            score_trend_7d=kpis.score_trend_7d(recs),
            custom_metric_value=kpis.silent_error_ratio(recs),
            custom_metric_name="silent_error_ratio",
            outcome_distribution=kpis.outcome_distribution(recs),
            error_type_distribution=kpis.error_type_distribution(recs),
        )

    def check_alerts(self, snapshot: MetricsSnapshot) -> list[Alert]:
        return alerts_module.check_alerts(
            snapshot,
            list(self._records),
            self._fired_alerts,
        )
