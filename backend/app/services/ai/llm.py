"""Structured LLM calls with validation and bounded self-correcting retries."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Protocol, TypeVar

from pydantic import BaseModel, ValidationError

from app.core.errors import InvalidAIOutputError
from app.core.settings_store import AppSettings
from app.services.ai.ollama import OllamaClient, parse_json_loose
from app.services.ai.schemas import json_schema

log = logging.getLogger(__name__)
M = TypeVar("M", bound=BaseModel)

SYSTEM = ("You are a careful information-extraction engine. You only use the provided text, never invent content, "
          "and always reply with a single valid JSON object matching the requested schema.")


class StructuredLLM(Protocol):
    model_name: str

    def generate(self, prompt: str, schema: type[M]) -> M: ...


@dataclass
class LLMStats:
    calls: int = 0
    invalid_responses: int = 0
    failures: int = 0
    log: list[str] = field(default_factory=list)


class OllamaStructuredLLM:
    def __init__(self, client: OllamaClient, settings: AppSettings):
        self.client = client
        self.settings = settings
        self.model_name = settings.ollama_model
        self.stats = LLMStats()

    def generate(self, prompt: str, schema: type[M]) -> M:
        messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}]
        last_err = ""
        for attempt in range(1, self.settings.llm_retries + 1):
            self.stats.calls += 1
            raw = self.client.chat(
                self.model_name,
                messages,
                schema=json_schema(schema),
                temperature=self.settings.llm_temperature,
                num_ctx=self.settings.llm_context_size,
                num_predict=self.settings.llm_max_tokens,
            )
            try:
                data = parse_json_loose(raw)
                return schema.model_validate(data)
            except (InvalidAIOutputError, ValidationError) as exc:
                self.stats.invalid_responses += 1
                last_err = str(exc)[:600]
                self.stats.log.append(f"attempt {attempt}: invalid output: {last_err[:200]}")
                log.warning("invalid LLM output (attempt %d): %s", attempt, last_err[:200])
                messages = messages[:2] + [
                    {"role": "assistant", "content": raw[:4000]},
                    {"role": "user", "content": "Your previous reply was not valid for the required JSON schema: "
                                                f"{last_err}\nReply again with ONLY the corrected JSON object."},
                ]
        self.stats.failures += 1
        raise InvalidAIOutputError(f"LLM output invalid after {self.settings.llm_retries} attempts: {last_err}",
                                   user_message="The language model repeatedly returned invalid JSON. "
                                                "Try another model or lower the chunk size.")
