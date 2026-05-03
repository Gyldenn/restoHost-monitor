"""
Capa 2: análisis de conversación con LLM.

Sólo se invoca cuando Capa 1 no fue suficiente para concluir.
"""

import logging

from pydantic import BaseModel, ConfigDict, Field

from shared.enums import ErrorType, OutcomeCategory
from shared.llm_client import LLMClient
from shared.models import CallRecord
from classifier.prompts import SYSTEM_PROMPT

log = logging.getLogger(__name__)


class LLMClassification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    error_type: ErrorType
    outcome_category: OutcomeCategory
    error_description: str
    expected_behavior: str
    confidence: float = Field(..., ge=0.0, le=1.0)
    reasoning: str  # para debug, no se persiste


def _build_user_prompt(call: CallRecord, markers: list[str]) -> str:
    markers_str = ", ".join(markers) if markers else "none"
    schema_hint = (
        '{\n'
        '  "error_type": "<NO_ERROR|WRONG_SMS|WRONG_TRANSFER|WRONG_INFO|LOOP|INCOMPLETE|AMBIGUOUS>",\n'
        '  "outcome_category": "<Resolved|Transferred|Spam|Error|Ambiguous>",\n'
        '  "error_description": "<1-2 sentences: what happened>",\n'
        '  "expected_behavior": "<1-2 sentences: what should have happened>",\n'
        '  "confidence": <0.0-1.0>,\n'
        '  "reasoning": "<brief debug note>"\n'
        '}'
    )
    return (
        f"Analizá esta llamada:\n\n"
        f"{call.model_dump_json(indent=2)}\n\n"
        f"Pistas de capa determinística (markers): [{markers_str}]\n\n"
        f"Devolvé JSON con este schema exacto:\n{schema_hint}"
    )


def analyze_with_llm(
    call: CallRecord,
    markers: list[str],
    llm: LLMClient,
) -> LLMClassification:
    """
    Llama al LLM con el system prompt del clasificador y el contexto completo
    de la llamada. Retorna LLMClassification validada.

    Lanza excepción si el LLM falla 2 veces (manejado por classify_call).
    """
    user_prompt = _build_user_prompt(call, markers)
    log.debug("Calling LLM for conversation %s (markers=%s)", call.conversationId, markers)

    result = llm.complete_json(
        system=SYSTEM_PROMPT,
        user=user_prompt,
        schema=LLMClassification,
        max_tokens=1024,
        temperature=0.2,  # baja temperatura para mayor consistencia en clasificación
    )
    log.debug(
        "LLM classified %s → %s / %s (conf=%.2f)",
        call.conversationId,
        result.error_type,
        result.outcome_category,
        result.confidence,
    )
    return result
