"""Tests de los prompts del generador."""

import json

import pytest

from shared.models import CallRecord
from generator.prompts import SYSTEM_PROMPT, build_user_prompt
from generator.generator import PROBLEMATIC_TYPES


# ─── Datos de soporte ────────────────────────────────────────────────────────

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
    "friendlysummary": "Customer reserved a table for 2.",
    "conversation": "Assistant: Hi!\nCustomer: Reservation for 2.\nAssistant: Done!",
}


def make_seed(n: int = 3) -> list[CallRecord]:
    calls = []
    restaurants = ["BG Las Olas", "BG Doral", "BG Brickell"]
    for i in range(n):
        data = dict(VALID_CALL_DATA)
        data["conversationId"] = f"mock_{i:03d}"
        data["restaurantName"] = restaurants[i % 3]
        calls.append(CallRecord.model_validate(data))
    return calls


# ─── Tests de SYSTEM_PROMPT ──────────────────────────────────────────────────


def test_system_prompt_contains_rol():
    """SYSTEM_PROMPT contiene la descripción del rol."""
    assert "generador de llamadas sintéticas" in SYSTEM_PROMPT
    assert "RestoHost" in SYSTEM_PROMPT
    assert "Baires Grill" in SYSTEM_PROMPT


def test_system_prompt_contains_all_reason_for_calling_values():
    """SYSTEM_PROMPT contiene los valores exactos de reasonForCalling."""
    expected_reasons = [
        "Making a Reservation or Inquiring About Reservations",
        "Questions about restaurant hours and wait times",
        "General information and amenities",
        "Special event or holiday inquiry",
        "Placing an order for takeout or delivery",
        "Menu inquiries and special dietary needs",
        "Lost items inquiries",
        "Employment opportunities or business inquiries",
        "Assistance with online platforms and technical issues",
        "Private event or client custom event inquiry",
        "Catering request",
        "Gift card request",
        "Payment issues",
        "Request to speak to a human, to a person, to customer service, to the host or the hostess",
        "Request to speak to a human, to a person, to customer support, to the representative or to someone",
    ]
    for reason in expected_reasons:
        assert reason in SYSTEM_PROMPT, f"Razón faltante en SYSTEM_PROMPT: {reason!r}"


def test_system_prompt_contains_sms_categories():
    """SYSTEM_PROMPT contiene los valores de SmsCategory."""
    expected_categories = [
        "reservation",
        "csf",
        "menu",
        "directions",
        "delivery",
        "large party form",
        "experiences",
        "waitlist",
        "private events",
        "catering",
        "giftcards",
        "job form",
        "careers web",
        "social media",
        "web",
        "pickup",
    ]
    for cat in expected_categories:
        assert cat in SYSTEM_PROMPT, f"SmsCategory faltante en SYSTEM_PROMPT: {cat!r}"


def test_system_prompt_contains_call_end_reasons():
    """SYSTEM_PROMPT contiene los valores de callEndReason."""
    expected_reasons = ["AgentHangup", "UserHangup", "UserInactivity", "CallTransfer"]
    for reason in expected_reasons:
        assert reason in SYSTEM_PROMPT, f"callEndReason faltante en SYSTEM_PROMPT: {reason!r}"


def test_system_prompt_contains_schema_instruction():
    """SYSTEM_PROMPT incluye instrucción de schema JSON."""
    assert '{"calls":' in SYSTEM_PROMPT or '"calls"' in SYSTEM_PROMPT


def test_system_prompt_contains_restaurant_names():
    """SYSTEM_PROMPT menciona los tres restaurantes válidos."""
    assert "BG Las Olas" in SYSTEM_PROMPT
    assert "BG Doral" in SYSTEM_PROMPT
    assert "BG Brickell" in SYSTEM_PROMPT


# ─── Tests de build_user_prompt ──────────────────────────────────────────────


def test_build_user_prompt_includes_batch_size():
    """build_user_prompt incluye el batch_size solicitado."""
    seed = make_seed(4)
    prompt = build_user_prompt(seed, batch_size=5, n_problematic=3, chosen_types=["WRONG_SMS_SENT", "AI_LOOP", "SPAM"])
    assert "5" in prompt


def test_build_user_prompt_includes_chosen_types():
    """build_user_prompt incluye los tipos problemáticos pedidos."""
    seed = make_seed(3)
    chosen = ["WRONG_SMS_SENT", "AI_LOOP", "SPAM"]
    prompt = build_user_prompt(seed, batch_size=5, n_problematic=3, chosen_types=chosen)
    for t in chosen:
        assert t in prompt, f"Tipo {t!r} no encontrado en el user prompt"


def test_build_user_prompt_includes_seed_examples():
    """build_user_prompt incluye JSON de los ejemplos seed."""
    seed = make_seed(2)
    prompt = build_user_prompt(seed, batch_size=5, n_problematic=2, chosen_types=["AI_LOOP", "SPAM"])
    # Al menos un conversationId del seed debe aparecer
    found = any(call.conversationId in prompt for call in seed)
    assert found, "Ningún conversationId del seed aparece en el user prompt"


def test_build_user_prompt_includes_all_problematic_type_descriptions():
    """build_user_prompt describe todos los tipos problemáticos posibles."""
    seed = make_seed(3)
    prompt = build_user_prompt(seed, batch_size=5, n_problematic=3, chosen_types=["WRONG_SMS_SENT"])
    # La sección de tipos debe estar presente
    for ptype in PROBLEMATIC_TYPES:
        assert ptype in prompt, f"Tipo problemático {ptype!r} no está descrito en el user prompt"


def test_build_user_prompt_specifies_normal_vs_problematic_counts():
    """build_user_prompt especifica cuántas normales y cuántas problemáticas."""
    seed = make_seed(3)
    prompt = build_user_prompt(seed, batch_size=5, n_problematic=3, chosen_types=["SPAM", "AI_LOOP", "WRONG_SMS_SENT"])
    # 2 normales, 3 problemáticas
    assert "2" in prompt  # normales
    assert "3" in prompt  # problemáticas


def test_build_user_prompt_output_instruction():
    """build_user_prompt incluye instrucción de output JSON."""
    seed = make_seed(2)
    prompt = build_user_prompt(seed, batch_size=3, n_problematic=2, chosen_types=["SPAM", "AI_LOOP"])
    assert "calls" in prompt
    assert "JSON" in prompt


def test_build_user_prompt_gen_prefix_rule():
    """build_user_prompt menciona la regla del prefijo 'gen_'."""
    seed = make_seed(2)
    prompt = build_user_prompt(seed, batch_size=3, n_problematic=1, chosen_types=["SPAM"])
    assert "gen_" in prompt
