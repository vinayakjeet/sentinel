"""Scoring path against tiny synthetic artifacts written in the DESIGN §4 format (real ones come from Lane B)."""

import json

import joblib
import lightgbm as lgb
import numpy as np
import pandas as pd
import pytest
import yaml
from sklearn.ensemble import IsolationForest

from app.schemas.application import ApplicationEvent
from app.services.model_registry import ModelScoringService, load_artifacts

FEATURES = ["velocity_6h", "credit_risk_score", "name_email_similarity", "payment_type", "bank_months_count_missing"]
PAYMENT_TYPES = ["AA", "AB", "AC", "AD", "AE"]


def fake_featurize(raw: dict) -> pd.DataFrame:
    row = {
        "velocity_6h": raw["velocity_6h"],
        "credit_risk_score": raw["credit_risk_score"],
        "name_email_similarity": raw["name_email_similarity"],
        "payment_type": raw["payment_type"],
        "bank_months_count_missing": int(raw["bank_months_count"] == -1),
    }
    df = pd.DataFrame([row])
    df["payment_type"] = pd.Categorical(df["payment_type"], categories=PAYMENT_TYPES)
    return df


@pytest.fixture(scope="module")
def artifacts_dir(tmp_path_factory):
    rng = np.random.default_rng(0)
    n = 2000
    X = pd.DataFrame(
        {
            "velocity_6h": rng.uniform(0, 15000, n),
            "credit_risk_score": rng.integers(-100, 350, n),
            "name_email_similarity": rng.uniform(0, 1, n),
            "payment_type": pd.Categorical(rng.choice(PAYMENT_TYPES, n), categories=PAYMENT_TYPES),
            "bank_months_count_missing": rng.integers(0, 2, n),
        }
    )
    logit = 0.0004 * X["velocity_6h"] - 3 * X["name_email_similarity"] + 0.01 * X["credit_risk_score"] - 2
    y = (rng.uniform(0, 1, n) < 1 / (1 + np.exp(-logit))).astype(int)
    model = lgb.LGBMClassifier(n_estimators=40, num_leaves=8, random_state=0, verbose=-1).fit(X, y)

    Xi = X.assign(payment_type=X["payment_type"].cat.codes)
    iforest = IsolationForest(n_estimators=50, random_state=0).fit(Xi[y == 0])
    raw = -iforest.score_samples(Xi[y == 0])

    d = tmp_path_factory.mktemp("artifacts")
    joblib.dump(model, d / "model_v1.pkl")
    joblib.dump({"model": iforest, "min": float(raw.min()), "max": float(raw.max())}, d / "iforest_v1.pkl")
    (d / "features.json").write_text(json.dumps({"features": FEATURES, "categorical": ["payment_type"]}))
    (d / "blend.json").write_text(json.dumps({"w_supervised": 0.75, "w_anomaly": 0.25}))
    (d / "reason_codes.yaml").write_text(
        yaml.safe_dump({f: {"reason": f"Reason for {f}", "ecoa_category": "Test category"} for f in FEATURES})
    )
    return d


@pytest.fixture(scope="module")
def scorer(artifacts_dir):
    return ModelScoringService(load_artifacts(artifacts_dir), fake_featurize)


@pytest.fixture
def event(payload) -> ApplicationEvent:
    payload.update(velocity_6h=14000.0, name_email_similarity=0.02, credit_risk_score=300)
    return ApplicationEvent.model_validate(payload)


def test_same_input_same_score_and_reasons(scorer, event):
    first, second = scorer.score(event), scorer.score(event)
    assert first == second
    assert 0.0 <= first.p_model <= 1.0


def test_top_reasons_positive_sorted_and_mapped(scorer, event):
    reasons = scorer.score(event).reason_codes
    assert 1 <= len(reasons) <= 4
    contribs = [r.contribution for r in reasons]
    assert all(c > 0 for c in contribs) and contribs == sorted(contribs, reverse=True)
    assert all(r.reason == f"Reason for {r.feature}" for r in reasons)


def test_shap_matches_lightgbm_pred_contrib(scorer, event):
    X = scorer.frame(event)
    exact = scorer._booster.predict(X, pred_contrib=True)[0, :-1]
    np.testing.assert_allclose(scorer._contributions(X), exact, rtol=1e-5, atol=1e-6)


def test_riskier_application_scores_higher(scorer, payload):
    safe = ApplicationEvent.model_validate(
        {**payload, "velocity_6h": 100.0, "name_email_similarity": 0.95, "credit_risk_score": -50}
    )
    risky = ApplicationEvent.model_validate(
        {**payload, "velocity_6h": 14500.0, "name_email_similarity": 0.01, "credit_risk_score": 340}
    )
    assert scorer.score(risky).p_model > scorer.score(safe).p_model


def test_fast_iforest_matches_sklearn(artifacts_dir):
    from app.services.fast_iforest import FastIsolationForest

    forest = joblib.load(artifacts_dir / "iforest_v1.pkl")["model"]
    fast = FastIsolationForest(forest)
    X = np.random.default_rng(3).normal(0, 1000, (300, forest.n_features_in_))
    np.testing.assert_allclose([fast.score_samples_row(r) for r in X], forest.score_samples(X), rtol=1e-12)


def test_scorer_uses_verified_fast_iforest(scorer):
    assert scorer._fast_if is not None
