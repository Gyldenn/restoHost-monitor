"""Pipeline orchestrator.

Modes:
  python main.py --mode batch --n 30
  python main.py --mode stream --n 30
"""
import argparse
import os
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"

def run_batch(n: int):
    # 1) generar
    subprocess.check_call([sys.executable, "-m", "generator.cli",
                           "--n", str(n),
                           "--out", str(DATA / "generated_calls.jsonl")])
    # 2) clasificar
    subprocess.check_call([sys.executable, "-m", "classifier.cli",
                           "--input", str(DATA / "generated_calls.jsonl"),
                           "--output", str(DATA / "classified_calls.jsonl")])
    # 3) métricas
    subprocess.check_call([sys.executable, "-m", "metrics.cli", "--batch"])

def run_stream(n: int):
    # arranca cada módulo como proceso
    procs = [
        subprocess.Popen([sys.executable, "-m", "generator.cli",
                          "--n", str(n),
                          "--out", str(DATA / "generated_calls.jsonl"),
                          "--stream"]),
        subprocess.Popen([sys.executable, "-m", "classifier.cli",
                          "--input", str(DATA / "generated_calls.jsonl"),
                          "--output", str(DATA / "classified_calls.jsonl"),
                          "--stream"]),
        subprocess.Popen([sys.executable, "-m", "metrics.cli"]),
    ]
    print(f"Pipeline started. PIDs: {[p.pid for p in procs]}")
    print(f"Run `streamlit run dashboard/app.py` in another terminal.")
    try:
        for p in procs:
            p.wait()
    except KeyboardInterrupt:
        for p in procs:
            p.terminate()

def main():
    load_dotenv()
    if not os.environ.get("GROQ_API_KEY"):
        sys.exit("GROQ_API_KEY no seteada. Copiá .env.example a .env.")
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["batch", "stream"], default="batch")
    ap.add_argument("--n", type=int, default=30)
    args = ap.parse_args()
    {"batch": run_batch, "stream": run_stream}[args.mode](args.n)

if __name__ == "__main__":
    main()
