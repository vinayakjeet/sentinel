"""Copilot orchestration (DESIGN §9).

Flow: guardrails -> read-only context -> prompt -> provider -> output validation -> response.
Every branch that cannot produce a validated model answer falls back to a templated answer built
from the decision's own reason codes, so the endpoint always answers and never invents.
"""

from __future__ import annotations

import json
import logging
import uuid
from functools import lru_cache
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined
from pydantic import BaseModel, Field, ValidationError

from app.llm import tools
from app.llm.config import LLMSettings, get_llm_settings
from app.llm.guardrails import check_input, filter_citations, mentions_foreign_reason
from app.llm.provider import LLMProvider, LLMUnavailable, build_provider

logger = logging.getLogger(__name__)

PROMPT_DIR = Path(__file__).parent / "prompts"

BLOCKED_ANSWER = (
    "I can't answer that. I explain decisions that the scoring service has already made; I can't "
    "change a score or an outcome, and I can't act on instructions embedded in a question."
)
NOT_FOUND_ANSWER = "No decision with that id exists."


@lru_cache
def _env() -> Environment:
    return Environment(
        loader=FileSystemLoader(PROMPT_DIR),
        undefined=StrictUndefined,
        autoescape=False,          # prompts are plain text, not markup
        trim_blocks=True,
        lstrip_blocks=True,
    )


class LLMAnswer(BaseModel):
    """The structure the model is required to return. Anything else is a fallback."""

    answer: str = Field(min_length=1, max_length=4000)
    cited_reasons: list[str] = Field(default_factory=list)


class CopilotResult(BaseModel):
    answer: str
    cited_reasons: list[str]
    blocked: bool
    fallback_used: bool


def _reason_entries(decision: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for entry in decision.get("reason_codes") or []:
        if isinstance(entry, dict):
            out.append(
                {
                    "feature": str(entry.get("feature", "")),
                    "reason": str(entry.get("reason", "")),
                    "ecoa_category": entry.get("ecoa_category"),
                    "contribution": entry.get("contribution"),
                }
            )
    return out


@lru_cache
def _reason_universe() -> frozenset[str]:
    """Every feature that could ever be a reason code, from the published artifact.

    Used to detect an answer citing a factor that is not on *this* decision. Loaded from
    ml/artifacts/reason_codes.yaml; if unavailable, the check degrades to citation filtering only.
    """
    import os

    candidates = [
        Path(os.environ.get("ARTIFACTS_DIR", "")) / "reason_codes.yaml",
        Path(__file__).resolve().parents[3] / "ml" / "artifacts" / "reason_codes.yaml",
        Path("/srv/ml/artifacts/reason_codes.yaml"),
    ]
    for path in candidates:
        try:
            if path.is_file():
                import yaml

                data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
                return frozenset(str(k) for k in data)
        except Exception:  # pragma: no cover - never fail a request over this
            logger.warning("could not load reason code universe from %s", path)
    # Reaching here means the foreign-reason check below degrades to a no-op. Citation filtering
    # still holds, but a guardrail that quietly stops guarding is worse than one that is absent,
    # so say so loudly rather than let it fail open in silence.
    logger.error(
        "reason code universe unavailable (looked in %s); the foreign-reason guardrail is INACTIVE",
        [str(c) for c in candidates],
    )
    return frozenset()


def _render_fallback(decision: dict[str, Any], reasons: list[dict], graph: dict | None) -> str:
    return _env().get_template("fallback.j2").render(
        decision=decision, reasons=reasons, graph=graph
    ).strip()


def build_context(decision_id: uuid.UUID, settings: LLMSettings) -> dict[str, Any] | None:
    """Gather everything the copilot may see — all of it through the read-only tool registry."""
    decision = tools.call("get_decision", decision_id=decision_id)
    if decision is None:
        return None

    graph: dict[str, Any] | None = None
    similar: list[dict[str, Any]] = []
    try:
        graph = tools.call("get_entity_graph", application_id=decision["application_id"])
    except Exception:
        logger.warning("entity graph tool failed; continuing without linkage", exc_info=True)
    try:
        similar = tools.call("find_similar_cases", decision_id=decision_id, k=settings.llm_similar_cases)
    except Exception:
        logger.warning("similar cases tool failed; continuing without them", exc_info=True)

    return {"decision": decision, "graph": graph, "similar": similar}


def ask(
    decision_id: uuid.UUID,
    question: str,
    *,
    provider: LLMProvider | None = None,
    settings: LLMSettings | None = None,
) -> CopilotResult:
    settings = settings or get_llm_settings()

    guard = check_input(question, max_chars=settings.llm_max_question_chars)
    if guard.blocked:
        logger.info("copilot question blocked", extra={"reasons": guard.reasons})
        return CopilotResult(answer=BLOCKED_ANSWER, cited_reasons=[], blocked=True, fallback_used=False)

    context = build_context(decision_id, settings)
    if context is None:
        return CopilotResult(answer=NOT_FOUND_ANSWER, cited_reasons=[], blocked=False, fallback_used=False)

    decision = context["decision"]
    reasons = _reason_entries(decision)
    allowed = {r["feature"] for r in reasons if r["feature"]}
    fallback_answer = _render_fallback(decision, reasons, context["graph"])

    provider = provider or build_provider(settings)

    try:
        system = _env().get_template("system.j2").render()
        user = _env().get_template("context.j2").render(
            decision=decision, reasons=reasons, graph=context["graph"],
            similar=context["similar"], question=guard.text,
        )
        raw = provider.complete(system=system, user=user)
    except LLMUnavailable as exc:
        logger.warning("llm unavailable, using templated answer: %s", exc)
        return CopilotResult(
            answer=fallback_answer, cited_reasons=sorted(allowed), blocked=False, fallback_used=True
        )
    except Exception:
        logger.exception("llm call failed unexpectedly, using templated answer")
        return CopilotResult(
            answer=fallback_answer, cited_reasons=sorted(allowed), blocked=False, fallback_used=True
        )

    # --- output validation -------------------------------------------------------------------
    try:
        parsed = LLMAnswer.model_validate(json.loads(raw))
    except (json.JSONDecodeError, ValidationError, TypeError) as exc:
        logger.warning("llm returned an unusable payload (%s), using templated answer", type(exc).__name__)
        return CopilotResult(
            answer=fallback_answer, cited_reasons=sorted(allowed), blocked=False, fallback_used=True
        )

    if mentions_foreign_reason(parsed.answer, allowed, set(_reason_universe())):
        # The model explained the decision with a factor that played no part in it. That is the
        # failure mode that would make an adverse-action notice wrong, so we do not ship it.
        logger.warning("llm answer cited a factor absent from the decision; using templated answer")
        return CopilotResult(
            answer=fallback_answer, cited_reasons=sorted(allowed), blocked=False, fallback_used=True
        )

    return CopilotResult(
        answer=parsed.answer.strip(),
        cited_reasons=filter_citations(parsed.cited_reasons, allowed),
        blocked=False,
        fallback_used=False,
    )
