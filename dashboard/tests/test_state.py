import json
from pathlib import Path
from datetime import datetime
import pytest

def test_mark_reviewed_creates_file(tmp_path, monkeypatch):
    # monkeypatch DATA_DIR en state.py
    import dashboard.state as s
    monkeypatch.setattr(s, "DATA_DIR", tmp_path)
    s.mark_reviewed("mock_001")
    state = s.load_review_state()
    assert "mock_001" in state.reviewed

def test_mark_reviewed_idempotent(tmp_path, monkeypatch):
    import dashboard.state as s
    monkeypatch.setattr(s, "DATA_DIR", tmp_path)
    s.mark_reviewed("mock_001")
    s.mark_reviewed("mock_001")
    state = s.load_review_state()
    assert len(state.reviewed) == 1

def test_load_review_state_missing_file(tmp_path, monkeypatch):
    import dashboard.state as s
    monkeypatch.setattr(s, "DATA_DIR", tmp_path)
    state = s.load_review_state()
    assert state.reviewed == {}

def test_load_classifications_empty(tmp_path, monkeypatch):
    import dashboard.state as s
    monkeypatch.setattr(s, "DATA_DIR", tmp_path)
    result = s._load_classifications_from_disk()
    assert result == []
