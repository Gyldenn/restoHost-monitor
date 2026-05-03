import streamlit as st
from shared.enums import AlertSeverity, Priority
from shared.models import Alert

def get_kpi_status(value: float | None, warning_at: float, critical_at: float,
                   direction: str) -> str:
    """Función pura testeable. Devuelve 'ok'|'warning'|'critical'|'no_data'."""
    if value is None:
        return "no_data"
    if direction == "higher_is_worse":
        if value >= critical_at:
            return "critical"
        if value >= warning_at:
            return "warning"
        return "ok"
    else:  # lower_is_worse
        if value <= critical_at:
            return "critical"
        if value <= warning_at:
            return "warning"
        return "ok"

STATUS_COLORS = {"ok": "🟢", "warning": "🟡", "critical": "🔴", "no_data": "⚪"}

def kpi_card(label: str, value: float | None, *,
             warning_at: float, critical_at: float,
             direction: str,
             format_str: str = "{:.1%}") -> None:
    status = get_kpi_status(value, warning_at, critical_at, direction)
    icon = STATUS_COLORS[status]
    display = format_str.format(value) if value is not None else "N/A"
    st.metric(label=f"{icon} {label}", value=display)

def priority_badge(priority: Priority | None) -> str:
    return {"HIGH": "🔴", "MEDIUM": "🟡", "LOW": "🟢"}.get(
        priority.value if priority else "", "⚪"
    )

def severity_color(severity: AlertSeverity) -> str:
    return "error" if severity == AlertSeverity.CRITICAL else "warning"

def alert_banner(alert: Alert) -> None:
    fn = st.error if alert.severity == AlertSeverity.CRITICAL else st.warning
    fn(f"**{alert.severity.value}** — {alert.metric}: {alert.current_value:.1%} "
       f"(umbral {alert.threshold:.1%}) — {alert.recommended_action}")
