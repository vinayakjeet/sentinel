"""SENTINEL — fairness evaluation (DESIGN §12).

Measures false-positive rate and approval rate by age group at the DECLINE threshold, writes
docs/charts/fairness.png, and merges a `fairness` block into ml/artifacts/metrics_v1.json.

Two things to be explicit about, because both affect how the numbers should be read:

1. Age is not a model feature. CLAUDE.md invariant 5 excludes customer_age, employment_status
   and income from the feature set; they are loaded here for evaluation only. Any disparity the
   chart shows therefore comes from features correlated with age, not from age itself — which is
   exactly why the evaluation is worth running.

2. BAF's `customer_age` is banded by decade (10, 20, ... 90), so DESIGN's literal "<25 / 25-50 /
   >50" buckets do not exist in the data. The closest faithful mapping is used and is printed on
   the chart and stored in the metrics file, rather than silently rounding into the DESIGN labels:

       <25   -> customer_age <= 20
       25-50 -> customer_age in {30, 40, 50}
       >50   -> customer_age >= 60

Run:  python ml/fairness.py
"""

from __future__ import annotations

import json
import pickle
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from ml.featurize import CATEGORICAL_FEATURES, build_feature_frame  # noqa: E402

PROC_DIR = REPO / "data" / "processed"
ARTIFACT_DIR = REPO / "ml" / "artifacts"
CHART_DIR = REPO / "docs" / "charts"

LABEL = "fraud_bool"
APPROVE_THRESHOLD = 300
DECLINE_THRESHOLD = 850

AGE_GROUPS: dict[str, tuple[int, int]] = {
    "<25 (age band <= 20)": (0, 20),
    "25-50 (age bands 30-50)": (30, 50),
    ">50 (age band >= 60)": (60, 200),
}


def log(msg: str = "") -> None:
    print(msg, flush=True)


def section(title: str) -> None:
    log()
    log(title)
    log("-" * len(title))


def score_test_set() -> tuple[pd.DataFrame, np.ndarray]:
    """Re-score the held-out months through the published artifacts, exactly as the API would."""
    with open(ARTIFACT_DIR / "model_v1.pkl", "rb") as fh:
        model = pickle.load(fh)
    with open(ARTIFACT_DIR / "iforest_v1.pkl", "rb") as fh:
        ifo = pickle.load(fh)
    blend = json.load(open(ARTIFACT_DIR / "blend.json", encoding="utf-8"))

    test = pd.read_parquet(PROC_DIR / "test.parquet")
    X = build_feature_frame(test)

    p_lgbm = model.predict_proba(X)[:, 1]

    Xn = X.copy()
    for col in CATEGORICAL_FEATURES:
        Xn[col] = Xn[col].cat.codes
    # DataFrame, not ndarray: the forest was fitted with feature names, so sklearn checks them here.
    anomaly = -ifo["model"].score_samples(Xn.astype("float64"))
    a_norm = np.clip((anomaly - ifo["min"]) / max(1e-12, ifo["max"] - ifo["min"]), 0.0, 1.0)

    p = np.clip(blend["w_supervised"] * p_lgbm + blend["w_anomaly"] * a_norm, 0.0, 1.0)
    return test, np.round(1000 * p).astype(int)


def group_metrics(y: np.ndarray, score: np.ndarray) -> dict:
    declined = score >= DECLINE_THRESHOLD
    approved = score < APPROVE_THRESHOLD
    legit = y == 0
    fraud = y == 1
    return {
        "n": int(len(y)),
        "fraud_rate": float(y.mean()) if len(y) else 0.0,
        "approval_rate": float(approved.mean()) if len(y) else 0.0,
        "decline_rate": float(declined.mean()) if len(y) else 0.0,
        # FPR at the DECLINE threshold: legitimate applicants who would be declined
        "fpr_at_decline": float(declined[legit].mean()) if legit.any() else 0.0,
        # shown alongside, because an FPR gap is only interpretable next to the catch rate
        "tpr_at_decline": float(declined[fraud].mean()) if fraud.any() else 0.0,
        "mean_score": float(score.mean()) if len(y) else 0.0,
    }


def chart(results: dict, overall: dict) -> Path:
    names = list(results)
    short = [n.split(" (")[0] for n in names]
    fpr = [results[n]["fpr_at_decline"] * 100 for n in names]
    approval = [results[n]["approval_rate"] * 100 for n in names]

    fig, axes = plt.subplots(1, 2, figsize=(11.5, 5.0), dpi=140)

    ax = axes[0]
    bars = ax.bar(short, fpr, color="#c1443a", width=0.55)
    ax.axhline(overall["fpr_at_decline"] * 100, color="#444444", linestyle="--", linewidth=1.1,
               label=f"overall ({overall['fpr_at_decline'] * 100:.3f}%)")
    ax.set_ylabel("False positive rate (%)")
    ax.set_title(f"Legitimate applicants declined\n(score >= {DECLINE_THRESHOLD})", fontsize=11)
    ax.legend(frameon=False, fontsize=9)
    for b, v in zip(bars, fpr, strict=False):
        ax.text(b.get_x() + b.get_width() / 2, v, f"{v:.3f}%", ha="center", va="bottom", fontsize=9)

    ax = axes[1]
    bars = ax.bar(short, approval, color="#2e7d5b", width=0.55)
    ax.axhline(overall["approval_rate"] * 100, color="#444444", linestyle="--", linewidth=1.1,
               label=f"overall ({overall['approval_rate'] * 100:.1f}%)")
    ax.set_ylabel("Approval rate (%)")
    ax.set_title(f"Straight-through approvals\n(score < {APPROVE_THRESHOLD})", fontsize=11)
    ax.legend(frameon=False, fontsize=9)
    for b, v in zip(bars, approval, strict=False):
        ax.text(b.get_x() + b.get_width() / 2, v, f"{v:.1f}%", ha="center", va="bottom", fontsize=9)

    for ax in axes:
        ax.grid(alpha=0.2, axis="y", linewidth=0.6)
        ax.set_axisbelow(True)
        ax.margins(y=0.15)

    fig.suptitle(
        "Fairness by age group on held-out months 6-7 — age is NOT a model feature "
        "(BAF bands age by decade; see ml/fairness.py)",
        fontsize=10.5,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    path = CHART_DIR / "fairness.png"
    fig.savefig(path)
    plt.close(fig)
    return path


def main() -> int:
    started = time.perf_counter()
    CHART_DIR.mkdir(parents=True, exist_ok=True)

    log("=" * 78)
    log("SENTINEL - fairness evaluation (DESIGN section 12)")
    log("=" * 78)

    test, score = score_test_set()
    y = test[LABEL].to_numpy()
    age = test["customer_age"].to_numpy()

    section("1. Age banding in BAF")
    bands, counts = np.unique(age, return_counts=True)
    log(f"  customer_age takes {len(bands)} distinct values: {[int(b) for b in bands]}")
    log("  DESIGN's <25 / 25-50 / >50 buckets do not exist in the data; using the closest mapping")

    section("2. Metrics by age group at the DECLINE threshold")
    overall = group_metrics(y, score)
    results: dict[str, dict] = {}
    for name, (lo, hi) in AGE_GROUPS.items():
        mask = (age >= lo) & (age <= hi)
        results[name] = group_metrics(y[mask], score[mask])

    header = f"  {'group':<26} {'n':>8} {'fraud%':>8} {'approve%':>9} {'decline%':>9} {'FPR%':>8} {'TPR%':>8}"
    log(header)
    for name, m in results.items():
        log(f"  {name.split(' (')[0]:<26} {m['n']:>8,} {m['fraud_rate'] * 100:>8.3f} "
            f"{m['approval_rate'] * 100:>9.2f} {m['decline_rate'] * 100:>9.3f} "
            f"{m['fpr_at_decline'] * 100:>8.3f} {m['tpr_at_decline'] * 100:>8.2f}")
    log(f"  {'OVERALL':<26} {overall['n']:>8,} {overall['fraud_rate'] * 100:>8.3f} "
        f"{overall['approval_rate'] * 100:>9.2f} {overall['decline_rate'] * 100:>9.3f} "
        f"{overall['fpr_at_decline'] * 100:>8.3f} {overall['tpr_at_decline'] * 100:>8.2f}")

    covered = sum(m["n"] for m in results.values())
    if covered != len(y):
        log(f"  note: {len(y) - covered:,} rows fall outside the three groups")

    section("3. Disparity")
    fprs = {n: m["fpr_at_decline"] for n, m in results.items()}
    apps = {n: m["approval_rate"] for n, m in results.items()}
    worst_fpr, best_fpr = max(fprs, key=fprs.get), min(fprs, key=fprs.get)
    fpr_ratio = (fprs[worst_fpr] / fprs[best_fpr]) if fprs[best_fpr] > 0 else float("inf")
    worst_app, best_app = min(apps, key=apps.get), max(apps, key=apps.get)
    app_ratio = (apps[worst_app] / apps[best_app]) if apps[best_app] > 0 else 0.0
    log(f"  highest FPR group      : {worst_fpr.split(' (')[0]}  ({fprs[worst_fpr] * 100:.3f}%)")
    log(f"  lowest  FPR group      : {best_fpr.split(' (')[0]}  ({fprs[best_fpr] * 100:.3f}%)")
    log(f"  FPR disparity ratio    : {fpr_ratio:.2f}x")
    log(f"  approval-rate ratio    : {app_ratio:.3f}  (lowest/highest group; the 80% rule reads this >= 0.80)")
    log("  age is not a model feature; any gap comes from features correlated with age")

    section("4. Outputs")
    path = chart(results, overall)
    log(f"  {path.relative_to(REPO).as_posix()}")

    metrics_path = ARTIFACT_DIR / "metrics_v1.json"
    doc = json.load(open(metrics_path, encoding="utf-8"))
    doc["fairness"] = {
        "status": "measured",
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "evaluated_on": "test.parquet (months 6-7)",
        "score_used": "blended score, before graph uplift (uplift is applied in the backend)",
        "approve_threshold": APPROVE_THRESHOLD,
        "decline_threshold": DECLINE_THRESHOLD,
        "protected_attribute": "customer_age",
        "note": (
            "customer_age is NOT a model feature (CLAUDE.md invariant 5); it is used here for "
            "evaluation only. BAF bands age by decade, so DESIGN's <25/25-50/>50 buckets are "
            "mapped to <=20 / 30-50 / >=60."
        ),
        "age_group_definitions": {k: {"min": v[0], "max": v[1]} for k, v in AGE_GROUPS.items()},
        "overall": overall,
        "by_age_group": results,
        "disparity": {
            "fpr_ratio_worst_over_best": fpr_ratio,
            "fpr_worst_group": worst_fpr,
            "fpr_best_group": best_fpr,
            "approval_rate_ratio_lowest_over_highest": app_ratio,
            "four_fifths_rule_met": bool(app_ratio >= 0.80),
        },
    }
    metrics_path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    log(f"  {metrics_path.relative_to(REPO).as_posix()} - fairness block merged")

    log(f"\nelapsed: {time.perf_counter() - started:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
