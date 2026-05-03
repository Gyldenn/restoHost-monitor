"""
Fixtures compartidos para tests del clasificador.
"""

import pytest

from shared.enums import ErrorType, OutcomeCategory
from shared.llm_client import LLMClient
from classifier.llm_classifier import LLMClassification


class FakeLLMClient:
    """
    Mock de LLMClient que devuelve una clasificación predefinida
    sin hacer llamadas reales a Groq.
    """

    def __init__(
        self,
        error_type: ErrorType = ErrorType.NO_ERROR,
        outcome_category: OutcomeCategory = OutcomeCategory.RESOLVED,
        confidence: float = 0.85,
        error_description: str = "Fake LLM description.",
        expected_behavior: str = "Fake expected behavior.",
        reasoning: str = "Fake reasoning.",
    ):
        self.error_type = error_type
        self.outcome_category = outcome_category
        self.confidence = confidence
        self.error_description = error_description
        self.expected_behavior = expected_behavior
        self.reasoning = reasoning

    def complete_json(self, system, user, schema, **kwargs):
        return schema(
            error_type=self.error_type,
            outcome_category=self.outcome_category,
            error_description=self.error_description,
            expected_behavior=self.expected_behavior,
            confidence=self.confidence,
            reasoning=self.reasoning,
        )


@pytest.fixture
def fake_llm():
    """Fixture que devuelve un FakeLLMClient con defaults razonables."""
    return FakeLLMClient()


@pytest.fixture
def fake_llm_factory():
    """Fixture factory para crear FakeLLMClient con parámetros custom."""
    return FakeLLMClient
