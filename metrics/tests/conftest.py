import pytest
import json
from pathlib import Path
from shared.models import CallRecord, Classification
from shared.io import read_all

FIXTURE_DIR = Path(__file__).parent / "fixtures"
SEED_PATH = Path(__file__).parent.parent.parent / "data" / "calls_seed.json"


@pytest.fixture
def sample_records() -> list[tuple[CallRecord, Classification]]:
    calls_raw = json.load(SEED_PATH.open())
    calls = {d["conversationId"]: CallRecord.model_validate(d) for d in calls_raw}
    classifications = read_all(FIXTURE_DIR / "classified_sample.jsonl", Classification)
    result = []
    for c in classifications:
        if c.conversationId in calls:
            result.append((calls[c.conversationId], c))
    return result
