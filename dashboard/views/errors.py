import streamlit as st
import plotly.express as px
import pandas as pd
from dashboard import state

def render() -> None:
    st.title("Error Breakdown")
    classifications = state.load_classifications()
    calls_index = state.load_calls_index()

    if not classifications:
        st.info("No hay datos aún.")
        return

    df = pd.DataFrame([
        {
            "conversationId": c.conversationId,
            "error_type": c.error_type.value,
            "outcome_category": c.outcome_category.value,
            "restaurant": calls_index.get(c.conversationId, None),
            "classified_at": c.classified_at,
            "human_review_required": c.human_review_required,
        }
        for c in classifications
    ])
    df["restaurant"] = df["restaurant"].apply(
        lambda r: r.restaurantName if r else "Unknown"
    )

    # Filtros
    with st.sidebar:
        rest_filter = st.multiselect("Restaurante", options=df["restaurant"].unique().tolist())
        if rest_filter:
            df = df[df["restaurant"].isin(rest_filter)]

    # Bar: error_type distribution
    err_counts = df["error_type"].value_counts().reset_index()
    err_counts.columns = ["error_type", "count"]
    fig1 = px.bar(err_counts, x="error_type", y="count", title="Distribución de Error Types",
                  color="error_type")
    st.plotly_chart(fig1, use_container_width=True)

    # Bar: error rate por restaurante
    by_rest = df.groupby("restaurant").apply(
        lambda g: (g["outcome_category"] == "Error").mean()
    ).reset_index()
    by_rest.columns = ["restaurant", "error_rate"]
    avg = by_rest["error_rate"].mean()
    fig2 = px.bar(by_rest, x="restaurant", y="error_rate",
                  title="Error Rate por Restaurante")
    fig2.add_hline(y=avg, line_dash="dash", annotation_text=f"avg {avg:.1%}")
    st.plotly_chart(fig2, use_container_width=True)

    # Timeline scatter
    errors_df = df[df["outcome_category"] == "Error"].copy()
    if not errors_df.empty:
        errors_df = errors_df.sort_values("classified_at").tail(100)
        errors_df["idx"] = range(len(errors_df))
        fig3 = px.scatter(errors_df, x="idx", y="error_type", color="error_type",
                          title="Timeline de errores (últimas 100 llamadas)",
                          hover_data=["conversationId", "restaurant"])
        st.plotly_chart(fig3, use_container_width=True)
