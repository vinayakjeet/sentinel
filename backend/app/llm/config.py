"""LLM configuration (invariant 3: pydantic-settings from env, no secrets in code).

A settings class of its own rather than fields on app.core.config.Settings, because core/config.py
belongs to Lane A. Same .env file, same casing rules, so LLM_PROVIDER / GROQ_API_KEY / GROQ_MODEL
are read exactly as .env.example documents them.
"""

from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class LLMSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    llm_provider: str = "groq"
    groq_api_key: SecretStr | None = None
    # CLAUDE.md names llama-3.3-70b-versatile, but that model has been decommissioned on Groq:
    # GET /models does not list it and every completion returns HTTP 404, which silently sent the
    # copilot down the fallback path. Default changed to a model the endpoint actually serves.
    # Override with GROQ_MODEL if the account has something better.
    groq_model: str = "openai/gpt-oss-120b"
    groq_base_url: str = "https://api.groq.com/openai/v1"

    llm_timeout_seconds: float = 12.0
    # The reply is capped at ~120 words by the prompt, but openai/gpt-oss-120b is a reasoning model and its hidden
    # reasoning tokens count against this budget. At 500, about one call in eight ran out before finishing the JSON
    # and Groq answered HTTP 400 json_validate_failed (measured), which silently became the templated fallback.
    llm_max_tokens: int = 2000
    llm_temperature: float = 0.1

    # Guardrails
    llm_max_question_chars: int = 1000
    llm_similar_cases: int = 3

    @property
    def configured(self) -> bool:
        """True when the selected provider can actually be called."""
        if self.llm_provider == "groq":
            return self.groq_api_key is not None and bool(self.groq_api_key.get_secret_value())
        return self.llm_provider in {"bedrock", "null"}


@lru_cache
def get_llm_settings() -> LLMSettings:
    return LLMSettings()
