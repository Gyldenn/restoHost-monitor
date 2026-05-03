import streamlit as st
import plotly.express as px
import pandas as pd
from datetime import datetime, timedelta
from dashboard import state, components
from shared.enums import AlertSeverity

def render() -> None:
    st.title("Health Overview")
    snap = state.load_metrics_snapshot()
    classifications = state.load_classifications()

    if not classifications and snap is None:
        st.info("No hay datos aún. Iniciá el pipeline con ▶ Start en el sidebar.")
        return

    # KPI cards
    if snap:
        cols = st.columns(4)
        with cols[0]:
            components.kpi_card("Resolution Rate", snap.resolution_rate,
                                warning_at=0.60, critical_at=0.40, direction="lower_is_worse")
        with cols[1]:
            components.kpi_card("Error Rate", snap.error_rate,
                                warning_at=0.15, critical_at=0.25, direction="higher_is_worse")
        with cols[2]:
            components.kpi_card("Human Review Rate", snap.human_review_rate,
                                warning_at=0.20, critical_at=0.35, direction="higher_is_worse")
        with cols[3]:
            components.kpi_card("Wrong Info Rate", snap.wrong_info_rate,
                                warning_at=0.03, critical_at=0.05, direction="higher_is_worse")

    # Alertas activas (últimas 1h)
    alerts = state.load_alerts()
    cutoff = datetime.utcnow() - timedelta(hours=1)
    recent_alerts = [a for a in alerts if a.timestamp >= cutoff]
    if recent_alerts:
        st.subheader("Alertas activas")
        for alert in sorted(recent_alerts, key=lambda a: (a.severity.value, a.timestamp), reverse=True):
            components.alert_banner(alert)

    # Time series
    if classifications:
        df = pd.DataFrame([
            {
                "classified_at": c.classified_at,
                "is_error": c.outcome_category.value == "Error",
                "is_resolved": c.outcome_category.value == "Resolved",
                "is_spam": c.outcome_category.value == "Spam",
            }
            for c in sorted(classifications, key=lambda c: c.classified_at)
        ])
        df["idx"] = range(len(df))
        # rolling 50
        df["error_rate"] = df["is_error"].rolling(50, min_periods=1).mean()
        df["resolution_rate"] = df["is_resolved"].rolling(50, min_periods=1).mean()
        fig = px.line(df, x="idx", y=["error_rate", "resolution_rate"],
                      labels={"idx": "Call #", "value": "Rate"},
                      title="Error Rate vs Resolution Rate (rolling 50)")
        st.plotly_chart(fig, use_container_width=True)

    # Donut outcome
    if snap and snap.outcome_distribution:
        fig2 = px.pie(
            names=list(snap.outcome_distribution.keys()),
            values=list(snap.outcome_distribution.values()),
            title="Outcome Distribution",
            hole=0.4,
        )
        st.plotly_chart(fig2, use_container_width=True)
