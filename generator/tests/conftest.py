import pytest
from unittest.mock import MagicMock


@pytest.fixture
def fake_llm():
    client = MagicMock()
    client.complete_json = MagicMock()
    return client
