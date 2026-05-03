"""Generador de llamadas sintéticas — función pura generate()."""

import logging
import os
import random
import uuid
import warnings
from typing import Iterator

from pydantic import BaseModel, ConfigDict

from shared.models import CallRecord
from shared.llm_client import LLMClient
from generator.prompts import SYSTEM_PROMPT, build_user_prompt

log = logging.getLogger(__name__)

# Restaurantes válidos — definidos localmente en caso de que no estén en shared/enums.py
KNOWN_RESTAURANTS: set[str] = {"BG Las Olas", "BG Doral", "BG Brickell"}

# Tipos problemáticos que el generador debe rotar
PROBLEMATIC_TYPES = [
    "WRONG_SMS_SENT",
    "WRONG_SMS_MISSING",
    "UNNECESSARY_TRANSFER",
    "MISSING_TRANSFER",
    "AI_LOOP",
    "SILENT_WRONG_INFO",
    "SPAM",
]

MAX_TOTAL_BATCHES = 20


class CallBatch(BaseModel):
    """Wrapper de validación para el output del LLM."""

    model_config = ConfigDict(extra="forbid")
    calls: list[CallRecord]


def generate(
    n: int,
    seed_calls: list[CallRecord],
    llm: LLMClient,
) -> Iterator[CallRecord]:
    """Genera n llamadas sintéticas usando el LLM.

    Función pura: no escribe archivos. Yieldea CallRecord validados.

    Args:
        n: Cantidad total de llamadas a generar.
        seed_calls: Llamadas del seed para few-shot.
        llm: Instancia de LLMClient.

    Yields:
        CallRecord validados.
    """
    batch_size = int(os.getenv("GENERATOR_BATCH_SIZE", "5"))
    temperature = float(os.getenv("GENERATOR_TEMPERATURE", "0.9"))

    produced = 0
    type_idx = 0
    total_batches = 0

    while produced < n:
        if total_batches >= MAX_TOTAL_BATCHES:
            warnings.warn(
                f"Se alcanzó el límite de {MAX_TOTAL_BATCHES} batches. "
                f"Se generaron {produced}/{n} llamadas.",
                RuntimeWarning,
                stacklevel=2,
            )
            log.warning(
                "Límite de batches alcanzado (%d). Producidas %d/%d llamadas.",
                MAX_TOTAL_BATCHES,
                produced,
                n,
            )
            return

        remaining = n - produced
        size = min(batch_size, remaining)

        # 60% problemáticas para garantizar cobertura en demos cortas
        n_problematic = max(1, size * 60 // 100)
        chosen_types = [
            PROBLEMATIC_TYPES[(type_idx + i) % len(PROBLEMATIC_TYPES)]
            for i in range(n_problematic)
        ]
        type_idx += n_problematic

        # Seleccionar ejemplos aleatorios del seed
        examples = random.sample(seed_calls, k=min(4, len(seed_calls)))

        log.info(
            "Generando batch %d/%d (size=%d, problematic=%d, types=%s)",
            total_batches + 1,
            MAX_TOTAL_BATCHES,
            size,
            n_problematic,
            chosen_types,
        )

        total_batches += 1

        try:
            batch: CallBatch = llm.complete_json(
                system=SYSTEM_PROMPT,
                user=build_user_prompt(examples, size, n_problematic, chosen_types),
                schema=CallBatch,
                temperature=temperature,
                max_tokens=8192,
            )
        except Exception as exc:
            log.error("Batch %d falló con error: %s. Descartando y continuando.", total_batches, exc)
            continue

        batch_valid = 0
        batch_discarded = 0

        for call in batch.calls[:size]:
            # Descartar llamadas con restaurantName inválido
            if call.restaurantName not in KNOWN_RESTAURANTS:
                log.warning(
                    "Llamada descartada: restaurantName inválido %r (conversationId=%s)",
                    call.restaurantName,
                    call.conversationId,
                )
                batch_discarded += 1
                continue

            # Forzar prefijo "gen_" en conversationId
            if not call.conversationId.startswith("gen_"):
                new_id = f"gen_{uuid.uuid4().hex[:8]}"
                log.debug(
                    "conversationId corregido: %r -> %r",
                    call.conversationId,
                    new_id,
                )
                call = call.model_copy(update={"conversationId": new_id})

            yield call
            batch_valid += 1
            produced += 1

            if produced >= n:
                log.info(
                    "Batch %d completo. Total producidas: %d. Válidas en este batch: %d, descartadas: %d",
                    total_batches,
                    produced,
                    batch_valid,
                    batch_discarded,
                )
                return

        log.info(
            "Batch %d completo. Producidas hasta ahora: %d/%d. Válidas: %d, descartadas: %d",
            total_batches,
            produced,
            n,
            batch_valid,
            batch_discarded,
        )
