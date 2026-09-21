"""SENTINEL — model training and artifact export (DESIGN §3, §4, §12).

Trains the three scorers, evaluates them against a rules baseline on the held-out months, and
writes every artifact in the DESIGN §4 contract. Lane A's ModelRegistry reads these at startup;
the filenames are a contract and are never renamed.

    ml/artifacts/model_v1.pkl        LightGBM classifier
    ml/artifacts/model_v1.txt        same booster in LightGBM's native text format (version-proof fallback)
    ml/artifacts/iforest_v1.pkl      {"model", "min", "max"} — IsolationForest + train-fitted normaliser
    ml/artifacts/preprocess_v1.pkl   everything needed to go from a raw dict to the feature frame
    ml/artifacts/features.json       ordered feature names + categorical list
    ml/artifacts/blend.json          {"w_supervised": 0.75, "w_anomaly": 0.25}
    ml/artifacts/reason_codes.yaml   feature -> {reason, ecoa_category}
    ml/artifacts/metrics_v1.json     every metric, for every model, incl. the baseline

    docs/charts/pr_curve.png
    docs/charts/score_distribution_bands.png
    docs/charts/feature_importance.png

Run:  python ml/train.py
"""

from __future__ import annotations

import json
import pickle
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import lightgbm as lgb
import matplotlib
import numpy as np
import pandas as pd
import yaml

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from sklearn.ensemble import IsolationForest  # noqa: E402
from sklearn.metrics import (  # noqa: E402
    average_precision_score,
    precision_recall_curve,
    roc_auc_score,
    roc_curve,
)

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from ml.featurize import (  # noqa: E402
    CATEGORICAL_FEATURES,
    FEATURE_ORDER,
    build_feature_frame,
    build_features,
    feature_metadata,
)
from ml.reason_codes import REASON_CODES  # noqa: E402
from ml.reason_codes import validate as validate_reason_codes  # noqa: E402

PROC_DIR = REPO / "data" / "processed"
ARTIFACT_DIR = REPO / "ml" / "artifacts"
CHART_DIR = REPO / "docs" / "charts"

LABEL = "fraud_bool"
TIME_COL = "month"
FIT_MONTHS = (0, 1, 2, 3, 4)
VAL_MONTH = 5
MODEL_VERSION = "v1"
SEED = 20260921

W_SUPERVISED = 0.75
W_ANOMALY = 0.25

# DESIGN §3 bands, for the score-distribution chart and the fairness threshold.
BANDS = {"APPROVE": (0, 300), "STEP_UP": (300, 650), "REVIEW": (650, 850), "DECLINE": (850, 1001)}
DECLINE_THRESHOLD = 850

# IsolationForest on ~790k rows is slow and adds nothing over a large subsample.
IFOREST_FIT_ROWS = 200_000
IFOREST_TREES = 200
PICKLE_PROTOCOL = 4  # readable by any CPython >= 3.4, incl. Lane A's 3.11 container


def log(msg: str = "") -> None:
    print(msg, flush=True)


def section(title: str) -> None:
    log()
    log(title)
    log("-" * len(title))


# --------------------------------------------------------------------------------------------
# metrics
# --------------------------------------------------------------------------------------------
def precision_at_k(y_true: np.ndarray, scores: np.ndarray, k: int = 100) -> float:
    """Precision among the k highest-scoring applications — the analyst's daily queue."""
    k = min(k, len(scores))
    top = np.argpartition(-scores, k - 1)[:k]
    return float(y_true[top].mean())


def recall_at_fpr(y_true: np.ndarray, scores: np.ndarray, target_fpr: float = 0.01) -> float:
    """Recall at the operating point whose false-positive rate is closest to (but <=) target."""
    fpr, tpr, _ = roc_curve(y_true, scores)
    ok = fpr <= target_fpr
    return float(tpr[ok].max()) if ok.any() else 0.0


def evaluate(name: str, y_true: np.ndarray, scores: np.ndarray) -> dict:
    return {
        "model": name,
        "roc_auc": float(roc_auc_score(y_true, scores)),
        "pr_auc": float(average_precision_score(y_true, scores)),
        "precision_at_100": precision_at_k(y_true, scores, 100),
        "recall_at_1pct_fpr": recall_at_fpr(y_true, scores, 0.01),
    }


# --------------------------------------------------------------------------------------------
# rules baseline
# --------------------------------------------------------------------------------------------
def fit_rules_baseline(train: pd.DataFrame) -> dict:
    """Expert-style rules with thresholds taken from TRAIN quantiles only (no test leakage).

    This is the "what would a sensible analyst write without ML" comparator that DESIGN §12 asks
    for. Score is simply the fraction of rules triggered.
    """
    q = {
        "velocity_6h_hi": float(train["velocity_6h"].quantile(0.90)),
        "zip_count_4w_hi": float(train["zip_count_4w"].quantile(0.90)),
        "bank_branch_count_8w_hi": float(train["bank_branch_count_8w"].quantile(0.90)),
        "name_email_similarity_lo": float(train["name_email_similarity"].quantile(0.10)),
        "credit_risk_score_lo": float(train["credit_risk_score"].quantile(0.20)),
        "session_length_lo": float(train["session_length_in_minutes"].quantile(0.10)),
        "dob_emails_hi": float(train["date_of_birth_distinct_emails_4w"].quantile(0.90)),
    }
    return q


def apply_rules_baseline(df: pd.DataFrame, q: dict) -> np.ndarray:
    rules = [
        df["velocity_6h"] > q["velocity_6h_hi"],
        df["zip_count_4w"] > q["zip_count_4w_hi"],
        df["bank_branch_count_8w"] > q["bank_branch_count_8w_hi"],
        df["name_email_similarity"] < q["name_email_similarity_lo"],
        df["credit_risk_score"] < q["credit_risk_score_lo"],
        df["session_length_in_minutes"] < q["session_length_lo"],
        df["date_of_birth_distinct_emails_4w"] > q["dob_emails_hi"],
        df["phone_home_valid"] == 0,
        df["email_is_free"] == 1,
        df["has_other_cards"] == 0,
        df["prev_address_months_count"] == -1,
        df["foreign_request"] == 1,
    ]
    return np.mean([r.to_numpy().astype(float) for r in rules], axis=0)


# --------------------------------------------------------------------------------------------
# charts
# --------------------------------------------------------------------------------------------
PALETTE = {"baseline": "#8c8c8c", "lightgbm": "#2f6fb3", "iforest": "#c98b2e", "blend": "#2e7d5b"}


def chart_pr_curve(y_true: np.ndarray, score_sets: dict[str, np.ndarray], metrics: dict) -> Path:
    fig, ax = plt.subplots(figsize=(7.5, 5.5), dpi=140)
    for name, scores in score_sets.items():
        precision, recall, _ = precision_recall_curve(y_true, scores)
        ax.plot(recall, precision, label=f"{name}  (PR-AUC {metrics[name]['pr_auc']:.4f})",
                color=PALETTE[name], linewidth=1.8)
    base_rate = float(y_true.mean())
    ax.axhline(base_rate, color="#b0b0b0", linestyle=":", linewidth=1.2,
               label=f"prevalence ({base_rate * 100:.2f}%)")
    ax.set_xlabel("Recall")
    ax.set_ylabel("Precision")
    ax.set_title("Precision-recall on held-out months 6-7")
    ax.set_ylim(0, 1)
    ax.grid(alpha=0.25, linewidth=0.6)
    ax.legend(frameon=False, fontsize=9)
    fig.tight_layout()
    path = CHART_DIR / "pr_curve.png"
    fig.savefig(path)
    plt.close(fig)
    return path


def chart_score_distribution(y_true: np.ndarray, blend: np.ndarray) -> Path:
    scores = np.round(blend * 1000)
    fig, ax = plt.subplots(figsize=(8.5, 5.0), dpi=140)
    bins = np.linspace(0, 1000, 81)
    ax.hist(scores[y_true == 0], bins=bins, color="#2f6fb3", alpha=0.75, label="legitimate", log=True)
    ax.hist(scores[y_true == 1], bins=bins, color="#c1443a", alpha=0.8, label="fraud", log=True)
    for name, (lo, _hi) in BANDS.items():
        if lo > 0:
            ax.axvline(lo, color="#444444", linestyle="--", linewidth=1.0)
            ax.text(lo + 6, ax.get_ylim()[1] * 0.4, name, rotation=90, fontsize=8, color="#444444")
    ax.text(60, ax.get_ylim()[1] * 0.4, "APPROVE", rotation=90, fontsize=8, color="#444444")
    ax.set_xlabel("Blended score (0-1000)")
    ax.set_ylabel("Applications (log scale)")
    ax.set_title("Score distribution by outcome, with policy bands")
    ax.grid(alpha=0.2, linewidth=0.6)
    ax.legend(frameon=False, fontsize=9)
    fig.tight_layout()
    path = CHART_DIR / "score_distribution_bands.png"
    fig.savefig(path)
    plt.close(fig)
    return path


def chart_feature_importance(model: lgb.LGBMClassifier, top_n: int = 20) -> Path:
    gain = pd.Series(model.booster_.feature_importance("gain"), index=list(FEATURE_ORDER))
    gain = gain.sort_values(ascending=False).head(top_n).iloc[::-1]
    fig, ax = plt.subplots(figsize=(8.5, 7.0), dpi=140)
    ax.barh(gain.index, gain.to_numpy(), color="#2f6fb3")
    ax.set_xlabel("Total gain")
    ax.set_title(f"LightGBM feature importance (top {top_n} of {len(FEATURE_ORDER)})")
    ax.grid(alpha=0.2, axis="x", linewidth=0.6)
    fig.tight_layout()
    path = CHART_DIR / "feature_importance.png"
    fig.savefig(path)
    plt.close(fig)
    return path


# --------------------------------------------------------------------------------------------
def main() -> int:
    started = time.perf_counter()
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    CHART_DIR.mkdir(parents=True, exist_ok=True)

    log("=" * 78)
    log("SENTINEL - train (DESIGN sections 3, 4, 12)")
    log("=" * 78)

    train_raw = pd.read_parquet(PROC_DIR / "train.parquet")
    test_raw = pd.read_parquet(PROC_DIR / "test.parquet")

    section("1. Data")
    log(f"  train : {len(train_raw):>9,} rows  months {sorted(int(m) for m in train_raw[TIME_COL].unique())}"
        f"  fraud {train_raw[LABEL].mean() * 100:.3f}%")
    log(f"  test  : {len(test_raw):>9,} rows  months {sorted(int(m) for m in test_raw[TIME_COL].unique())}"
        f"  fraud {test_raw[LABEL].mean() * 100:.3f}%")

    fit_mask = train_raw[TIME_COL].isin(FIT_MONTHS)
    val_mask = train_raw[TIME_COL] == VAL_MONTH
    log(f"  fit   : months {list(FIT_MONTHS)} ({int(fit_mask.sum()):,} rows)")
    log(f"  val   : month  {VAL_MONTH} ({int(val_mask.sum()):,} rows) - early stopping only")

    section("2. Features")
    X_all = build_feature_frame(train_raw)
    X_test = build_feature_frame(test_raw)
    y_all = train_raw[LABEL].to_numpy()
    y_test = test_raw[LABEL].to_numpy()
    log(f"  {len(FEATURE_ORDER)} features "
        f"({len(FEATURE_ORDER) - len(CATEGORICAL_FEATURES)} numeric/flag + {len(CATEGORICAL_FEATURES)} categorical)")
    log(f"  excluded protected attributes: {feature_metadata()['excluded_protected_attributes']}")
    validate_reason_codes(FEATURE_ORDER)
    log(f"  reason code coverage: {len(REASON_CODES)}/{len(FEATURE_ORDER)} features - validated")

    X_fit, y_fit = X_all[fit_mask.to_numpy()], y_all[fit_mask.to_numpy()]
    X_val, y_val = X_all[val_mask.to_numpy()], y_all[val_mask.to_numpy()]

    section("3. LightGBM")
    scale_pos_weight = float((y_fit == 0).sum() / max(1, (y_fit == 1).sum()))
    log(f"  scale_pos_weight = {scale_pos_weight:.2f}")
    model = lgb.LGBMClassifier(
        objective="binary",
        # Disable LightGBM's default binary_logloss. With scale_pos_weight ~99 the logloss on an
        # unweighted validation month is best at iteration 1 and never improves, so leaving it on
        # makes early stopping fire immediately and hand back a single-tree model. Verified:
        # with the default metric left on, best_iteration_ = 1 and val PR-AUC 0.058; with it off,
        # best_iteration_ = 185 and val PR-AUC 0.172.
        metric="None",
        n_estimators=1500,
        learning_rate=0.05,
        num_leaves=63,
        min_child_samples=100,
        subsample=0.8,
        subsample_freq=1,
        colsample_bytree=0.8,
        reg_lambda=1.0,
        scale_pos_weight=scale_pos_weight,
        random_state=SEED,
        n_jobs=-1,
        verbose=-1,
    )
    # Custom eval metric, because LightGBM's built-in "average_precision" is scored as
    # lower-is-better by the early-stopping callback. Returning is_higher_better=True explicitly
    # is the only way to early-stop on PR-AUC, which is the metric that matters at a 1% base rate.
    def pr_auc_eval(y_true: np.ndarray, y_pred: np.ndarray) -> tuple[str, float, bool]:
        return "pr_auc", float(average_precision_score(y_true, y_pred)), True

    model.fit(
        X_fit, y_fit,
        eval_X=X_val, eval_y=y_val,
        eval_metric=pr_auc_eval,
        callbacks=[
            lgb.early_stopping(100, first_metric_only=True, verbose=False),
            lgb.log_evaluation(0),
        ],
    )
    val_pr_auc = float(model.best_score_["valid_0"]["pr_auc"])
    log(f"  best iteration: {model.best_iteration_} of {model.n_estimators} "
        f"(early stopped on month {VAL_MONTH}, patience 100)")
    log(f"  val PR-AUC: {val_pr_auc:.4f}")
    n_cat_used = sum(1 for f in CATEGORICAL_FEATURES if f in X_fit.columns and str(X_fit[f].dtype) == "category")
    log(f"  categoricals passed as pandas category dtype: {n_cat_used}/{len(CATEGORICAL_FEATURES)}")
    assert model.best_iteration_ > 10, (
        f"early stopping collapsed at iteration {model.best_iteration_} - refusing to ship a stump"
    )
    p_lgbm_test = model.predict_proba(X_test)[:, 1]

    section("4. IsolationForest (fitted on legitimate training rows only)")
    rng = np.random.default_rng(SEED)
    legit_idx = np.flatnonzero(y_all == 0)
    if len(legit_idx) > IFOREST_FIT_ROWS:
        legit_idx = rng.choice(legit_idx, size=IFOREST_FIT_ROWS, replace=False)
    # IsolationForest needs numeric input; categoricals go in as their pinned category codes.
    def to_numeric(frame: pd.DataFrame) -> np.ndarray:
        out = frame.copy()
        for col in CATEGORICAL_FEATURES:
            out[col] = out[col].cat.codes.astype("float64")
        return out.to_numpy(dtype="float64")

    iforest = IsolationForest(
        n_estimators=IFOREST_TREES, max_samples=256, contamination="auto",
        random_state=SEED, n_jobs=-1,
    )
    iforest.fit(to_numeric(X_all.iloc[legit_idx]))
    log(f"  fitted on {len(legit_idx):,} legitimate rows, {IFOREST_TREES} trees")

    # normaliser fitted on TRAIN only, per DESIGN §3
    anomaly_train = -iforest.score_samples(to_numeric(X_all))
    a_min, a_max = float(anomaly_train.min()), float(anomaly_train.max())
    log(f"  train anomaly score range: [{a_min:.4f}, {a_max:.4f}] (min-max normaliser stored)")

    def normalise(raw_anomaly: np.ndarray) -> np.ndarray:
        return np.clip((raw_anomaly - a_min) / max(1e-12, a_max - a_min), 0.0, 1.0)

    p_iforest_test = normalise(-iforest.score_samples(to_numeric(X_test)))

    section("5. Blend and rules baseline")
    p_blend_test = np.clip(W_SUPERVISED * p_lgbm_test + W_ANOMALY * p_iforest_test, 0.0, 1.0)
    log(f"  blend = {W_SUPERVISED} * lightgbm + {W_ANOMALY} * anomaly")
    rules_q = fit_rules_baseline(train_raw)
    p_baseline_test = apply_rules_baseline(test_raw, rules_q)
    log("  rules baseline: 12 rules, thresholds from train quantiles only")

    section("6. Test-set metrics (months 6-7, never seen in training)")
    score_sets = {
        "baseline": p_baseline_test,
        "lightgbm": p_lgbm_test,
        "iforest": p_iforest_test,
        "blend": p_blend_test,
    }
    metrics = {name: evaluate(name, y_test, scores) for name, scores in score_sets.items()}
    log(f"  {'model':<10} {'ROC-AUC':>9} {'PR-AUC':>9} {'P@100':>8} {'recall@1%FPR':>13}")
    for name, m in metrics.items():
        log(f"  {name:<10} {m['roc_auc']:>9.4f} {m['pr_auc']:>9.4f} "
            f"{m['precision_at_100']:>8.3f} {m['recall_at_1pct_fpr']:>13.4f}")

    if metrics["lightgbm"]["pr_auc"] <= metrics["baseline"]["pr_auc"]:
        log("\n  WARNING: LightGBM did not beat the rules baseline on PR-AUC. Reporting as measured.")

    section("7. SHAP smoke test (Lane A builds TreeExplainer at startup)")
    import shap  # local import: only needed to prove A3's path works

    explainer = shap.TreeExplainer(model)
    shap_values = explainer.shap_values(X_test.head(5))
    sv = shap_values[1] if isinstance(shap_values, list) else shap_values
    log(f"  TreeExplainer OK - shap_values shape {np.asarray(sv).shape} for 5 rows")

    section("8. Artifacts")
    with open(ARTIFACT_DIR / "model_v1.pkl", "wb") as fh:
        pickle.dump(model, fh, protocol=PICKLE_PROTOCOL)
    model.booster_.save_model(str(ARTIFACT_DIR / "model_v1.txt"))
    with open(ARTIFACT_DIR / "iforest_v1.pkl", "wb") as fh:
        pickle.dump({"model": iforest, "min": a_min, "max": a_max}, fh, protocol=PICKLE_PROTOCOL)

    preprocess = {
        "model_version": MODEL_VERSION,
        "feature_order": list(FEATURE_ORDER),
        "categorical_features": list(CATEGORICAL_FEATURES),
        "featurize_module": "ml.featurize",
        "featurize_entrypoint": "build_features",
        "iforest_categorical_encoding": "pandas category codes, levels pinned in ml/featurize.CATEGORY_LEVELS",
        "anomaly_normaliser": {"min": a_min, "max": a_max},
        "rules_baseline_thresholds": rules_q,
        **feature_metadata(),
    }
    with open(ARTIFACT_DIR / "preprocess_v1.pkl", "wb") as fh:
        pickle.dump(preprocess, fh, protocol=PICKLE_PROTOCOL)

    (ARTIFACT_DIR / "features.json").write_text(json.dumps(feature_metadata(), indent=2), encoding="utf-8")
    (ARTIFACT_DIR / "blend.json").write_text(
        json.dumps({"w_supervised": W_SUPERVISED, "w_anomaly": W_ANOMALY}, indent=2), encoding="utf-8"
    )
    (ARTIFACT_DIR / "reason_codes.yaml").write_text(
        "# Generated from ml/reason_codes.py - edit that module, not this file.\n"
        f"# {len(REASON_CODES)} features, validated against features.json at train time.\n"
        + yaml.safe_dump(REASON_CODES, sort_keys=True, allow_unicode=True, width=100),
        encoding="utf-8",
    )

    metrics_doc = {
        "model_version": MODEL_VERSION,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "data": {
            "train_rows": int(len(train_raw)),
            "test_rows": int(len(test_raw)),
            "fit_months": list(FIT_MONTHS),
            "validation_month": VAL_MONTH,
            "test_months": sorted(int(m) for m in test_raw[TIME_COL].unique()),
            "train_fraud_rate": float(train_raw[LABEL].mean()),
            "test_fraud_rate": float(y_test.mean()),
            "split": "temporal (DESIGN section 2) - never random",
        },
        "lightgbm": {
            "best_iteration": int(model.best_iteration_),
            "scale_pos_weight": scale_pos_weight,
            "val_pr_auc": val_pr_auc,
            "early_stopping": "patience 100 on month 5 PR-AUC, LightGBM default metric disabled",
        },
        "blend": {"w_supervised": W_SUPERVISED, "w_anomaly": W_ANOMALY},
        "n_features": len(FEATURE_ORDER),
        "excluded_protected_attributes": list(feature_metadata()["excluded_protected_attributes"]),
        "test_metrics": metrics,
        "fairness": {"status": "pending", "note": "written by ml/fairness.py in task B3"},
    }
    (ARTIFACT_DIR / "metrics_v1.json").write_text(json.dumps(metrics_doc, indent=2), encoding="utf-8")

    for name in ("model_v1.pkl", "model_v1.txt", "iforest_v1.pkl", "preprocess_v1.pkl",
                 "features.json", "blend.json", "reason_codes.yaml", "metrics_v1.json"):
        p = ARTIFACT_DIR / name
        log(f"  {('ml/artifacts/' + name):<34} {p.stat().st_size / 1024:>9.1f} KB")

    section("9. Charts")
    for p in (
        chart_pr_curve(y_test, score_sets, metrics),
        chart_score_distribution(y_test, p_blend_test),
        chart_feature_importance(model),
    ):
        log(f"  {p.relative_to(REPO).as_posix()}")

    section("10. Serving-path check (the no-skew guarantee)")
    raw_row = test_raw.iloc[0].to_dict()
    single = build_features(raw_row)
    assert list(single.columns) == list(FEATURE_ORDER), "build_features column order drifted"
    batch_row = X_test.iloc[[0]]
    single_p = float(model.predict_proba(single)[:, 1][0])
    batch_p = float(p_lgbm_test[0])
    log(f"  build_features(raw dict) -> {single.shape[0]} row x {single.shape[1]} cols, order matches features.json")
    log(f"  single-row probability {single_p:.10f} vs batch {batch_p:.10f}  delta {abs(single_p - batch_p):.2e}")
    assert abs(single_p - batch_p) < 1e-9, "single-row and batch scoring disagree - train/serve skew"
    assert single.equals(batch_row), "single-row feature values differ from the training frame"
    log("  PASS - the API path and the training path produce identical features and scores")

    log(f"\nelapsed: {time.perf_counter() - started:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
