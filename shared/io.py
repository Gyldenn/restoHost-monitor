import json
import logging
from pathlib import Path
from typing import Iterator, Type, TypeVar
from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)
log = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

def append_event(path: Path, model: BaseModel) -> None:
    """Escribe una línea JSON al final del archivo. Atómico para líneas
    pequeñas en POSIX (single write < PIPE_BUF)."""
    line = model.model_dump_json() + "\n"
    with path.open("a", encoding="utf-8") as f:
        f.write(line)
        f.flush()

def read_all(path: Path, schema: Type[T]) -> list[T]:
    if not path.exists():
        return []
    out = []
    with path.open("r", encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                out.append(schema.model_validate_json(line))
            except ValidationError as e:
                log.error("Invalid line %d in %s: %s", i, path, e)
    return out

def tail_follow(path: Path, schema: Type[T], poll_interval: float = 0.5) -> Iterator[T]:
    """Generator que hace tail-follow de un JSONL, yieldea líneas validadas.
    Bloquea esperando nuevas líneas. Pensado para Módulos 2, 3, 4."""
    import time
    path.touch(exist_ok=True)
    with path.open("r", encoding="utf-8") as f:
        while True:
            line = f.readline()
            if not line:
                time.sleep(poll_interval)
                continue
            line = line.strip()
            if not line:
                continue
            try:
                yield schema.model_validate_json(line)
            except ValidationError as e:
                log.error("Invalid tail line in %s: %s", path, e)
