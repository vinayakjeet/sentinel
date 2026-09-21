"""Input and output guardrails for the copilot (DESIGN §9).

Input:  length cap -> prompt-injection scan -> PII redaction.
Output: structured validation, and citations restricted to reason codes that are actually on the
        decision being discussed.

The redaction order matters: injection is scanned on the raw text (so an attack cannot hide behind
something that redaction would rewrite), and redaction runs afterwards so nothing personal reaches
the provider.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------------------------
# prompt injection
# --------------------------------------------------------------------------------------------
# Patterns aimed at the two things that would actually matter here: making the model disregard its
# instructions, and making it claim an authority it does not have (changing a decision).
INJECTION_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"ignore\s+(?:all\s+|any\s+|the\s+)?(?:previous|prior|above|earlier)\s+instructions", "instruction override"),
    (r"disregard\s+(?:all\s+|any\s+|the\s+)?(?:previous|prior|above|earlier|your)\s+", "instruction override"),
    (r"forget\s+(?:everything|all|your)\s+(?:instructions|rules|prompt)", "instruction override"),
    (r"you\s+are\s+now\s+(?:a|an|the)\s+", "role reassignment"),
    (r"act\s+as\s+(?:if\s+you\s+are\s+)?(?:a|an|the)\s+(?:admin|administrator|developer|root)", "role reassignment"),
    (r"(?:system|developer)\s*(?:prompt|message)\s*[:=]", "prompt injection"),
    (r"<\s*\|?\s*(?:im_start|im_end|system|endoftext)\s*\|?\s*>", "control token injection"),
    (r"\b(?:approve|decline|change|set|update|override|modify)\s+(?:this\s+|the\s+)?"
     r"(?:application|decision|score|band|case)\b", "attempted decision mutation"),
    (r"reveal\s+(?:your\s+)?(?:system\s+)?(?:prompt|instructions)", "prompt exfiltration"),
    (r"\b(?:drop|delete|truncate|update|insert)\s+(?:table|into|from)\b", "sql injection"),
)

_COMPILED_INJECTION = tuple((re.compile(p, re.IGNORECASE), label) for p, label in INJECTION_PATTERNS)

# --------------------------------------------------------------------------------------------
# PII redaction — regex fallback, used when Presidio is unavailable
# --------------------------------------------------------------------------------------------
PII_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "<EMAIL>"),
    (re.compile(r"\b(?:\+?\d{1,3}[\s-]?)?\(?\d{3,5}\)?[\s-]?\d{3}[\s-]?\d{4,6}\b"), "<PHONE>"),
    (re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"), "<IP>"),
    (re.compile(r"\b(?:\d[ -]*?){13,19}\b"), "<CARD>"),
    (re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b"), "<NATIONAL_ID>"),   # PAN-shaped
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "<SSN>"),
)


@dataclass
class GuardrailResult:
    """Outcome of the input guardrails."""

    allowed: bool
    text: str
    reasons: list[str] = field(default_factory=list)
    redactions: list[str] = field(default_factory=list)

    @property
    def blocked(self) -> bool:
        return not self.allowed


def scan_for_injection(text: str) -> list[str]:
    """Return the labels of every injection pattern the text matches."""
    return [label for pattern, label in _COMPILED_INJECTION if pattern.search(text)]


def _redact_with_presidio(text: str) -> tuple[str, list[str]] | None:
    """Presidio if it is installed, else None so the caller falls back to regex.

    Presidio pulls spaCy and a language model, which is a lot of image for a demo, so it is
    genuinely optional — the regex path below is the one that runs by default.
    """
    try:
        from presidio_analyzer import AnalyzerEngine
        from presidio_anonymizer import AnonymizerEngine
    except ImportError:
        return None

    try:
        analyzer = AnalyzerEngine()
        results = analyzer.analyze(text=text, language="en")
        if not results:
            return text, []
        anonymized = AnonymizerEngine().anonymize(text=text, analyzer_results=results)
        return anonymized.text, sorted({r.entity_type for r in results})
    except Exception:  # pragma: no cover - defensive; never fail a request over redaction
        logger.exception("presidio redaction failed, falling back to regex")
        return None


def redact_pii(text: str) -> tuple[str, list[str]]:
    """Redact personal data before anything leaves the process. Returns (text, entity labels)."""
    via_presidio = _redact_with_presidio(text)
    if via_presidio is not None:
        return via_presidio

    found: list[str] = []
    out = text
    for pattern, placeholder in PII_PATTERNS:
        out, n = pattern.subn(placeholder, out)
        if n:
            found.append(placeholder.strip("<>"))
    return out, found


def check_input(question: str, *, max_chars: int) -> GuardrailResult:
    """Length cap, then injection scan on the raw text, then redaction."""
    stripped = question.strip()

    if not stripped:
        return GuardrailResult(allowed=False, text="", reasons=["empty question"])

    if len(stripped) > max_chars:
        return GuardrailResult(
            allowed=False,
            text=stripped[:max_chars],
            reasons=[f"question exceeds {max_chars} characters"],
        )

    hits = scan_for_injection(stripped)
    if hits:
        logger.warning("copilot input blocked by injection scan", extra={"patterns": hits})
        return GuardrailResult(allowed=False, text=stripped, reasons=sorted(set(hits)))

    redacted, entities = redact_pii(stripped)
    return GuardrailResult(allowed=True, text=redacted, redactions=entities)


# --------------------------------------------------------------------------------------------
# output
# --------------------------------------------------------------------------------------------
def filter_citations(cited: list[str] | None, allowed: set[str]) -> list[str]:
    """Keep only citations that correspond to reason codes actually on this decision."""
    seen: set[str] = set()
    out: list[str] = []
    for c in cited or []:
        key = str(c).strip()
        if key in allowed and key not in seen:
            seen.add(key)
            out.append(key)
    return out


def mentions_foreign_reason(answer: str, allowed: set[str], universe: set[str]) -> bool:
    """True if the answer names a reason-code feature that is NOT on this decision.

    This is the check that stops the model explaining a decline with a factor that played no part
    in it — the failure mode that would make an adverse-action notice wrong.
    """
    for feature in universe - allowed:
        if re.search(rf"\b{re.escape(feature)}\b", answer, re.IGNORECASE):
            return True
    return False
