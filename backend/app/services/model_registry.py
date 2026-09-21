"""Loads Lane B's artifacts (DESIGN §4) once at startup and scores applications with them.

Artifacts contract (ml/artifacts/): model_v1.pkl, iforest_v1.pkl, features.json, blend.json, reason_codes.yaml
(+ preprocess_v1.pkl, consumed by ml.featurize). Feature engineering is Lane B's `ml.featurize.build_features`,
the same code path used in training, so there is no train/serve skew.
"""

import importlib
import json
import logging
import warnings
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
import yaml

from app.schemas.application import ApplicationEvent
from app.schemas.decision import ReasonCode
from app.services.fast_iforest import FastIsolationForest
from app.services.scoring import ModelScore

logger = logging.getLogger(__name__)

# shap 0.51 warns on every LightGBM binary explain call about its output format (handled in _contributions).
warnings.filterwarnings("ignore", message="LightGBM binary classifier with TreeExplainer", category=UserWarning)

Featurizer = Callable[[dict], pd.DataFrame]
TOP_REASONS = 4
_FALLBACK_REASON = {"reason": "Other application characteristics", "ecoa_category": "Other"}


@dataclass(frozen=True)
class ModelArtifacts:
    version: str
    model: Any  # lightgbm.LGBMClassifier or lightgbm.Booster
    iforest: Any
    if_min: float
    if_max: float
    if_features: list[str] | None
    features: list[str]
    categorical: list[str]
    w_supervised: float
    w_anomaly: float
    reason_codes: dict[str, dict[str, str]]


def load_artifacts(artifacts_dir: str | Path, version: str = "v1") -> ModelArtifacts:
    # Pickle (joblib) can execute code on load. Accepted here because the .pkl format is the DESIGN §4 contract and
    # these files are our own training outputs from the repo, mounted read-only; never user-supplied or downloaded.
    d = Path(artifacts_dir)
    feats = json.loads((d / "features.json").read_text(encoding="utf-8"))
    if isinstance(feats, list):  # tolerate a bare ordered list
        feats = {"features": feats, "categorical": []}
    blend = json.loads((d / "blend.json").read_text(encoding="utf-8"))
    iforest = joblib.load(d / f"iforest_{version}.pkl")
    reason_codes = yaml.safe_load((d / "reason_codes.yaml").read_text(encoding="utf-8")) or {}
    missing = [f for f in feats["features"] if f not in reason_codes]
    if missing:
        logger.warning("reason_codes.yaml lacks features; generic reason used", extra={"features": missing})
    return ModelArtifacts(
        version=version,
        model=joblib.load(d / f"model_{version}.pkl"),
        iforest=iforest["model"],
        if_min=float(iforest["min"]),
        if_max=float(iforest["max"]),
        if_features=iforest.get("features"),
        features=list(feats["features"]),
        categorical=list(feats.get("categorical", [])),
        w_supervised=float(blend["w_supervised"]),
        w_anomaly=float(blend["w_anomaly"]),
        reason_codes=reason_codes,
    )


def import_featurizer(module: str = "ml.featurize") -> Featurizer:
    return importlib.import_module(module).build_features


class ModelScoringService:
    """p = w_sup * LightGBM proba + w_anom * normalised IsolationForest anomaly; top-4 SHAP reasons."""

    def __init__(self, artifacts: ModelArtifacts, featurize: Featurizer) -> None:
        self.art = artifacts
        self.featurize = featurize
        self.model_version = f"lgbm-if-{artifacts.version}"
        self._booster = getattr(artifacts.model, "booster_", artifacts.model)
        self._explainer = self._make_explainer()
        self._if_columns = list(getattr(artifacts.iforest, "feature_names_in_", []))
        self._fast_if = self._make_fast_iforest()

    def _make_fast_iforest(self) -> FastIsolationForest | None:
        try:
            fast = FastIsolationForest(self.art.iforest)
            if fast.verified_against(self.art.iforest, self.art.iforest.n_features_in_):
                logger.info("fast IsolationForest path verified against sklearn")
                return fast
            logger.warning("fast IsolationForest path disagrees with sklearn; using sklearn")
        except Exception:
            logger.warning("fast IsolationForest path unavailable; using sklearn", exc_info=True)
        return None

    def _make_explainer(self):
        try:
            import shap

            return shap.TreeExplainer(self._booster)
        except Exception:
            logger.warning("shap.TreeExplainer unavailable; using LightGBM pred_contrib (same TreeSHAP values)",
                           exc_info=True)
            return None

    def frame(self, event: ApplicationEvent) -> pd.DataFrame:
        X = self.featurize(event.features())
        return X[self.art.features]

    def score(self, event: ApplicationEvent) -> ModelScore:
        X = self.frame(event)
        p_sup = self._p_supervised(X)
        a_norm = self._anomaly_norm(X)
        p = self.art.w_supervised * p_sup + self.art.w_anomaly * a_norm
        return ModelScore(p_model=float(np.clip(p, 0.0, 1.0)), reason_codes=self.reasons(X))

    def _p_supervised(self, X: pd.DataFrame) -> float:
        if hasattr(self.art.model, "predict_proba"):
            return float(self.art.model.predict_proba(X)[0, 1])
        return float(self._booster.predict(X)[0])

    def _anomaly_norm(self, X: pd.DataFrame) -> float:
        Xi = X[self.art.if_features] if self.art.if_features else X
        cat_cols = [c for c in Xi.columns if isinstance(Xi[c].dtype, pd.CategoricalDtype)]
        if cat_cols:
            Xi = Xi.assign(**{c: Xi[c].cat.codes for c in cat_cols})
        if self._fast_if is not None:
            row = (Xi[self._if_columns] if self._if_columns else Xi).to_numpy(dtype=np.float64)[0]
            raw = -self._fast_if.score_samples_row(row)  # higher = more anomalous
        else:
            raw = -float(self.art.iforest.score_samples(Xi)[0])
        span = self.art.if_max - self.art.if_min
        return float(np.clip((raw - self.art.if_min) / span, 0.0, 1.0)) if span > 0 else 0.0

    def _contributions(self, X: pd.DataFrame) -> np.ndarray:
        if self._explainer is not None:
            sv = self._explainer.shap_values(X)
            if isinstance(sv, list):  # older shap: [class0, class1]
                sv = sv[1]
            sv = np.asarray(sv)
            if sv.ndim == 3:  # (rows, features, classes)
                sv = sv[..., 1]
            return sv[0]
        return np.asarray(self._booster.predict(X, pred_contrib=True))[0, :-1]  # last column = bias

    def reasons(self, X: pd.DataFrame) -> list[ReasonCode]:
        contrib = self._contributions(X)
        order = np.argsort(-contrib)
        out: list[ReasonCode] = []
        for i in order[:TOP_REASONS]:
            if contrib[i] <= 0:
                break
            feature = self.art.features[i]
            meta = self.art.reason_codes.get(feature, _FALLBACK_REASON)
            out.append(
                ReasonCode(
                    feature=feature,
                    reason=meta["reason"],
                    ecoa_category=meta["ecoa_category"],
                    contribution=round(float(contrib[i]), 6),
                )
            )
        return out
