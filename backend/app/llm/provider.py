"""LLMProvider interface plus a Groq implementation and a Bedrock stub (DESIGN §9).

Groq is called over plain httpx rather than the vendor SDK: httpx is already a backend dependency,
the endpoint is OpenAI-shaped, and it keeps the swap to Bedrock a matter of implementing one
method instead of unpicking an SDK's abstractions.

Every provider raises LLMUnavailable on any failure — timeout, transport error, bad status,
unparseable body. The service layer treats that single exception as "fall back to the templated
answer", so a provider outage degrades the copilot instead of breaking the endpoint.
"""

from __future__ import annotations

import json
import logging
from typing import Protocol, runtime_checkable

import httpx

from app.llm.config import LLMSettings, get_llm_settings

logger = logging.getLogger(__name__)


class LLMUnavailable(RuntimeError):
    """The provider could not produce an answer. Always recoverable via the fallback path."""


@runtime_checkable
class LLMProvider(Protocol):
    name: str

    def complete(self, *, system: str, user: str) -> str:
        """Return the raw completion text, or raise LLMUnavailable."""


class GroqProvider:
    """Groq chat completions. Model comes from GROQ_MODEL (see app/llm/config.py)."""

    name = "groq"

    def __init__(self, settings: LLMSettings | None = None) -> None:
        self.settings = settings or get_llm_settings()
        if not self.settings.groq_api_key:
            raise LLMUnavailable("GROQ_API_KEY is not configured")

    def complete(self, *, system: str, user: str) -> str:
        payload = {
            "model": self.settings.groq_model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": self.settings.llm_temperature,
            "max_tokens": self.settings.llm_max_tokens,
            "response_format": {"type": "json_object"},
        }
        headers = {
            "Authorization": f"Bearer {self.settings.groq_api_key.get_secret_value()}",
            "Content-Type": "application/json",
        }
        try:
            response = httpx.post(
                f"{self.settings.groq_base_url}/chat/completions",
                json=payload,
                headers=headers,
                timeout=self.settings.llm_timeout_seconds,
            )
        except httpx.HTTPError as exc:
            raise LLMUnavailable(f"groq transport error: {exc}") from exc

        if response.status_code != 200:
            # Never log the body verbatim — it can echo the prompt back. 404 is called out
            # separately because it almost always means the configured model has been retired,
            # which otherwise looks identical to an outage and quietly degrades to fallbacks.
            if response.status_code == 404:
                raise LLMUnavailable(
                    f"groq has no model {self.settings.groq_model!r} (HTTP 404) - "
                    "check GROQ_MODEL against GET /v1/models"
                )
            raise LLMUnavailable(f"groq returned HTTP {response.status_code}")

        try:
            content = response.json()["choices"][0]["message"]["content"]
        except (KeyError, IndexError, ValueError, json.JSONDecodeError) as exc:
            raise LLMUnavailable(f"groq returned an unparseable body: {type(exc).__name__}") from exc

        if not content or not content.strip():
            raise LLMUnavailable("groq returned an empty completion")
        return content


class BedrockProvider:
    """Amazon Bedrock — interface stub (DESIGN §9, §14 puts cloud deployment out of scope).

    Deliberately not a fake that returns plausible text: a stub that answers would make the
    fallback path untestable and could ship a demo that looks like it is calling a model when it
    is not. It raises, which is the honest behaviour and exercises the fallback.
    """

    name = "bedrock"

    def __init__(self, settings: LLMSettings | None = None) -> None:
        self.settings = settings or get_llm_settings()

    def complete(self, *, system: str, user: str) -> str:
        raise LLMUnavailable(
            "Bedrock provider is a stub; set LLM_PROVIDER=groq with a GROQ_API_KEY to use a live model"
        )


class NullProvider:
    """Always unavailable. Used to force the templated path in tests and offline demos."""

    name = "null"

    def complete(self, *, system: str, user: str) -> str:
        raise LLMUnavailable("null provider: no LLM configured")


def build_provider(settings: LLMSettings | None = None) -> LLMProvider:
    """Select the provider from config. Never raises: an unusable provider becomes NullProvider,
    so the endpoint still answers from reason codes."""
    settings = settings or get_llm_settings()
    choice = (settings.llm_provider or "").strip().lower()

    if choice == "groq":
        try:
            return GroqProvider(settings)
        except LLMUnavailable as exc:
            logger.warning("groq provider unavailable, using templated answers: %s", exc)
            return NullProvider()
    if choice == "bedrock":
        return BedrockProvider(settings)
    if choice in {"", "null", "none", "off"}:
        return NullProvider()

    logger.warning("unknown LLM_PROVIDER %r, using templated answers", settings.llm_provider)
    return NullProvider()
