"""Entry point del generador de llamadas sintéticas.

Uso:
    python -m generator.cli --n 30 --out data/generated_calls.jsonl
    python -m generator.cli --n 30 --out data/generated_calls.jsonl --stream
"""

import argparse
import json
import logging
import os
import random
import time
from pathlib import Path

# Cargar .env antes de importar módulos que usan variables de entorno
try:
    from dotenv import load_dotenv

    _env_path = Path(__file__).resolve().parent.parent / ".env"
    load_dotenv(_env_path)
except ImportError:
    pass  # python-dotenv no instalado; las env vars deben estar ya seteadas

from shared.logging_config import setup_logging
from shared.llm_client import LLMClient
from shared.models import CallRecord
from shared.io import append_event, DATA_DIR
from generator.generator import generate


def load_seed_calls(seed_path: Path) -> list[CallRecord]:
    """Carga el seed desde un JSON array (no JSONL)."""
    with seed_path.open("r", encoding="utf-8") as f:
        raw = json.load(f)
    return [CallRecord.model_validate(item) for item in raw]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generador de llamadas sintéticas RestoHost"
    )
    parser.add_argument(
        "--n",
        type=int,
        default=30,
        help="Cantidad de llamadas a generar (default: 30)",
    )
    parser.add_argument(
        "--out",
        type=str,
        default=str(DATA_DIR / "generated_calls.jsonl"),
        help="Ruta del archivo JSONL de salida",
    )
    parser.add_argument(
        "--stream",
        action="store_true",
        help="Modo stream: sleep entre llamadas generadas",
    )
    parser.add_argument(
        "--seed",
        type=str,
        default=str(DATA_DIR / "calls_seed.json"),
        help="Ruta al archivo seed JSON",
    )
    args = parser.parse_args()

    log = setup_logging("generator")
    log.info("Iniciando generador. n=%d, out=%s, stream=%s", args.n, args.out, args.stream)

    # Verificar GROQ_API_KEY
    if not os.environ.get("GROQ_API_KEY"):
        log.error("GROQ_API_KEY no está seteada. Copiá .env.example a .env y completala.")
        raise SystemExit(1)

    # Cargar seed
    seed_path = Path(args.seed)
    if not seed_path.exists():
        log.error("Seed no encontrado: %s", seed_path)
        raise SystemExit(1)

    seed_calls = load_seed_calls(seed_path)
    log.info("Seed cargado: %d llamadas", len(seed_calls))

    # Instanciar LLM
    try:
        llm = LLMClient()
    except RuntimeError as e:
        log.error("Error al instanciar LLMClient: %s", e)
        raise SystemExit(1)

    log.info("LLMClient listo: %s", llm)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    min_delay = float(os.getenv("GENERATOR_MIN_DELAY", "0.5"))
    max_delay = float(os.getenv("GENERATOR_MAX_DELAY", "3.0"))

    count = 0
    for call in generate(args.n, seed_calls, llm):
        append_event(out_path, call)
        count += 1
        log.info("[%d/%d] Llamada guardada: %s (%s)", count, args.n, call.conversationId, call.restaurantName)

        if args.stream:
            delay = random.uniform(min_delay, max_delay)
            log.debug("Stream mode: sleeping %.2fs", delay)
            time.sleep(delay)

    log.info("Generación completa. Total guardadas: %d en %s", count, out_path)


if __name__ == "__main__":
    main()
