import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st
from dashboard.views import health, errors, review_queue, explorer
from dashboard.state import start_pipeline, stop_pipeline

st.set_page_config(page_title="RestoHost Quality Monitor", layout="wide", initial_sidebar_state="expanded")

def main():
    with st.sidebar:
        st.title("RestoHost Monitor")
        live = st.toggle("Live mode", value=False)  # default False para evitar loops en dev
        st.divider()
        col1, col2 = st.columns(2)
        with col1:
            if st.button("▶ Start"):
                start_pipeline(30)
                st.success("Pipeline iniciado")
        with col2:
            if st.button("⏹ Stop"):
                stop_pipeline()
                st.info("Pipeline detenido")
        st.divider()
        page = st.radio("Vista", ["Health", "Errors", "Review Queue", "Explorer"])

    {"Health": health.render, "Errors": errors.render,
     "Review Queue": review_queue.render, "Explorer": explorer.render}[page]()

    if live:
        time.sleep(2)
        st.rerun()

if __name__ == "__main__":
    main()
