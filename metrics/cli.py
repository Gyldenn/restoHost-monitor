"""CLI entry point for the metrics engine.

Usage:
    python -m metrics.cli           # tail-follow mode (streaming)
    python -m metrics.cli --batch   # process all available data and exit
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

# Resolve project root so imports work regardless of cwd
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from shared.io import DATA_DIR, append_event, read_all, tail_follow
from shared.models import Alert, CallRecord, Classification, MetricsSnapshot
from metrics.engine import MetricsEngine

log = logging.getLogger("metrics.cli")


def load_calls_index(paths: list[Path]) -> dict[str, CallRecord]:
    index: dict[str, CallRecord] = {}
    for path in paths:
        if not path.exists():
            continue
        if path.suffix == ".json":  # seed (array)
            data = json.load(path.open(encoding="utf-8"))
            for d in data:
                r = CallRecord.model_validate(d)
                index[r.conversationId] = r
        else:  # jsonl
            for r in read_all(path, CallRecord):
                index[r.conversationId] = r
    return index


def write_snapshot(snapshot: MetricsSnapshot, path: Path) -> None:
    """Atomic overwrite of current_metrics.json."""
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(snapshot.model_dump_json(indent=2), encoding="utf-8")
    tmp.replace(path)


def run_batch(engine: MetricsEngine, calls_index: dict[str, CallRecord]) -> MetricsSnapshot | None:
    classifications = read_all(DATA_DIR / "classified_calls.jsonl", Classification)
    if not classifications:
        log.warning("No classified calls found in %s", DATA_DIR / "classified_calls.jsonl")
        return None

    for cls in classifications:
        record = calls_index.get(cls.conversationId)
        if record is None:
            log.warning("Classification for unknown call %s — skipping", cls.conversationId)
            continue
        engine.ingest(record, cls)

    snap = engine.snapshot()
    for alert in engine.check_alerts(snap):
        append_event(DATA_DIR / "alerts.jsonl", alert)

    write_snapshot(snap, DATA_DIR / "current_metrics.json")
    return snap


def run_stream(engine: MetricsEngine, calls_index: dict[str, CallRecord]) -> None:
    log.info("Starting tail-follow on %s", DATA_DIR / "classified_calls.jsonl")
    for cls in tail_follow(DATA_DIR / "classified_calls.jsonl", Classification):
        record = calls_index.get(cls.conversationId)
        if record is None:
            log.warning("Classification for unknown call %s — skipping", cls.conversationId)
            continue

        engine.ingest(record, cls)
        snap = engine.snapshot()

        for alert in engine.check_alerts(snap):
            append_event(DATA_DIR / "alerts.jsonl", alert)
            log.info("Alert fired: %s [%s]", alert.metric, alert.severity.value)

        write_snapshot(snap, DATA_DIR / "current_metrics.json")
        log.debug("Snapshot updated: total_calls=%d", snap.total_calls)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    parser = argparse.ArgumentParser(description="RestoHost metrics engine")
    parser.add_argument(
        "--batch",
        action="store_true",
        help="Process all available data and exit (no tail-follow)",
    )
    args = parser.parse_args()

    calls_index = load_calls_index([
        DATA_DIR / "calls_seed.json",
        DATA_DIR / "generated_calls.jsonl",
    ])
    log.info("Loaded %d call records into index", len(calls_index))

    engine = MetricsEngine()

    if args.batch:
        snap = run_batch(engine, calls_index)
        if snap:
            log.info(
                "Batch complete — total_calls=%d, error_rate=%s",
                snap.total_calls,
                f"{snap.error_rate:.1%}" if snap.error_rate is not None else "N/A",
            )
        else:
            log.info("Batch complete — no data processed")
    else:
        run_stream(engine, calls_index)


if __name__ == "__main__":
    main()
