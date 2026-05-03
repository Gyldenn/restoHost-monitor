import streamlit as st
import pandas as pd
from dashboard import state, components

def render() -> None:
    st.title("Call Explorer")
    classifications = state.load_classifications()
    calls_index = state.load_calls_index()

    if not classifications:
        st.info("No hay datos aún.")
        return

    rows = []
    for c in classifications:
        call = calls_index.get(c.conversationId)
        rows.append({
            "conversationId": c.conversationId,
            "restaurant": call.restaurantName if call else "Unknown",
            "error_type": c.error_type.value,
            "outcome": c.outcome_category.value,
            "review": "⚠ " + (c.human_review_priority.value if c.human_review_priority else "") if c.human_review_required else "",
            "confidence": round(c.confidence, 2),
            "classified_at": str(c.classified_at)[:19],
        })
    df = pd.DataFrame(rows)

    # Filtros
    with st.sidebar:
        rest_f = st.multiselect("Restaurante", df["restaurant"].unique())
        err_f  = st.multiselect("Error type", df["error_type"].unique())
        out_f  = st.multiselect("Outcome", df["outcome"].unique())
    if rest_f: df = df[df["restaurant"].isin(rest_f)]
    if err_f:  df = df[df["error_type"].isin(err_f)]
    if out_f:  df = df[df["outcome"].isin(out_f)]

    event = st.dataframe(df, use_container_width=True, on_select="rerun", selection_mode="single-row")
    selected = event.selection.rows if hasattr(event, "selection") else []

    if selected:
        idx = selected[0]
        conv_id = df.iloc[idx]["conversationId"]
        cls = next((c for c in classifications if c.conversationId == conv_id), None)
        call = calls_index.get(conv_id)
        if cls:
            if cls.human_review_required:
                badge = components.priority_badge(cls.human_review_priority)
                st.warning(f"{badge} Requiere revisión humana ({cls.human_review_priority.value if cls.human_review_priority else ''}) — {cls.human_review_reason}")
            col1, col2 = st.columns(2)
            with col1:
                st.subheader("Classification")
                st.json(cls.model_dump(mode="json"))
            with col2:
                if call:
                    st.subheader("Call Record")
                    st.json(call.model_dump(mode="json"))
            if call:
                st.subheader("Transcripción")
                st.text_area("", value=call.conversation, disabled=True, height=300, key="explorer_conv")
