"""Provider-neutral LLM adapter, built on litellm.

Selecting a different provider (Ollama, OpenAI, Azure OpenAI, Anthropic,
...) is purely a MODEL_NAME env var change — litellm routes by the model
string's provider prefix (e.g. "ollama/qwen3.5:4b", "gpt-4o",
"azure/my-deployment"). This is deliberately the interface Phase 1 wires a
local Ollama model into and Phase 4's full controlled-enhancement workflow
(evidence links, human approval, budget limits) later builds on without a
pipeline rework.

Every call degrades gracefully to `None` on failure — a slow, unreachable,
or misconfigured LLM must never break document generation. Local models in
particular can have very high cold-start latency (the first request after
an idle period has to load model weights into memory), so the timeout is
generous by default.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

import litellm

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS = 120.0


@dataclass(frozen=True)
class LLMSettings:
    model_name: str
    api_base: str | None
    thinking: bool
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS

    @classmethod
    def from_env(cls) -> "LLMSettings | None":
        model_name = os.environ.get("MODEL_NAME", "").strip()
        if not model_name:
            return None
        return cls(
            model_name=model_name,
            api_base=os.environ.get("OLLAMA_BASE_URL", "").strip() or None,
            thinking=os.environ.get("LLM_THINKING", "false").strip().lower() == "true",
        )


class LLMAdapter:
    def __init__(self, settings: LLMSettings) -> None:
        self._settings = settings

    def complete(self, prompt: str, *, system: str | None = None, max_tokens: int = 900) -> str | None:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        kwargs: dict = {}
        # api_base only makes sense for self-hosted/Ollama-style endpoints —
        # passing it to a hosted-provider model string would be wrong.
        if self._settings.model_name.startswith("ollama/"):
            if self._settings.api_base:
                kwargs["api_base"] = self._settings.api_base
            # Reasoning models (Qwen3, etc.) spend most of their token budget
            # on an internal "thinking" trace before the real answer — with a
            # capped max_tokens that can exhaust the budget before any actual
            # content is produced, silently returning empty output. Ollama's
            # `think` toggle skips that trace entirely: ~5x faster and content
            # arrives directly. LLM_THINKING=true opts back into it.
            kwargs["think"] = self._settings.thinking

        try:
            response = litellm.completion(
                model=self._settings.model_name,
                messages=messages,
                timeout=self._settings.timeout_seconds,
                max_tokens=max_tokens,
                **kwargs,
            )
            content = response.choices[0].message.content
            return content.strip() if content else None
        except Exception:  # noqa: BLE001 — AI enhancement is always optional
            logger.warning(
                "LLM completion failed (model=%s) — continuing without AI enhancement",
                self._settings.model_name,
                exc_info=True,
            )
            return None


def get_default_adapter() -> LLMAdapter | None:
    settings = LLMSettings.from_env()
    if settings is None:
        return None
    return LLMAdapter(settings)
