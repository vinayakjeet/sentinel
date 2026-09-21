"""Every model feature must have applicant-facing text behind it.

DESIGN §5 requires the top-4 SHAP contributors on a decision to be rendered as Reg B reasons.
If a feature has no mapping, the API would either crash or — far worse — quietly return a
decision with fewer than four reasons on a declined application. These tests make that a build
failure instead.
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from ml.featurize import FEATURE_ORDER  # noqa: E402
from ml.reason_codes import ECOA_CATEGORIES, REASON_CODES, validate  # noqa: E402

ARTIFACT_DIR = REPO / "ml" / "artifacts"


def test_every_feature_has_a_reason_code():
    missing = [f for f in FEATURE_ORDER if f not in REASON_CODES]
    assert not missing, f"features with no applicant-facing reason: {missing}"


def test_no_reason_codes_for_features_that_do_not_exist():
    """An orphan mapping usually means a feature was renamed and the text was left behind."""
    orphans = [f for f in REASON_CODES if f not in set(FEATURE_ORDER)]
    assert not orphans, f"reason codes for features not in the model: {orphans}"


def test_every_reason_has_text_and_a_known_ecoa_category():
    for feature, entry in REASON_CODES.items():
        assert entry.get("reason", "").strip(), f"{feature} has empty reason text"
        assert entry.get("ecoa_category") in ECOA_CATEGORIES, (
            f"{feature} has off-vocabulary ECOA category {entry.get('ecoa_category')!r}"
        )


def test_reason_text_is_applicant_facing():
    """The text goes in an adverse action notice, so it must not leak model mechanics."""
    for feature, entry in REASON_CODES.items():
        reason = entry["reason"]
        assert "_" not in reason, f"{feature}: reason text contains a raw column name: {reason!r}"
        assert reason[0].isupper(), f"{feature}: reason should read as a sentence: {reason!r}"
        assert reason.endswith("."), f"{feature}: reason should end with a full stop: {reason!r}"
        assert len(reason.split()) >= 5, f"{feature}: reason is too terse to be meaningful: {reason!r}"
        assert "SHAP" not in reason and "model" not in reason.lower(), (
            f"{feature}: reason describes the model rather than the applicant: {reason!r}"
        )


def test_protected_attributes_never_appear_as_features_or_reasons():
    """CLAUDE.md invariant 5, enforced at the explainability layer too.

    A protected attribute must never be a feature, and therefore must never be citable as a
    reason for an adverse action.
    """
    protected = {"customer_age", "employment_status", "income"}
    assert not (protected & set(FEATURE_ORDER)), "a protected attribute is a model feature"
    assert not (protected & set(REASON_CODES)), "a protected attribute has a reason code"


def test_validate_rejects_a_missing_mapping():
    """The guard must actually fire — a test that can never fail protects nothing."""
    with pytest.raises(ValueError, match="no reason code mapping"):
        validate(list(FEATURE_ORDER) + ["a_feature_with_no_mapping"])


def test_validate_rejects_an_off_vocabulary_category(monkeypatch):
    patched = {k: dict(v) for k, v in REASON_CODES.items()}
    patched["credit_risk_score"]["ecoa_category"] = "Vibes"
    monkeypatch.setattr("ml.reason_codes.REASON_CODES", patched)
    with pytest.raises(ValueError, match="off-vocabulary"):
        validate(FEATURE_ORDER)


@pytest.mark.skipif(
    not (ARTIFACT_DIR / "reason_codes.yaml").exists(), reason="run ml/train.py first"
)
def test_published_yaml_matches_the_source_module():
    """ml/artifacts/reason_codes.yaml is what Lane A actually reads; it must not drift."""
    published = yaml.safe_load(io.open(ARTIFACT_DIR / "reason_codes.yaml", encoding="utf-8"))
    assert published == REASON_CODES, (
        "ml/artifacts/reason_codes.yaml is stale — re-run ml/train.py after editing ml/reason_codes.py"
    )


@pytest.mark.skipif(
    not (ARTIFACT_DIR / "features.json").exists(), reason="run ml/train.py first"
)
def test_published_features_match_the_published_reason_codes():
    features = json.load(io.open(ARTIFACT_DIR / "features.json", encoding="utf-8"))["feature_order"]
    published = yaml.safe_load(io.open(ARTIFACT_DIR / "reason_codes.yaml", encoding="utf-8"))
    assert set(features) == set(published), "artifacts disagree about the feature set"
