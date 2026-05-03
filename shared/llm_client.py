import json
import logging
import os
import time
from typing import Type, TypeVar

from pydantic import BaseModel, ValidationError
from groq import Groq, RateLimitError

T = TypeVar("T", bound=BaseModel)
log = logging.getLogger(__name__)

class LLMClient:
    """Wrapper para Groq con:
    - JSON mode forzado
    - Validación Pydantic con 1 reintento dando feedback del error
    - Backoff exponencial en 429
    """

    def __init__(self, model: str | None = None):
        self.api_key = os.environ.get("GROQ_API_KEY")
        if not self.api_key:
            raise RuntimeError("GROQ_API_KEY no está seteada. Copiá .env.example a .env.")
        self.model = model or os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
        self._client = Groq(api_key=self.api_key)

    def __repr__(self):
        return f"LLMClient(model={self.model!r}, key=***)"

    def complete_json(
        self,
        system: str,
        user: str,
        schema: Type[T],
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> T:
        """Pide al LLM una respuesta JSON, la valida contra `schema`. Reintenta
        1 vez si la validación falla."""
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        for attempt in (1, 2):
            raw = self._call(messages, max_tokens, temperature)
            try:
                data = json.loads(raw)
                return schema.model_validate(data)
            except (json.JSONDecodeError, ValidationError) as e:
                log.warning("LLM output failed validation (attempt %d): %s", attempt, e)
                if attempt == 2:
                    raise
                # feedback al LLM con el error específico
                messages.append({"role": "assistant", "content": raw})
                messages.append({
                    "role": "user",
                    "content": f"Tu respuesta anterior no validó: {e}. "
                               f"Devolveme JSON estricto que cumpla el schema.",
                })

    def _call(self, messages, max_tokens, temperature) -> str:
        delay = 1.0
        for _ in range(5):
            try:
                resp = self._client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    response_format={"type": "json_object"},
                )
                return resp.choices[0].message.content
            except RateLimitError:
                log.warning("Rate limited, sleeping %.1fs", delay)
                time.sleep(delay)
                delay *= 2
        raise RuntimeError("Groq rate limit no recuperable")
