"""Contract for POST /copilot/ask (implemented by Lane B in app/llm/, which imports these)."""

import uuid
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints


class CopilotAskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision_id: uuid.UUID
    question: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]


class CopilotAskResponse(BaseModel):
    answer: str
    cited_reasons: list[str] = Field(description="Feature keys of reason codes on this decision cited in the answer")
    blocked: bool = Field(description="True if guardrails refused the question")
    fallback_used: bool = Field(description="True if the LLM failed and a templated answer was returned")
