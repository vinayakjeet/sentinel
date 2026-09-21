# Model card — SENTINEL application-fraud scorer `v1`

Real-time fraud scoring for digital lending applications. Produced by `ml/train.py`; every number
below is measured on the held-out months and reproducible with the commands in §11. Nothing here
is estimated or rounded in the model's favour.

| | |
|---|---|
| **Version** | `v1` |
| **Date** | 21 September 2026 |
| **Type** | LightGBM gradient-boosted trees + IsolationForest anomaly detector, linearly blended |
| **Output** | Fraud probability, rescaled to an integer score 0–1000, mapped to a policy band |
| **Owner** | SENTINEL — Lane B |

---

## 1. Intended use

Scoring a new credit-card application at submission time, in a human-in-the-loop workflow. The
score selects a **policy band**, not a final answer: only the narrow DECLINE band is intended for
automated adverse action, and even there the decision is recorded with reasons and is appealable.

**Out of scope.** Account takeover and transaction fraud (designed for, not built — see DESIGN §1).
Any use as a credit-worthiness or affordability score: this model is trained to detect *fraudulent
applications*, not to predict repayment. Any use without the reason codes and the adverse-action
path, which are what make a decline explainable under Regulation B.

---

## 2. Data

* **Source** — Feedzai Bank Account Fraud (BAF), NeurIPS 2022. `Base.csv`, 1,000,000 rows,
  32 columns, fraud rate **1.103%** (11,029 fraudulent applications).
* **Split** — strictly temporal, per DESIGN §2. Never random.

  | split | months | rows | fraud rate |
  |---|---|---|---|
  | fit | 0–4 | 675,666 | 1.000% |
  | validation (early stopping only) | 5 | 119,323 | 1.183% |
  | **test (never seen in training)** | **6–7** | **205,011** | **1.404%** |

* **Missing data** — BAF encodes "not applicable / unknown" as `-1` in five columns. The `-1` is
  kept (the trees split on it happily) and an explicit `<col>_missing` flag is added, rather than
  imputing a value the applicant never supplied. `prev_address_months_count` is `-1` for 71.3% of
  rows, so this is a large effect, not a detail. `credit_risk_score` also contains `-1`, but its
  genuine range starts at −170, so there `-1` is a real score and gets no flag.
* **Synthetic identifiers** — BAF ships no identifiers. `device_id`, `email`, `phone`, `ip`,
  `address` and `applicant_name` are generated deterministically from a seeded RNG, and four fraud
  rings of 8–15 applications each are planted sharing a device and a phone. **This linkage is
  synthetic and exists to demonstrate the entity graph. It is not a property of the published
  dataset**, and no conclusion about real-world fraud rings should be drawn from it.

## 3. Features

**31 features**: 22 numeric, 5 missing-indicator flags, 4 categorical
(`payment_type`, `housing_status`, `source`, `device_os`, passed to LightGBM as native categoricals).

**Excluded, and why:**

| Excluded | Reason |
|---|---|
| `customer_age`, `employment_status`, `income` | Protected attributes (CLAUDE.md invariant 5). Retained for fairness evaluation only, never seen by the model. |
| `month` | The temporal split key. Training on it would fit month-specific effects that cannot generalise to held-out months. |
| `device_fraud_count` | Constant `0` across all 1,000,000 rows — no signal. |
| `fraud_bool` | The label. |

Note: DESIGN §2 listed `employment_status` both as a LightGBM categorical *and* as an excluded
protected attribute. The invariant wins; it is not a feature.

The **same function** builds features for training and for serving —
`ml.featurize.build_features(raw: dict)` is a thin wrapper over the `build_feature_frame()` that
training calls, so train/serve skew is structurally impossible rather than merely unlikely.
`ml/train.py` asserts it on every run: single-row and batch probabilities agree to `0.00e+00`.

## 4. Training

* LightGBM binary classifier, `scale_pos_weight = 99.25`, learning rate 0.05, 63 leaves,
  `min_child_samples=100`, subsample 0.8, colsample 0.8, `reg_lambda=1.0`, seed 20260921.
* Early stopping on **month 5 PR-AUC**, patience 100 → **185 trees**, validation PR-AUC **0.1715**.
  LightGBM's default `binary_logloss` metric is disabled: at `scale_pos_weight ≈ 99` it is best at
  iteration 1 and never improves, which silently early-stops the fit into a single tree. `train.py`
  asserts `best_iteration_ > 10` so that failure cannot recur unnoticed.
* IsolationForest, 200 trees, fitted on **200,000 legitimate training rows only**; its raw anomaly
  score is min–max normalised using bounds fitted on train alone.
* Blend `p = 0.75 · lightgbm + 0.25 · anomaly` (weights config-driven in `ml/artifacts/blend.json`).
* A **graph uplift** is applied downstream in the backend, not here, and is reported separately on
  every decision (DESIGN §3). It is not a model feature.

## 5. Evaluation

Test set = months 6–7, 205,011 applications, 2,878 frauds. Never seen during training or tuning.

| model | ROC-AUC | PR-AUC | Precision@100 | Recall @ 1% FPR |
|---|---|---|---|---|
| rules baseline (12 expert rules) | 0.6851 | 0.0243 | 0.040 | 0.0024 |
| **LightGBM** | **0.8765** | **0.1668** | **0.550** | 0.2265 |
| IsolationForest (unsupervised) | 0.5855 | 0.0199 | 0.060 | 0.0236 |
| blend (shipped) | 0.8726 | 0.1596 | 0.480 | **0.2297** |

Baseline thresholds come from **train** quantiles only, so the comparison carries no test leakage.
At a 1.4% base rate, PR-AUC is the metric that matters; the blend is **6.6×** the baseline there.

**Stated plainly: the blend is slightly worse than LightGBM alone** on PR-AUC (0.1596 vs 0.1668)
and Precision@100 (0.48 vs 0.55), and slightly better on recall at 1% FPR (0.2297 vs 0.2265). The
IsolationForest is barely better than chance on its own (ROC-AUC 0.586). The blend is retained
because DESIGN §3 specifies it and because the unsupervised channel is the part that can respond to
fraud patterns absent from the training labels — but on this dataset it costs a little precision
and it would be wrong to present it otherwise. The weights are config, not code, so this is a
one-line change if the trade is judged not worth it.

## 6. Operating points

Bands from DESIGN §3, measured on the test set:

| band | score | share of volume | fraud rate in band | share of all fraud caught |
|---|---|---|---|---|
| APPROVE | < 300 | 77.90% | 0.34% | 18.8% |
| STEP_UP | 300–649 | 16.91% | 2.64% | 31.8% |
| REVIEW | 650–849 | 5.10% | 12.83% | 46.6% |
| DECLINE | ≥ 850 | 0.09% | **43.96%** | 2.8% |

**REVIEW + DECLINE is 5.19% of volume and contains 49.4% of all fraud.** The DECLINE band is
deliberately narrow and high-precision (44% of what lands there is genuinely fraudulent) because it
is the only band eligible for automated adverse action. Observed score range on test: median 127,
p99 777, p99.9 847, max 930.

## 7. Fairness

Measured by `ml/fairness.py`; chart at `docs/charts/fairness.png`, numbers in
`ml/artifacts/metrics_v1.json`.

BAF bands `customer_age` by decade (10, 20, … 90), so DESIGN's literal `<25 / 25–50 / >50` buckets
do not exist in the data. The closest faithful mapping is used and is printed on the chart rather
than quietly rounded into the DESIGN labels: `≤20`, `30–50`, `≥60`.

| age group | n | fraud rate | approval rate | FPR at DECLINE | TPR at DECLINE |
|---|---|---|---|---|---|
| <25 (≤20) | 51,437 | 0.644% | 85.62% | 0.014% | 1.21% |
| 25–50 (30–50) | 145,471 | 1.504% | 76.07% | 0.052% | 2.83% |
| >50 (≥60) | 8,103 | 4.430% | 61.77% | 0.271% | 3.90% |
| **overall** | 205,011 | 1.404% | 77.90% | 0.050% | 2.78% |

**Findings, stated without softening:**

1. **The approval-rate ratio is 0.721 (lowest ÷ highest group), which does not meet the four-fifths
   rule** (≥ 0.80). Applicants in the ≥60 band are approved straight-through materially less often
   than those in the ≤20 band.
2. **The FPR disparity ratio is 19.8×** — a legitimate applicant aged ≥60 is ~20× more likely to be
   auto-declined than one aged ≤20, though both rates are small in absolute terms (0.271% vs 0.014%).
3. Age is **not** a model feature. The disparity is produced by features correlated with age, and by
   a genuinely different base rate: the ≥60 group has a **4.43%** fraud rate against 0.644% for ≤20,
   a factor of ~7. Part of the gap tracks real risk; that does not make the disparate impact
   acceptable, it makes it something a deployment would have to justify and monitor.

**This is a disclosed limitation, not a solved problem.** Nothing in this submission mitigates it.
A production deployment would need, at minimum: threshold calibration per segment or an equalised-
odds post-processing step, review of the highest-gain features for age proxies, and ongoing
monitoring with alerting on the disparity ratios. See `docs/responsible-ai.md`.

## 8. Explainability

* `shap.TreeExplainer` over the LightGBM model, constructed once at API startup.
* The top 4 features by **positive** SHAP contribution (i.e. pushing toward fraud) are mapped
  through `ml/artifacts/reason_codes.yaml` to applicant-facing text plus an ECOA category, and are
  returned on every decision and required on every non-APPROVE decision.
* `ml/tests/test_reason_codes.py` fails the build if any feature lacks a mapping, if any mapping is
  orphaned, if any ECOA category is off-vocabulary, or if the published YAML drifts from its source
  module. It also asserts that no protected attribute is citable as a reason.
* Reason text is constrained to be applicant-facing: no raw column names, no model mechanics, and
  no disclosure of a threshold an adversary could tune against.

## 9. Limitations

1. **Fairness** — see §7. Fails the four-fifths rule on approval rate; unmitigated.
2. **The entity linkage is synthetic.** Ring detection is demonstrated against rings this repo
   planted. It shows the graph machinery works; it is not evidence of real-world ring detection.
3. **The anomaly component is weak** (ROC-AUC 0.586) and slightly dilutes the supervised model.
4. **Single dataset, single institution, eight months.** BAF is itself a synthetic-but-realistic
   dataset; results will not transfer unchanged to production traffic.
5. **Labels are assumed correct and immediate.** Real application fraud labels arrive late and are
   incomplete; DESIGN §7's delayed-label drift path models the lag, but not label noise.
6. **No adversarial evaluation.** The model has not been tested against an attacker who knows the
   feature set.
7. `device_fraud_count` being constant zero suggests BAF nulled a leakage-prone column; an
   equivalent production feature would likely be highly predictive and is absent here.

## 10. Artifacts

| file | contents |
|---|---|
| `ml/artifacts/model_v1.pkl` | LightGBM classifier (pickle protocol 4) |
| `ml/artifacts/model_v1.txt` | same booster, LightGBM native text format — version-proof fallback |
| `ml/artifacts/iforest_v1.pkl` | `{"model", "min", "max"}` — IsolationForest + train-fitted normaliser |
| `ml/artifacts/preprocess_v1.pkl` | everything needed to turn a raw dict into the feature frame |
| `ml/artifacts/features.json` | ordered feature names, categorical list, category levels, exclusions |
| `ml/artifacts/blend.json` | `{"w_supervised": 0.75, "w_anomaly": 0.25}` |
| `ml/artifacts/reason_codes.yaml` | feature → `{reason, ecoa_category}` |
| `ml/artifacts/metrics_v1.json` | every metric above, including baseline and fairness |

## 11. Reproduction

```bash
python -m venv .venv && .venv/Scripts/pip install -r ml/requirements.txt
# place Base.csv and one Variant CSV in data/raw/
python ml/scripts/prepare_data.py     # split, demo sample, rings, replay streams
python ml/train.py                    # models, artifacts, charts, metrics
python ml/fairness.py                 # fairness block + docs/charts/fairness.png
python -m pytest ml/tests -q
```

Seed `20260921` throughout. The dependency pins in `ml/requirements.txt` are exact and are the
newest fully stable set that installs identically on Python 3.11 and 3.13 — the artifacts are
pickled on 3.13 here and unpickled in a 3.11 container, so the pins are a correctness requirement,
not housekeeping.
