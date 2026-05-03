"""Tests del generador: validación de schema, filtrado y corrección de IDs."""

import uuid
from unittest.mock import MagicMock

import pytest

from shared.models import CallRecord
from generator.generator import CallBatch, generate, KNOWN_RESTAURANTS


# ─── Fixtures de datos ───────────────────────────────────────────────────────

VALID_CALL_DATA = {
    "conversationId": "gen_abc12345",
    "restaurantName": "BG Las Olas",
    "callStartTime": "2026-04-28T19:32:10.000-04:00",
    "callDuration": "02:15",
    "callEndReason": "UserHangup",
    "callWithinOfficeHours": True,
    "reasonForCalling": "Making a Reservation or Inquiring About Reservations",
    "reasonForTransfering": "",
    "reasonForSendingText": "reservation",
    "numberOfTextsSent": 1,
    "partySize": "Small party",
    "partysizenumber": "2",
    "detectederror": "No Error Detected",
    "errorCategory": "No Error Detected",
    "customerfrustration": "no",
    "speakInSpanish": "no",
    "menuMention": "no",
    "eventMention": "no",
    "callsHighlights": "No Highlight",
    "friendlysummary": "Customer reserved a table for 2. AI handled correctly.",
    "conversation": "Assistant: Hi, thanks for calling. How can I help?\nCustomer: Reservation for 2 please.\nAssistant: Done! See you then.",
}


def make_call(**overrides) -> dict:
    data = dict(VALID_CALL_DATA)
    data.update(overrides)
    return data


def make_seed_calls(n: int = 3) -> list[CallRecord]:
    calls = []
    for i in range(n):
        calls.append(
            CallRecord.model_validate(
                make_call(
                    conversationId=f"mock_{i:03d}",
                    restaurantName=["BG Las Olas", "BG Doral", "BG Brickell"][i % 3],
                )
            )
        )
    return calls


# ─── Tests ───────────────────────────────────────────────────────────────────


def test_generate_returns_valid_call_records(fake_llm):
    """generate() con fake_llm que devuelve CallBatch válido → output son CallRecord válidos."""
    call1 = CallRecord.model_validate(make_call(conversationId="gen_aaa11111"))
    call2 = CallRecord.model_validate(make_call(
        conversationId="gen_bbb22222",
        restaurantName="BG Doral",
        reasonForCalling="Questions about restaurant hours and wait times",
    ))

    batch = CallBatch(calls=[call1, call2])
    fake_llm.complete_json.return_value = batch

    seed = make_seed_calls()
    results = list(generate(n=2, seed_calls=seed, llm=fake_llm))

    assert len(results) == 2
    for r in results:
        assert isinstance(r, CallRecord)
        # Cada resultado debe validar como CallRecord
        CallRecord.model_validate(r.model_dump())


def test_generate_returns_correct_number(fake_llm):
    """generate() produce exactamente n llamadas (cuando el LLM coopera)."""
    calls = [
        CallRecord.model_validate(make_call(conversationId=f"gen_{i:08x}"))
        for i in range(5)
    ]
    batch = CallBatch(calls=calls)
    fake_llm.complete_json.return_value = batch

    seed = make_seed_calls()
    results = list(generate(n=3, seed_calls=seed, llm=fake_llm))

    assert len(results) == 3


def test_invalid_restaurant_filtered(fake_llm):
    """Llamadas con restaurantName inválido son filtradas silenciosamente.

    El batch contiene primero la llamada válida y luego la inválida.
    Pedimos n=1 → el generador debe yieldar solo la válida.
    """
    valid_call = CallRecord.model_validate(
        make_call(conversationId="gen_valid001", restaurantName="BG Brickell")
    )
    invalid_call = CallRecord.model_validate(
        make_call(conversationId="gen_invalid1", restaurantName="BG Miami")
    )

    # Batch con la válida primero, pedimos n=1
    batch = CallBatch(calls=[valid_call, invalid_call])
    fake_llm.complete_json.return_value = batch

    seed = make_seed_calls()
    results = list(generate(n=1, seed_calls=seed, llm=fake_llm))

    assert len(results) == 1
    assert results[0].restaurantName in KNOWN_RESTAURANTS
    assert results[0].conversationId == "gen_valid001"


def test_invalid_restaurant_filtered_leading_invalid(fake_llm):
    """Cuando todas las llamadas del batch son inválidas, se descartan y se pide otro batch.

    Para este test ponemos una llamada inválida en el primer batch y una válida en el segundo.
    """
    invalid_call = CallRecord.model_validate(
        make_call(conversationId="gen_bad99999", restaurantName="Restaurant Inventado")
    )
    valid_call = CallRecord.model_validate(
        make_call(conversationId="gen_ok000001", restaurantName="BG Doral")
    )

    invalid_batch = CallBatch(calls=[invalid_call])
    valid_batch = CallBatch(calls=[valid_call])

    # Primer llamado devuelve inválida, segundo devuelve válida
    fake_llm.complete_json.side_effect = [invalid_batch, valid_batch]

    seed = make_seed_calls()
    results = list(generate(n=1, seed_calls=seed, llm=fake_llm))

    assert len(results) == 1
    assert results[0].restaurantName == "BG Doral"
    assert results[0].conversationId == "gen_ok000001"


def test_all_invalid_restaurants_triggers_more_batches(fake_llm):
    """Si todas las llamadas son inválidas, se pide más batches hasta MAX_TOTAL_BATCHES."""
    invalid_call = CallRecord.model_validate(
        make_call(conversationId="gen_bad00001", restaurantName="BG Miami")
    )
    batch = CallBatch(calls=[invalid_call])
    fake_llm.complete_json.return_value = batch

    seed = make_seed_calls()
    import warnings
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        results = list(generate(n=1, seed_calls=seed, llm=fake_llm))
        # Debe emitir warning de límite alcanzado
        assert any("límite" in str(warning.message).lower() or "MAX" in str(warning.message) or "batches" in str(warning.message).lower() for warning in w)

    assert len(results) == 0


def test_conversation_id_without_prefix_is_corrected(fake_llm):
    """conversationId sin prefijo 'gen_' es corregido automáticamente."""
    call_without_prefix = CallRecord.model_validate(
        make_call(conversationId="mock_no_prefix_1")
    )
    batch = CallBatch(calls=[call_without_prefix])
    fake_llm.complete_json.return_value = batch

    seed = make_seed_calls()
    results = list(generate(n=1, seed_calls=seed, llm=fake_llm))

    assert len(results) == 1
    assert results[0].conversationId.startswith("gen_")
    # El ID original no debe permanecer
    assert results[0].conversationId != "mock_no_prefix_1"


def test_conversation_id_with_prefix_is_preserved(fake_llm):
    """conversationId que ya tiene prefijo 'gen_' no se modifica."""
    original_id = "gen_deadbeef"
    call_with_prefix = CallRecord.model_validate(make_call(conversationId=original_id))
    batch = CallBatch(calls=[call_with_prefix])
    fake_llm.complete_json.return_value = batch

    seed = make_seed_calls()
    results = list(generate(n=1, seed_calls=seed, llm=fake_llm))

    assert len(results) == 1
    assert results[0].conversationId == original_id


def test_generate_uses_llm_complete_json(fake_llm):
    """generate() llama a llm.complete_json con system y user prompt."""
    call = CallRecord.model_validate(make_call())
    batch = CallBatch(calls=[call])
    fake_llm.complete_json.return_value = batch

    seed = make_seed_calls()
    list(generate(n=1, seed_calls=seed, llm=fake_llm))

    fake_llm.complete_json.assert_called()
    call_kwargs = fake_llm.complete_json.call_args
    # Debe pasar schema=CallBatch
    assert call_kwargs.kwargs.get("schema") is CallBatch or (
        len(call_kwargs.args) >= 3 and call_kwargs.args[2] is CallBatch
    )


def test_call_batch_validates_pydantic():
    """CallBatch valida correctamente con Pydantic."""
    call = CallRecord.model_validate(VALID_CALL_DATA)
    batch = CallBatch(calls=[call])
    assert len(batch.calls) == 1
    assert isinstance(batch.calls[0], CallRecord)


def test_call_batch_rejects_extra_fields():
    """CallBatch rechaza campos extra (extra='forbid')."""
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        CallBatch(calls=[], extra_field="not allowed")
