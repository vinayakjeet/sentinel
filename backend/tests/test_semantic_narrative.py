"""Narrative construction is what similarity actually compares, so it gets its own tests.

These run without a database or the embedding model — importing app.semantic.narrative must stay
free of both, which is itself part of what is asserted here.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.semantic.narrative import build_narrative, narrative_metadata

RING_SIGNALS = {
    "component_size": 12,
    "distinct_names_per_device": 3,
    "known_fraud_2hop": 2,
    "component_velocity_24h": 5,
}
REASONS = [
    {"feature": "prev_address_months_count", "reason": "Little recorded history at the previous address."},
    {"feature": "device_distinct_emails_8w", "reason": "Several different email addresses have recently been used from this device."},
]


def test_narrative_mentions_band_reasons_and_linkage():
    text = build_narrative(band="REVIEW", decision="MANUAL_REVIEW", reason_codes=REASONS,
                           graph_signals=RING_SIGNALS, graph_uplift=0.25)
    assert "REVIEW" in text
    assert "previous address" in text
    assert "11 other applications" in text          # component_size 12 -> 11 others
    assert "2 confirmed fraud cases" in text


def test_narrative_carries_no_personal_data():
    """Embeddings are queried by similarity and shown to other analysts, so no PII goes in.

    Identifiers are the entity graph's job; leaking them into a vector store would be a quiet
    data-handling failure that nothing else in the system would catch.
    """
    text = build_narrative(
        band="DECLINE", decision="DECLINED",
        reason_codes=REASONS + [{"feature": "email_is_free", "reason": "The application used a free email provider rather than a personal or work domain."}],
        graph_signals=RING_SIGNALS, graph_uplift=0.15,
    )
    for leaked in ("@", "+91", "DEV-", "10.", "Mumbai"):
        assert leaked not in text, f"narrative leaked {leaked!r}: {text}"


def test_narrative_handles_an_empty_case():
    text = build_narrative(band="APPROVE", decision="APPROVED", reason_codes=[], graph_signals={})
    assert "APPROVE" in text
    assert "no individual risk drivers" in text
    assert "no linked applications" in text


def test_narrative_is_stable_for_the_same_input():
    """Changing the wording invalidates every stored embedding, so drift must be deliberate."""
    a = build_narrative(band="REVIEW", reason_codes=REASONS, graph_signals=RING_SIGNALS)
    b = build_narrative(band="REVIEW", reason_codes=REASONS, graph_signals=RING_SIGNALS)
    assert a == b


def test_narrative_caps_reasons_at_four():
    many = [{"reason": f"Reason number {i} about the application."} for i in range(10)]
    text = build_narrative(band="REVIEW", reason_codes=many, graph_signals={})
    assert "Reason number 3" in text
    assert "Reason number 4" not in text


def test_metadata_shape():
    meta = narrative_metadata(band="REVIEW", reason_codes=REASONS, graph_signals=RING_SIGNALS)
    assert meta["band"] == "REVIEW"
    assert len(meta["top_reasons"]) == 2
    assert meta["graph_signals"]["component_size"] == 12
    assert meta["narrative_version"] == 1


@pytest.mark.parametrize("signals,expected", [
    ({"component_size": 1}, "no linked applications found"),
    ({"component_size": 3}, "linked to 2 other applications"),
    ({"known_fraud_2hop": 1}, "1 confirmed fraud cases within two hops"),
])
def test_graph_phrases(signals, expected):
    assert expected in build_narrative(band="REVIEW", reason_codes=[], graph_signals=signals)
