"""Turn a persisted decision into the short case narrative that gets embedded (DESIGN §8).

The narrative is what similarity is computed over, so its content decides what "similar" means.
It deliberately includes band, the reason codes, and the graph signals — an analyst asking "have I
seen this before?" means "same kind of risk, same kind of linkage", not "same numbers".

Two things are deliberately excluded:

* the raw score, so that two cases are not called similar merely for scoring 701 and 703;
* any applicant identifier (name, email, phone, address, IP, device). Those are the keys the
  entity graph already joins on, and putting personal data into an embedding — which is then
  queried by similarity and shown to other analysts — is exactly the kind of quiet data leak
  responsible handling is meant to prevent.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

MAX_REASONS = 4


def _reason_texts(reason_codes: Iterable[Mapping[str, Any]] | None) -> list[str]:
    out: list[str] = []
    for entry in reason_codes or []:
        if not isinstance(entry, Mapping):
            continue
        text = entry.get("reason") or entry.get("feature")
        if text:
            out.append(str(text).rstrip("."))
    return out[:MAX_REASONS]


def _graph_phrase(signals: Mapping[str, Any] | None) -> str:
    if not signals:
        return "no linked applications found"

    parts: list[str] = []
    size = signals.get("component_size")
    if isinstance(size, (int, float)) and size > 1:
        parts.append(f"linked to {int(size) - 1} other applications")
    names = signals.get("distinct_names_per_device")
    if isinstance(names, (int, float)) and names > 1:
        parts.append(f"{int(names)} different names seen on the same device")
    known = signals.get("known_fraud_2hop")
    if isinstance(known, (int, float)) and known > 0:
        parts.append(f"{int(known)} confirmed fraud cases within two hops")
    velocity = signals.get("component_velocity_24h")
    if isinstance(velocity, (int, float)) and velocity > 1:
        parts.append(f"{int(velocity)} applications from this cluster in 24 hours")

    return "; ".join(parts) if parts else "no linked applications found"


def build_narrative(
    *,
    band: str,
    decision: str | None = None,
    reason_codes: Iterable[Mapping[str, Any]] | None = None,
    graph_signals: Mapping[str, Any] | None = None,
    graph_uplift: float | None = None,
) -> str:
    """Compose the case narrative. Stable wording matters more than elegance here: changing it
    changes every embedding, so a backfill is required if this function's output changes."""
    reasons = _reason_texts(reason_codes)
    reason_phrase = "; ".join(reasons) if reasons else "no individual risk drivers stood out"

    sentences = [
        f"Application placed in the {band} band" + (f", outcome {decision.lower().replace('_', ' ')}" if decision else "") + ".",
        f"Main risk drivers: {reason_phrase}.",
        f"Entity linkage: {_graph_phrase(graph_signals)}.",
    ]
    if graph_uplift:
        sentences.append("The score was raised because of its connections to other applications.")
    return " ".join(sentences)


def narrative_metadata(
    *,
    band: str,
    reason_codes: Iterable[Mapping[str, Any]] | None = None,
    graph_signals: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """The jsonb `metadata` column: enough to explain a match without re-reading the decision."""
    return {
        "band": band,
        "top_reasons": _reason_texts(reason_codes),
        "graph_signals": dict(graph_signals or {}),
        "narrative_version": 1,
    }
