import json
import os
import signal
import subprocess
import time
from datetime import datetime
from pathlib import Path
import streamlit as st
from shared.models import CallRecord, Classification, Alert, MetricsSnapshot, ReviewState
from shared.io import read_all

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

def _load_classifications_from_disk() -> list[Classification]:
    path = DATA_DIR / "classified_calls.jsonl"
    if not path.exists():
        return []
    return read_all(path, Classification)

def _load_calls_index_from_disk() -> dict[str, CallRecord]:
    index = {}
    seed = DATA_DIR / "calls_seed.json"
    if seed.exists():
        for d in json.load(seed.open()):
            r = CallRecord.model_validate(d)
            index[r.conversationId] = r
    gen = DATA_DIR / "generated_calls.jsonl"
    if gen.exists():
        for r in read_all(gen, CallRecord):
            index[r.conversationId] = r
    return index

def _load_alerts_from_disk() -> list[Alert]:
    path = DATA_DIR / "alerts.jsonl"
    if not path.exists():
        return []
    return read_all(path, Alert)

def _load_metrics_snapshot_from_disk() -> MetricsSnapshot | None:
    path = DATA_DIR / "current_metrics.json"
    if not path.exists():
        return None
    try:
        return MetricsSnapshot.model_validate_json(path.read_text(encoding="utf-8"))
    except Exception:
        return None

def load_review_state() -> ReviewState:
    path = DATA_DIR / "review_state.json"
    if not path.exists():
        return ReviewState()
    try:
        return ReviewState.model_validate_json(path.read_text(encoding="utf-8"))
    except Exception:
        return ReviewState()

def mark_reviewed(conversation_id: str) -> None:
    state = load_review_state()
    state.reviewed[conversation_id] = datetime.utcnow()
    path = DATA_DIR / "review_state.json"
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(state.model_dump_json(), encoding="utf-8")
    tmp.replace(path)

@st.cache_data(ttl=2)
def load_classifications() -> list[Classification]:
    return _load_classifications_from_disk()

@st.cache_data(ttl=2)
def load_calls_index() -> dict[str, CallRecord]:
    return _load_calls_index_from_disk()

@st.cache_data(ttl=2)
def load_alerts() -> list[Alert]:
    return _load_alerts_from_disk()

@st.cache_data(ttl=2)
def load_metrics_snapshot() -> MetricsSnapshot | None:
    return _load_metrics_snapshot_from_disk()

def start_pipeline(n: int = 30) -> None:
    if "pipeline_proc" in st.session_state and st.session_state.pipeline_proc:
        return  # ya corriendo
    proc = subprocess.Popen(
        ["python", "main.py", "--mode", "stream", "--n", str(n)],
        cwd=str(DATA_DIR.parent),
    )
    st.session_state.pipeline_proc = proc

def stop_pipeline() -> None:
    proc = st.session_state.get("pipeline_proc")
    if proc:
        proc.terminate()
        st.session_state.pipeline_proc = None
