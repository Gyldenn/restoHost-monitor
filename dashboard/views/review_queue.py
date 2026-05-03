import streamlit as st
import pandas as pd
from dashboard import state, components
from shared.enums import Priority

def render() -> None:
    st.title("Human Review Queue")
    classifications = state.load_classifications()
    calls_index = state.load_calls_index()
    review_state = state.load_review_state()

    pending_only = st.sidebar.toggle("Solo pendientes", value=True)
    err_filter = st.sidebar.multiselect("Error type", options=list({c.error_type.value for c in classifications if c.human_review_required}))
    rest_filter = st.sidebar.multiselect("Restaurante", options=list({
        calls_index[c.conversationId].restaurantName
        for c in classifications
        if c.conversationId in calls_index
    }))

    queue = [c for c in classifications if c.human_review_required]
    if pending_only:
        queue = [c for c in queue if c.conversationId not in review_state.reviewed]
    if err_filter:
        queue = [c for c in queue if c.error_type.value in err_filter]
    if rest_filter:
        queue = [c for c in queue if
                 calls_index.get(c.conversationId) and
                 calls_index[c.conversationId].restaurantName in rest_filter]

    # Contadores
    high = sum(1 for c in queue if c.human_review_priority and c.human_review_priority.value == "HIGH")
    med  = sum(1 for c in queue if c.human_review_priority and c.human_review_priority.value == "MEDIUM")
    low  = sum(1 for c in queue if c.human_review_priority and c.human_review_priority.value == "LOW")
    c1, c2, c3 = st.columns(3)
    c1.metric("🔴 HIGH", high)
    c2.metric("🟡 MEDIUM", med)
    c3.metric("🟢 LOW", low)

    if not queue:
        st.success("No hay llamadas pendientes de revisión.")
        return

    # Orden: HIGH → MEDIUM → LOW
    priority_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    queue.sort(key=lambda c: (
        priority_order.get(c.human_review_priority.value if c.human_review_priority else "", 3),
        c.classified_at
    ), reverse=False)
    queue.sort(key=lambda c: priority_order.get(
        c.human_review_priority.value if c.human_review_priority else "", 3))

    for cls in queue:
        call = calls_index.get(cls.conversationId)
        restaurant = call.restaurantName if call else "Unknown"
        badge = components.priority_badge(cls.human_review_priority)
        already = cls.conversationId in review_state.reviewed

        with st.expander(
            f"{badge} {cls.human_review_priority.value if cls.human_review_priority else 'LOW'} — "
            f"{cls.error_type.value} — {cls.conversationId} — {restaurant}"
            + (" ✓" if already else ""),
            expanded=False,
        ):
            st.write(f"**Error:** {cls.error_description}")
            st.write(f"**Expected:** {cls.expected_behavior}")
            st.write(f"**Reason for review:** {cls.human_review_reason}")
            if call:
                st.text_area("Transcripción", value=call.conversation,
                             disabled=True, height=200, key=f"conv_{cls.conversationId}")
            if not already:
                if st.button("✓ Mark as reviewed", key=f"mark_{cls.conversationId}"):
                    state.mark_reviewed(cls.conversationId)
                    st.rerun()
            else:
                st.success("Revisada")
