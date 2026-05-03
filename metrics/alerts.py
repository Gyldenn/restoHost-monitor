"""Alert rules and evaluation for the metrics engine."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from statistics import mean
from typing import Literal

from shared.enums import AlertSeverity, ErrorType, OutcomeCategory, Priority
from shared.models import Alert, CallRecord, Classification, MetricsSnapshot


@dataclass
class AlertRule:
    name: str
    metric: str
    severity: AlertSeverity
    threshold: float
    operator: str  # ">" | "<" | ">="


ALERT_RULES: list[AlertRule] = [
    AlertRule("resolution_rate_warning", "resolution_rate", AlertSeverity.WARNING, 0.60, "<"),
    AlertRule("error_rate_warning", "error_rate", AlertSeverity.WARNING, 0.15, ">"),
    AlertRule("error_rate_critical", "error_rate", AlertSeverity.CRITICAL, 0.25, ">"),
    AlertRule("human_review_rate_warning", "human_review_rate", AlertSeverity.WARNING, 0.20, ">"),
    AlertRule("high_priority_review_rate_critical", "high_priority_review_rate", AlertSeverity.CRITICAL, 0.10, ">"),
    AlertRule("wrong_transfer_rate_warning", "wrong_transfer_rate", AlertSeverity.WARNING, 0.08, ">"),
    AlertRule("wrong_info_rate_critical", "wrong_info_rate", AlertSeverity.CRITICAL, 0.03, ">"),
    AlertRule("loop_rate_critical", "loop_rate", AlertSeverity.CRITICAL, 0.05, ">"),
    AlertRule("silent_error_ratio_warning", "silent_error_ratio", AlertSeverity.WARNING, 0.30, ">"),
]


def _alert_id(metric: str, severity: AlertSeverity, restaurant: str | None = None) -> str:
    """Stable hash-based alert ID for deduplication."""
    key = f"{metric}:{severity.value}:{restaurant or ''}"
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def _operator_triggered(value: float, operator: str, threshold: float) -> bool:
    if operator == ">":
        return value > threshold
    elif operator == "<":
        return value < threshold
    elif operator == ">=":
        return value >= threshold
    elif operator == "<=":
        return value <= threshold
    return False


def _top_calls_for_metric(
    metric: str,
    records: list[tuple[CallRecord, Classification]],
    restaurant: str | None = None,
    window: int = 50,
) -> list[str]:
    """Return up to 5 most recent conversation IDs contributing to the alert metric."""
    recs = records[-window:]

    if restaurant:
        recs = [(r, c) for r, c in recs if r.restaurantName == restaurant]

    contributing = []
    if metric in ("error_rate", "error_rate_warning", "error_rate_critical"):
        contributing = [r.conversationId for r, c in recs if c.outcome_category == OutcomeCategory.ERROR]
    elif metric == "wrong_transfer_rate":
        contributing = [r.conversationId for r, c in recs if c.error_type == ErrorType.WRONG_TRANSFER]
    elif metric == "wrong_info_rate":
        contributing = [r.conversationId for r, c in recs if c.error_type == ErrorType.WRONG_INFO]
    elif metric == "loop_rate":
        contributing = [r.conversationId for r, c in recs if c.error_type == ErrorType.LOOP]
    elif metric == "human_review_rate":
        contributing = [r.conversationId for r, c in recs if c.human_review_required]
    elif metric == "high_priority_review_rate":
        contributing = [r.conversationId for r, c in recs if c.human_review_priority == Priority.HIGH]
    elif metric == "resolution_rate":
        # For low resolution rate, top calls are the errors
        contributing = [r.conversationId for r, c in recs if c.outcome_category == OutcomeCategory.ERROR]
    elif metric == "silent_error_ratio":
        from shared.enums import YesNo
        contributing = [
            r.conversationId for r, c in recs
            if c.error_type in {ErrorType.WRONG_INFO, ErrorType.INCOMPLETE}
            and r.customerfrustration == YesNo.NO
        ]
    else:
        contributing = [r.conversationId for r, c in recs]

    # Return last 5
    return contributing[-5:]


def _recommended_action(
    rule: AlertRule,
    current_value: float,
    top_calls: list[str],
    restaurant: str | None = None,
) -> str:
    calls_str = ", ".join(top_calls) if top_calls else "N/A"

    if restaurant:
        action = (
            f"Error rate de {restaurant} supera en 15pp el promedio. "
            f"Revisar llamadas recientes: {calls_str}."
        )
    elif rule.metric == "error_rate":
        action = (
            f"Error rate llegó a {current_value:.0%} en últimas 50 llamadas "
            f"(umbral {rule.threshold:.0%}). Revisar: {calls_str}."
        )
    elif rule.metric == "resolution_rate":
        action = (
            f"Resolution rate cayó a {current_value:.0%} (umbral {rule.threshold:.0%}) "
            f"en las últimas 50 llamadas. Errores recientes: {calls_str}."
        )
    elif rule.metric == "wrong_info_rate":
        action = (
            f"Wrong info rate cruzó {rule.threshold:.0%} — error silencioso crítico. "
            f"Revisar respuestas factuales del agente. Calls: {calls_str}."
        )
    elif rule.metric == "loop_rate":
        action = (
            f"Loop rate {current_value:.0%} superó umbral {rule.threshold:.0%}. "
            f"Posible problema en el prompt. Calls: {calls_str}."
        )
    elif rule.metric == "wrong_transfer_rate":
        action = (
            f"Wrong transfer rate {current_value:.0%} superó {rule.threshold:.0%}. "
            f"Revisar lógica de transferencias. Calls: {calls_str}."
        )
    elif rule.metric == "human_review_rate":
        action = (
            f"Human review rate {current_value:.0%} superó {rule.threshold:.0%}. "
            f"Alta carga de revisión manual. Calls: {calls_str}."
        )
    elif rule.metric == "high_priority_review_rate":
        action = (
            f"High priority review rate {current_value:.0%} superó {rule.threshold:.0%}. "
            f"Calls críticas: {calls_str}."
        )
    elif rule.metric == "silent_error_ratio":
        action = (
            f"Silent error ratio {current_value:.0%} superó {rule.threshold:.0%}. "
            f"Errores sin frustración del cliente: {calls_str}."
        )
    else:
        action = (
            f"Métrica {rule.metric} = {current_value:.2%} superó umbral "
            f"{rule.threshold:.2%}. Calls: {calls_str}."
        )

    # Truncate to 400 chars
    return action[:400]


def _is_deduped(
    alert_id: str,
    fired_cache: dict[str, datetime],
    dedup_seconds: int,
    now: datetime,
) -> bool:
    last_fired = fired_cache.get(alert_id)
    if last_fired is None:
        return False
    # Make both timezone-naive for comparison
    last_naive = last_fired.replace(tzinfo=None) if last_fired.tzinfo else last_fired
    now_naive = now.replace(tzinfo=None) if now.tzinfo else now
    elapsed = (now_naive - last_naive).total_seconds()
    return elapsed < dedup_seconds


def check_alerts(
    snapshot: MetricsSnapshot,
    records: list[tuple[CallRecord, Classification]],
    fired_cache: dict[str, datetime],
    dedup_seconds: int = 300,
) -> list[Alert]:
    """Evalúa todas las reglas + alertas por restaurante.
    Deduplica: no re-emite la misma alert_id si fue emitida en los últimos dedup_seconds."""
    now = datetime.utcnow()
    fired: list[Alert] = []

    snapshot_dict = snapshot.model_dump()

    # Map custom_metric_value → its named metric for rule lookup
    if snapshot.custom_metric_name and snapshot.custom_metric_value is not None:
        snapshot_dict[snapshot.custom_metric_name] = snapshot.custom_metric_value

    # ── Standard rules ──
    for rule in ALERT_RULES:
        value = snapshot_dict.get(rule.metric)
        if value is None:
            continue

        if not _operator_triggered(value, rule.operator, rule.threshold):
            continue

        aid = _alert_id(rule.metric, rule.severity, None)
        if _is_deduped(aid, fired_cache, dedup_seconds, now):
            continue

        top_calls = _top_calls_for_metric(rule.metric, records)
        action = _recommended_action(rule, value, top_calls)

        alert = Alert(
            alert_id=aid,
            severity=rule.severity,
            metric=rule.metric,
            current_value=value,
            threshold=rule.threshold,
            restaurant=None,
            timestamp=now,
            top_contributing_calls=top_calls,
            recommended_action=action,
        )
        fired.append(alert)
        fired_cache[aid] = now

    # ── Per-restaurant alerts ──
    per_rest = snapshot.error_rate_by_restaurant
    if len(per_rest) >= 2:
        avg = mean(per_rest.values())
        for rest_name, rate in per_rest.items():
            if rate - avg > 0.15:
                aid = _alert_id("error_rate", AlertSeverity.WARNING, rest_name)
                if _is_deduped(aid, fired_cache, dedup_seconds, now):
                    continue

                top_calls = _top_calls_for_metric("error_rate", records, restaurant=rest_name)
                action = _recommended_action(
                    AlertRule("restaurant_delta", "error_rate", AlertSeverity.WARNING, 0.15, ">"),
                    rate,
                    top_calls,
                    restaurant=rest_name,
                )

                alert = Alert(
                    alert_id=aid,
                    severity=AlertSeverity.WARNING,
                    metric="error_rate",
                    current_value=rate,
                    threshold=avg + 0.15,
                    restaurant=rest_name,
                    timestamp=now,
                    top_contributing_calls=top_calls,
                    recommended_action=action,
                )
                fired.append(alert)
                fired_cache[aid] = now

    return fired
