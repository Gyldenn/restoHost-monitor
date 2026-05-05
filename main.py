"""Pipeline orchestrator.

Modes:
  python main.py --mode batch --n 30
  python main.py --mode stream --n 30
  python main.py --mode batch --input-calls path/to/calls.jsonl   # saltea el generador
"""
import argparse
import os
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"

def run_batch(n: int, input_calls: Path | None = None):
    calls_path = input_calls if input_calls else DATA / "generated_calls.jsonl"

    if input_calls is None:
        # 1) generar
        subprocess.check_call([sys.executable, "-m", "generator.cli",
                               "--n", str(n),
                               "--out", str(calls_path)])
    else:
        print(f"Skipping generator — using external calls file: {calls_path}")

    # 2) clasificar
    subprocess.check_call([sys.executable, "-m", "classifier.cli",
                           "--input", str(calls_path),
                           "--output", str(DATA / "classified_calls.jsonl")])
    # 3) métricas
    subprocess.check_call([sys.executable, "-m", "metrics.cli", "--batch"])

def run_stream(n: int, input_calls: Path | None = None):
    calls_path = input_calls if input_calls else DATA / "generated_calls.jsonl"
    procs = []

    if input_calls is None:
        procs.append(subprocess.Popen([sys.executable, "-m", "generator.cli",
                                       "--n", str(n),
                                       "--out", str(calls_path),
                                       "--stream"]))
    else:
        print(f"Skipping generator — using external calls file: {calls_path}")

    procs.extend([
        subprocess.Popen([sys.executable, "-m", "classifier.cli",
                          "--input", str(calls_path),
                          "--output", str(DATA / "classified_calls.jsonl"),
                          "--stream"]),
        subprocess.Popen([sys.executable, "-m", "metrics.cli"]),
    ])
    print(f"Pipeline started. PIDs: {[p.pid for p in procs]}")
    print("Run `streamlit run dashboard/app.py` in another terminal.")
    try:
        for p in procs:
            p.wait()
    except KeyboardInterrupt:
        for p in procs:
            p.terminate()

def main():
    load_dotenv()
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["batch", "stream"], default="batch")
    ap.add_argument("--n", type=int, default=30)
    ap.add_argument("--input-calls", type=Path, default=None,
                    help="Path a un .jsonl/.json de llamadas ya generadas. "
                         "Si se especifica, se saltea el módulo generador.")
    args = ap.parse_args()

    if args.input_calls is not None and not args.input_calls.exists():
        sys.exit(f"--input-calls: archivo no encontrado: {args.input_calls}")

    if not os.environ.get("GROQ_API_KEY"):
        sys.exit("GROQ_API_KEY no seteada. Copiá .env.example a .env.")

    {"batch": run_batch, "stream": run_stream}[args.mode](args.n, args.input_calls)

if __name__ == "__main__":
    main()
