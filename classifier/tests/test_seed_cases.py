"""
Tests parametrizados sobre los casos obligatorios de data/calls_seed.json.
Solo usan capas 1 y 3 (llm=None) — sin dependencias externas.
"""

import json
import pytest
from pathlib import Path

from shared.models import CallRecord
from shared.enums import ErrorType, OutcomeCategory
from classifier.classifier import classify_call

# Buscamos el archivo desde varias rutas posibles para robustez en CI
_POSSIBLE_SEED_PATHS = [
    Path("data/calls_seed.json"),
    Path(__file__).resolve().parents[2] / "data" / "calls_seed.json",
]

SEED_PATH = next((p for p in _POSSIBLE_SEED_PATHS if p.exists()), None)


@pytest.fixture(scope="module")
def seed() -> dict[str, CallRecord]:
    if SEED_PATH is None:
        pytest.skip("data/calls_seed.json not found")
    data = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    return {d["conversationId"]: CallRecord.model_validate(d) for d in data}


# ─────────────────────────────────────────────────────────────────────────
# Casos obligatorios según doc 02_MODULE_CLASSIFIER.md
#
# (conv_id, expected_error, expected_outcome, expected_review, expected_priority)
# expected_review=None → no se verifica
# expected_priority=None → no se verifica
# ─────────────────────────────────────────────────────────────────────────

SEED_TEST_CASES = [
    # mock_004: hours query limpia → NO_ERROR / Resolved, sin review
    ("mock_004", ErrorType.NO_ERROR, OutcomeCategory.RESOLVED, False, None),

    # mock_006: queja sin transfer → WRONG_TRANSFER / Error + review HIGH (H2)
    ("mock_006", ErrorType.WRONG_TRANSFER, OutcomeCategory.ERROR, True, "HIGH"),

    # mock_008: escalación legítima → NO_ERROR / Transferred, sin review
    ("mock_008", ErrorType.NO_ERROR, OutcomeCategory.TRANSFERRED, False, None),

    # mock_012: manager transfer legítimo → NO_ERROR / Transferred, sin review
    ("mock_012", ErrorType.NO_ERROR, OutcomeCategory.TRANSFERRED, False, None),

    # mock_013: loop claro con frustración → LOOP / Error + review HIGH (H4)
    ("mock_013", ErrorType.LOOP, OutcomeCategory.ERROR, True, "HIGH"),

    # mock_019: info incorrecta → WRONG_INFO / Error + review HIGH (H1)
    ("mock_019", ErrorType.WRONG_INFO, OutcomeCategory.ERROR, True, "HIGH"),
]


@pytest.mark.parametrize(
    "conv_id,expected_error,expected_outcome,expected_review,expected_priority",
    SEED_TEST_CASES,
    ids=[case[0] for case in SEED_TEST_CASES],
)
def test_seed_classification(
    seed,
    conv_id,
    expected_error,
    expected_outcome,
    expected_review,
    expected_priority,
):
    """
    Clasifica cada caso seed con llm=None (capas 1+3 solo) y verifica
    que error_type, outcome_category y (opcionalemnte) human_review coinciden.
    """
    assert conv_id in seed, f"conversationId {conv_id!r} not found in seed"

    call = seed[conv_id]
    result = classify_call(call, llm=None)

    assert result.error_type == expected_error, (
        f"{conv_id}: error_type got {result.error_type!r}, expected {expected_error!r}. "
        f"Rules triggered: {result.rules_triggered}. "
        f"Description: {result.error_description}"
    )
    assert result.outcome_category == expected_outcome, (
        f"{conv_id}: outcome_category got {result.outcome_category!r}, expected {expected_outcome!r}."
    )

    if expected_review is not None:
        assert result.human_review_required == expected_review, (
            f"{conv_id}: human_review_required got {result.human_review_required!r}, "
            f"expected {expected_review!r}. Reason: {result.human_review_reason}"
        )

    if expected_priority is not None:
        assert result.human_review_priority is not None, (
            f"{conv_id}: human_review_priority is None but expected {expected_priority!r}"
        )
        assert result.human_review_priority.value == expected_priority, (
            f"{conv_id}: priority got {result.human_review_priority.value!r}, "
            f"expected {expected_priority!r}"
        )


# ─────────────────────────────────────────────────────────────────────────
# Invariantes de contrato para TODOS los casos seed
# ─────────────────────────────────────────────────────────────────────────

def test_all_seed_classifications_are_valid(seed):
    """
    Para todos los casos seed: Classification siempre válida,
    rules_triggered siempre lista, y si human_review_required=True
    entonces priority y reason no son vacíos.
    """
    for conv_id, call in seed.items():
        result = classify_call(call, llm=None)

        # Contrato: rules_triggered siempre es lista
        assert isinstance(result.rules_triggered, list), (
            f"{conv_id}: rules_triggered is not a list"
        )

        # Contrato: human_review_required=True siempre tiene priority y reason
        if result.human_review_required:
            assert result.human_review_priority is not None, (
                f"{conv_id}: human_review_required=True but priority is None"
            )
            assert result.human_review_reason != "", (
                f"{conv_id}: human_review_required=True but reason is empty"
            )

        # Contrato: confidence en [0, 1]
        assert 0.0 <= result.confidence <= 1.0, (
            f"{conv_id}: confidence {result.confidence} out of range"
        )
