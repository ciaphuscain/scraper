"""Minimal Ollama HTTP client (local API, no cloud)."""
from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx

from app.core.errors import DeferredError, InvalidAIOutputError, PermanentError, TransientError
from app.core.settings_store import AppSettings

log = logging.getLogger(__name__)


class OllamaClient:
    def __init__(self, base_url: str, timeout: float = 900, transport: httpx.BaseTransport | None = None):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._transport = transport

    def _client(self, timeout: float | None = None) -> httpx.Client:
        return httpx.Client(base_url=self.base_url, timeout=timeout or self.timeout, transport=self._transport)

    def list_models(self) -> list[dict[str, Any]]:
        try:
            with self._client(10) as c:
                r = c.get("/api/tags")
                r.raise_for_status()
                return r.json().get("models", [])
        except httpx.HTTPError as exc:
            raise DeferredError(str(exc), user_message=f"Ollama is not reachable at {self.base_url}.") from exc

    def version(self) -> str | None:
        try:
            with self._client(5) as c:
                r = c.get("/api/version")
                r.raise_for_status()
                return r.json().get("version")
        except httpx.HTTPError:
            return None

    def is_available(self) -> bool:
        return self.version() is not None

    def chat(
        self,
        model: str,
        messages: list[dict[str, str]],
        *,
        schema: dict[str, Any] | None = None,
        temperature: float = 0.1,
        num_ctx: int = 8192,
        num_predict: int = 2048,
    ) -> str:
        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": temperature, "num_ctx": num_ctx, "num_predict": num_predict},
            "keep_alive": "10m",
        }
        if schema is not None:
            body["format"] = schema
        try:
            with self._client() as c:
                r = c.post("/api/chat", json=body)
        except httpx.ConnectError as exc:
            raise DeferredError(str(exc), user_message=f"Ollama is offline at {self.base_url}; "
                                                       "analysis will resume when it is available.") from exc
        except httpx.TimeoutException as exc:
            raise TransientError(str(exc), user_message="Ollama request timed out. Consider a smaller model, "
                                                        "smaller chunk size or a longer timeout.") from exc
        except httpx.HTTPError as exc:
            raise TransientError(str(exc)) from exc
        if r.status_code == 404:
            raise PermanentError(r.text, user_message=f"Ollama model '{model}' is not installed. "
                                                      f"Run: ollama pull {model}")
        if r.status_code >= 400:
            raise TransientError(f"Ollama HTTP {r.status_code}: {r.text[:500]}")
        data = r.json()
        return (data.get("message") or {}).get("content", "")


def client_from_settings(settings: AppSettings, transport: httpx.BaseTransport | None = None) -> OllamaClient:
    return OllamaClient(settings.ollama_url, timeout=settings.llm_timeout_seconds, transport=transport)


_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.M)


def parse_json_loose(text: str) -> Any:
    """Parse model output as JSON, tolerating code fences and leading prose."""
    t = text.strip()
    t = _FENCE.sub("", t).strip()
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        pass
    for open_c, close_c in (("{", "}"), ("[", "]")):
        start = t.find(open_c)
        end = t.rfind(close_c)
        if start != -1 and end > start:
            try:
                return json.loads(t[start : end + 1])
            except json.JSONDecodeError:
                continue
    raise InvalidAIOutputError(f"model returned invalid JSON: {text[:300]!r}")
