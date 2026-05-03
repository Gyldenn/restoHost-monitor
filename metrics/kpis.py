"""Pure KPI functions. Each takes records: list[tuple[CallRecord, Classification]]
and returns float | None (or dict). Window is applied inside each function."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone

from shared.enums import ErrorType, OutcomeCategory, YesNo
from shared.models import CallRecord, Classification

# ──────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────

WINDOW_SHORT = 50
WINDOW_LONG = 100
WINDOW_PER_RESTAURANT = 20
MIN_SAMPLES = 5


def _excl_spam(
    records: list[tuple[CallRecord, Classification]],
) -> list[tuple[CallRecord, Classification]]:
    return [(r, c) for r, c in records if c.outcome_category != OutcomeCategory.SPAM]


# ──────────────────────────────────────────────────────────────────
# KPIs — short window (50)
# ──────────────────────────────────────────────────────────────────


def resolution_rate(records: list[tuple[CallRecord, Classification]]) -> float | None:
    """% Resolved / total_excl_spam, últimas 50. None si < 5 muestras."""
    window = records[-WINDOW_SHORT:]
    excl = _excl_spam(window)
    if len(excl) < MIN_SAMPLES:
        return None
    resolved = sum(1 for _, c in excl if c.outcome_category == OutcomeCategory.RESOLVED)
    return resolved / len(excl)


def error_rate(records: list[tuple[CallRecord, Classification]]) -> float | None:
    """% Error / total_excl_spam, últimas 50. None si < 5 muestras."""
    window = records[-WINDOW_SHORT:]
    excl = _excl_spam(window)
    if len(excl) < MIN_SAMPLES:
        return None
    errors = sum(1 for _, c in excl if c.outcome_category == OutcomeCategory.ERROR)
    return errors / len(excl)


def human_review_rate(records: list[tuple[CallRecord, Classification]]) -> float | None:
    """% human_review_required=True / total (incluye spam), últimas 50."""
    window = records[-WINDOW_SHORT:]
    if len(window) < MIN_SAMPLES:
        return None
    reviews = sum(1 for _, c in window if c.human_review_required)
    return reviews / len(window)


def high_priority_review_rate(records: list[tuple[CallRecord, Classification]]) -> float | None:
    """% priority=HIGH / total, últimas 50."""
    window = records[-WINDOW_SHORT:]
    if len(window) < MIN_SAMPLES:
        return None
    from shared.enums import Priority
    high = sum(1 for _, c in window if c.human_review_priority == Priority.HIGH)
    return high / len(window)


def wrong_transfer_rate(records: list[tuple[CallRecord, Classification]]) -> float | None:
    """% WRONG_TRANSFER / total_excl_spam, últimas 50."""
    window = records[-WINDOW_SHORT:]
    excl = _excl_spam(window)
    if len(excl) < MIN_SAMPLES:
        return None
    wt = sum(1 for _, c in excl if c.error_type == ErrorType.WRONG_TRANSFER)
    return wt / len(excl)


# ──────────────────────────────────────────────────────────────────
# KPIs — long window (100)
# ──────────────────────────────────────────────────────────────────


def wrong_info_rate(records: list[tuple[CallRecord, Classification]]) -> float | None:
    """% WRONG_INFO / total_excl_spam, últimas 100."""
    window = records[-WINDOW_LONG:]
    excl = _excl_spam(window)
    if len(excl) < MIN_SAMPLES:
        return None
    wi = sum(1 for _, c in excl if c.error_type == ErrorType.WRONG_INFO)
    return wi / len(excl)


def loop_rate(records: list[tuple[CallRecord, Classification]]) -> float | None:
    """% LOOP / total_excl_spam, últimas 100."""
    window = records[-WINDOW_LONG:]
    excl = _excl_spam(window)
    if len(excl) < MIN_SAMPLES:
        return None
    loops = sum(1 for _, c in excl if c.error_type == ErrorType.LOOP)
    return loops / len(excl)


def silent_error_ratio(records: list[tuple[CallRecord, Classification]]) -> float | None:
    """% llamadas con error_type in {WRONG_INFO, INCOMPLETE} y customerfrustration=='no'
    sobre total de errores. Ventana 100. None si < 5 errores.

    Por qué existe: las métricas estándar de frustración no detectan errores donde el
    cliente quedó satisfecho con información incorrecta. Estos errores silenciosos son
    los más peligrosos porque nunca aparecen en sistemas basados en quejas.
    """
    window = records[-WINDOW_LONG:]
    silent_error_types = {ErrorType.WRONG_INFO, ErrorType.INCOMPLETE}

    all_errors = [(r, c) for r, c in window if c.outcome_category == OutcomeCategory.ERROR]
    if len(all_errors) < MIN_SAMPLES:
        return None

    silent = sum(
        1
        for r, c in all_errors
        if c.error_type in silent_error_types and r.customerfrustration == YesNo.NO
    )
    return silent / len(all_errors)


# ──────────────────────────────────────────────────────────────────
# KPIs — per-restaurant
# ──────────────────────────────────────────────────────────────────


def error_rate_by_restaurant(records: list[tuple[CallRecord, Classification]]) -> dict[str, float]:
    """Error rate por restaurante, últimas 20 llamadas por restaurante."""
    # Group by restaurant
    by_rest: dict[str, list[tuple[CallRecord, Classification]]] = defaultdict(list)
    for r, c in records:
        by_rest[r.restaurantName].append((r, c))

    result: dict[str, float] = {}
    for rest_name, rest_records in by_rest.items():
        window = rest_records[-WINDOW_PER_RESTAURANT:]
        excl = _excl_spam(window)
        if not excl:
            result[rest_name] = 0.0
            continue
        errors = sum(1 for _, c in excl if c.outcome_category == OutcomeCategory.ERROR)
        result[rest_name] = errors / len(excl)

    return result


# ──────────────────────────────────────────────────────────────────
# KPIs — trend
# ──────────────────────────────────────────────────────────────────


def score_trend_7d(records: list[tuple[CallRecord, Classification]]) -> float | None:
    """Pendiente lineal del confidence promedio diario, últimos 7 días.
    None si < 3 puntos de datos."""
    # Aggregate confidence by day
    from collections import defaultdict

    daily: dict[str, list[float]] = defaultdict(list)
    for _, c in records:
        day = c.classified_at.strftime("%Y-%m-%d")
        daily[day].append(c.confidence)

    # Sort days and take last 7
    sorted_days = sorted(daily.keys())[-7:]
    if len(sorted_days) < 3:
        return None

    # Compute daily averages
    avgs = [sum(daily[d]) / len(daily[d]) for d in sorted_days]
    n = len(avgs)
    xs = list(range(n))

    # Simple linear regression: slope = (n*sum(x*y) - sum(x)*sum(y)) / (n*sum(x^2) - sum(x)^2)
    sum_x = sum(xs)
    sum_y = sum(avgs)
    sum_xy = sum(x * y for x, y in zip(xs, avgs))
    sum_xx = sum(x * x for x in xs)

    denom = n * sum_xx - sum_x ** 2
    if denom == 0:
        return None

    slope = (n * sum_xy - sum_x * sum_y) / denom
    return slope


# ──────────────────────────────────────────────────────────────────
# KPIs — distributions
# ──────────────────────────────────────────────────────────────────


def outcome_distribution(records: list[tuple[CallRecord, Classification]]) -> dict[str, int]:
    """Conteo por OutcomeCategory.value, últimas 50."""
    window = records[-WINDOW_SHORT:]
    dist: dict[str, int] = {cat.value: 0 for cat in OutcomeCategory}
    for _, c in window:
        dist[c.outcome_category.value] = dist.get(c.outcome_category.value, 0) + 1
    return dist


def error_type_distribution(records: list[tuple[CallRecord, Classification]]) -> dict[str, int]:
    """Conteo por ErrorType.value, últimas 50."""
    window = records[-WINDOW_SHORT:]
    dist: dict[str, int] = {et.value: 0 for et in ErrorType}
    for _, c in window:
        dist[c.error_type.value] = dist.get(c.error_type.value, 0) + 1
    return dist
