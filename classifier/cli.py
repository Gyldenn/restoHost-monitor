"""
CLI del módulo clasificador.

Uso:
  python -m classifier.cli --input data/generated_calls.jsonl --output data/classified_calls.jsonl
  python -m classifier.cli --input data/generated_calls.jsonl --output data/classified_calls.jsonl --stream
  python -m classifier.cli --input data/generated_calls.jsonl --output data/classified_calls.jsonl --offline
"""

import argparse
import json
import logging
import signal
import sys
from pathlib import Path

from pydantic import ValidationError

from shared.io import DATA_DIR, append_event, read_all, tail_follow
from shared.models import CallRecord, Classification
from classifier.classifier import classify_call

log = logging.getLogger(__name__)


def _get_llm():
    """Intenta crear LLMClient; devuelve None si falla (modo offline automático)."""
    try:
        from shared.llm_client import LLMClient
        return LLMClient()
    except Exception as e:
        log.warning("LLM not available (%s) — running offline (layers 1+3 only).", e)
        return None


def _resolve_path(raw: str) -> Path:
    p = Path(raw)
    if not p.is_absolute():
        p = DATA_DIR / raw
    return p


def _classify_and_write(call: CallRecord, output_path: Path, llm) -> None:
    try:
        result = classify_call(call, llm=llm)
        append_event(output_path, result)
        print(
            f"[OK] {call.conversationId} → {result.error_type.value} / "
            f"{result.outcome_category.value} (conf={result.confidence:.2f})"
            + (" [REVIEW]" if result.human_review_required else ""),
            flush=True,
        )
    except Exception as e:
        log.error("Failed to classify %s: %s", call.conversationId, e)


def run_batch(input_path: Path, output_path: Path, llm) -> None:
    """Lee todas las líneas del input y las clasifica."""
    calls = read_all(input_path, CallRecord)
    if not calls:
        # También intentar leer como JSON array (para calls_seed.json)
        try:
            raw = json.loads(input_path.read_text(encoding="utf-8"))
            if isinstance(raw, list):
                calls = [CallRecord.model_validate(d) for d in raw]
        except Exception as e:
            log.error("Could not read input file %s: %s", input_path, e)
            sys.exit(1)

    log.info("Processing %d calls from %s", len(calls), input_path)
    for call in calls:
        _classify_and_write(call, output_path, llm)


def run_stream(input_path: Path, output_path: Path, llm) -> None:
    """Hace tail-follow del input y va clasificando en tiempo real. Termina con SIGINT."""

    def _shutdown(signum, frame):
        print("\nStopped.", flush=True)
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)

    print(f"Streaming {input_path} → {output_path}  (Ctrl+C to stop)", flush=True)
    for call in tail_follow(input_path, CallRecord):
        _classify_and_write(call, output_path, llm)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    parser = argparse.ArgumentParser(
        description="RestoHost call classifier",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--input", required=True, help="Input JSONL (or JSON array) file path")
    parser.add_argument("--output", required=True, help="Output JSONL file path")
    parser.add_argument(
        "--stream",
        action="store_true",
        help="Tail-follow input and classify in real time",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Run without LLM (layers 1+3 only)",
    )
    args = parser.parse_args()

    input_path = _resolve_path(args.input)
    output_path = _resolve_path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    llm = None if args.offline else _get_llm()

    if args.stream:
        run_stream(input_path, output_path, llm)
    else:
        run_batch(input_path, output_path, llm)


if __name__ == "__main__":
    main()
