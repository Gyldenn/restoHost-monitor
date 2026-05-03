import logging
import sys
from pathlib import Path

LOGS_DIR = Path(__file__).resolve().parent.parent / "logs"
LOGS_DIR.mkdir(exist_ok=True)

def setup_logging(module_name: str, level: int = logging.INFO) -> logging.Logger:
    fmt = logging.Formatter(
        "%(asctime)s [%(name)s] %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler_stdout = logging.StreamHandler(sys.stdout)
    handler_stdout.setFormatter(fmt)
    handler_file = logging.FileHandler(LOGS_DIR / f"{module_name}.log", encoding="utf-8")
    handler_file.setFormatter(fmt)

    log = logging.getLogger(module_name)
    log.setLevel(level)
    log.handlers.clear()
    log.addHandler(handler_stdout)
    log.addHandler(handler_file)
    return log
