"""SENTINEL — feature construction (DESIGN §2, §4).

One transformation, used by both sides:

    build_features(raw: dict) -> pd.DataFrame        # 1 row, what the API calls per request
    build_feature_frame(df: pd.DataFrame) -> ...     # many rows, what train.py calls

`build_features` is a thin wrapper over `build_feature_frame`, so there is exactly one
implementation of the feature logic and training/serving skew is structurally impossible
rather than merely unlikely.

Design decisions enforced here:

* BAF uses -1 as a "not applicable / unknown" sentinel in five columns. We keep the -1 (LightGBM
  splits on it happily) and add an explicit <col>_missing flag, rather than imputing a value the
  applicant never supplied.
* `credit_risk_score` also contains -1 values, but its real range starts at -170, so there -1 is a
  genuine score and NOT a sentinel. It gets no missing flag.
* CLAUDE.md invariant 5: customer_age, employment_status and income are protected attributes and
  are never features. They are carried through the pipeline for fairness evaluation only.
* `month` is the temporal split key, not a feature — training on it would let the model learn
  month-specific effects that cannot generalise to the held-out months.
* `device_fraud_count` is constant (0) across all 1,000,000 rows, so it carries no signal and is
  dropped.
* Categorical levels are pinned here rather than inferred, so a single-row request produces the
  same LightGBM category codes as the training frame did.
"""

from __future__ import annotations

from typing import Any, Mapping

import pandas as pd

# --- protected attributes: never features (CLAUDE.md invariant 5) -----------------------------
PROTECTED_ATTRIBUTES: tuple[str, ...] = ("customer_age", "employment_status", "income")

# --- columns carrying BAF's -1 "unknown" sentinel ---------------------------------------------
SENTINEL_VALUE = -1
SENTINEL_COLS: tuple[str, ...] = (
    "prev_address_months_count",
    "current_address_months_count",
    "bank_months_count",
    "session_length_in_minutes",
    "device_distinct_emails_8w",
)

NUMERIC_FEATURES: tuple[str, ...] = (
    "name_email_similarity",
    "prev_address_months_count",
    "current_address_months_count",
    "days_since_request",
    "intended_balcon_amount",
    "zip_count_4w",
    "velocity_6h",
    "velocity_24h",
    "velocity_4w",
    "bank_branch_count_8w",
    "date_of_birth_distinct_emails_4w",
    "credit_risk_score",
    "email_is_free",
    "phone_home_valid",
    "phone_mobile_valid",
    "bank_months_count",
    "has_other_cards",
    "proposed_credit_limit",
    "foreign_request",
    "session_length_in_minutes",
    "keep_alive_session",
    "device_distinct_emails_8w",
)

MISSING_FLAG_FEATURES: tuple[str, ...] = tuple(f"{c}_missing" for c in SENTINEL_COLS)

# Observed levels from all 1,000,000 Base.csv rows (ml/artifacts/raw_columns.json).
# employment_status is deliberately absent — it is protected.
CATEGORY_LEVELS: dict[str, tuple[str, ...]] = {
    "payment_type": ("AA", "AB", "AC", "AD", "AE"),
    "housing_status": ("BA", "BB", "BC", "BD", "BE", "BF", "BG"),
    "source": ("INTERNET", "TELEAPP"),
    "device_os": ("linux", "macintosh", "other", "windows", "x11"),
}
CATEGORICAL_FEATURES: tuple[str, ...] = tuple(CATEGORY_LEVELS)

#: Canonical feature order. ml/artifacts/features.json is written from this, and Lane A's
#: ModelRegistry asserts the frame it gets back matches it.
FEATURE_ORDER: tuple[str, ...] = NUMERIC_FEATURES + MISSING_FLAG_FEATURES + CATEGORICAL_FEATURES

#: Raw columns a caller must supply. Identifiers, the label and `month` may be present and are ignored.
REQUIRED_RAW_COLUMNS: tuple[str, ...] = NUMERIC_FEATURES + CATEGORICAL_FEATURES


class FeatureError(ValueError):
    """Raised when a raw payload cannot be turned into a valid feature row."""


def build_feature_frame(df: pd.DataFrame, *, strict: bool = True) -> pd.DataFrame:
    """Turn a frame of raw BAF rows into the model feature frame.

    Returns a new frame with exactly FEATURE_ORDER columns, in that order, with the four
    categoricals as pandas ``category`` dtype using the pinned levels.
    """
    missing = [c for c in REQUIRED_RAW_COLUMNS if c not in df.columns]
    if missing and strict:
        raise FeatureError(f"missing required raw columns: {missing}")

    out = pd.DataFrame(index=df.index)

    for col in NUMERIC_FEATURES:
        if col not in df.columns:
            raise FeatureError(f"missing required raw column: {col}")
        out[col] = pd.to_numeric(df[col], errors="coerce").astype("float64")

    # Explicit "the applicant has no such history" flags, computed before any other handling so
    # the sentinel stays visible to the model in both the value and the flag.
    for col in SENTINEL_COLS:
        out[f"{col}_missing"] = (out[col] == SENTINEL_VALUE).astype("int8")

    for col, levels in CATEGORY_LEVELS.items():
        if col not in df.columns:
            raise FeatureError(f"missing required raw column: {col}")
        values = df[col].astype("string").str.strip()
        out[col] = pd.Categorical(values, categories=list(levels))

    out = out[list(FEATURE_ORDER)]

    if out.isna().to_numpy().any():
        bad = out.columns[out.isna().any()].tolist()
        # An unseen categorical level becomes NaN here; LightGBM would treat it as missing, but we
        # would rather hear about it than score an application on a level we never trained on.
        raise FeatureError(f"NaN after featurisation in columns: {bad}")

    return out


def build_features(raw: Mapping[str, Any]) -> pd.DataFrame:
    """Build the 1-row feature frame for a single raw application payload.

    This is the function Lane A's scoring service imports. It shares its entire implementation
    with the training path via ``build_feature_frame``.
    """
    if not isinstance(raw, Mapping):
        raise FeatureError(f"expected a mapping, got {type(raw).__name__}")
    frame = build_feature_frame(pd.DataFrame([dict(raw)]))
    if len(frame) != 1:
        raise FeatureError(f"expected 1 row, produced {len(frame)}")
    return frame


def feature_metadata() -> dict[str, Any]:
    """The contents of ml/artifacts/features.json (written by train.py)."""
    return {
        "feature_order": list(FEATURE_ORDER),
        "n_features": len(FEATURE_ORDER),
        "numeric": list(NUMERIC_FEATURES),
        "missing_flags": list(MISSING_FLAG_FEATURES),
        "categorical": list(CATEGORICAL_FEATURES),
        "category_levels": {k: list(v) for k, v in CATEGORY_LEVELS.items()},
        "sentinel_value": SENTINEL_VALUE,
        "sentinel_columns": list(SENTINEL_COLS),
        "excluded_protected_attributes": list(PROTECTED_ATTRIBUTES),
        "excluded_other": {
            "month": "temporal split key, not a feature",
            "device_fraud_count": "constant 0 across all 1,000,000 rows, no signal",
            "fraud_bool": "label",
        },
    }
