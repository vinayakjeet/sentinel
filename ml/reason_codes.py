"""SENTINEL — feature to applicant-facing reason mapping (DESIGN §5).

This module is the source of truth. ``train.py`` dumps it to ``ml/artifacts/reason_codes.yaml``,
which is what Lane A's explainability service reads. Edit the text here and re-dump, so that
re-running training can never clobber hand-written wording.

Two rules for the ``reason`` text:

1. It is shown to a declined applicant in a Reg B adverse action notice. It must be understandable
   by someone with no knowledge of the model, and must describe the applicant's situation, never
   the mechanics ("no recorded history at the previous address", not "prev_address_months_count
   was -1 and contributed +0.4 SHAP").
2. It must not reveal a threshold an adversary could tune against.

``ecoa_category`` groups reasons the way Regulation B / the Model Form C-1 principal-reason
checklists do, so the adverse action notice can be assembled from them.
"""

from __future__ import annotations

# Controlled vocabulary — keep new entries inside this set so the notice stays assemblable.
ECOA_CATEGORIES: tuple[str, ...] = (
    "Credit history",
    "Insufficient bank references",
    "Length of residence",
    "Unable to verify identity",
    "Application characteristics",
    "Other - application channel and device",
)

REASON_CODES: dict[str, dict[str, str]] = {
    # --- identity coherence ---------------------------------------------------------------
    "name_email_similarity": {
        "reason": "The name on the application does not closely match the email address supplied.",
        "ecoa_category": "Unable to verify identity",
    },
    "date_of_birth_distinct_emails_4w": {
        "reason": "Several different email addresses have recently been used with this date of birth.",
        "ecoa_category": "Unable to verify identity",
    },
    "device_distinct_emails_8w": {
        "reason": "Several different email addresses have recently been used from this device.",
        "ecoa_category": "Unable to verify identity",
    },
    "phone_home_valid": {
        "reason": "The home telephone number provided could not be verified.",
        "ecoa_category": "Unable to verify identity",
    },
    "phone_mobile_valid": {
        "reason": "The mobile telephone number provided could not be verified.",
        "ecoa_category": "Unable to verify identity",
    },
    "device_distinct_emails_8w_missing": {
        "reason": "No email history was available for the device used to apply.",
        "ecoa_category": "Unable to verify identity",
    },
    # --- residence ------------------------------------------------------------------------
    "prev_address_months_count": {
        "reason": "Little recorded history at the previous address given.",
        "ecoa_category": "Length of residence",
    },
    "current_address_months_count": {
        "reason": "Short length of time at the current address.",
        "ecoa_category": "Length of residence",
    },
    "prev_address_months_count_missing": {
        "reason": "No previous address history was supplied with the application.",
        "ecoa_category": "Length of residence",
    },
    "current_address_months_count_missing": {
        "reason": "No history for the current address was supplied with the application.",
        "ecoa_category": "Length of residence",
    },
    "housing_status": {
        "reason": "The housing status recorded on the application.",
        "ecoa_category": "Length of residence",
    },
    # --- banking relationship ---------------------------------------------------------------
    "bank_months_count": {
        "reason": "Short banking relationship history with this institution.",
        "ecoa_category": "Insufficient bank references",
    },
    "bank_months_count_missing": {
        "reason": "No existing banking relationship could be found for the applicant.",
        "ecoa_category": "Insufficient bank references",
    },
    "has_other_cards": {
        "reason": "No other card accounts are held with this institution.",
        "ecoa_category": "Insufficient bank references",
    },
    "bank_branch_count_8w": {
        "reason": "An unusually high number of recent applications at the same bank branch.",
        "ecoa_category": "Insufficient bank references",
    },
    # --- credit ------------------------------------------------------------------------------
    "credit_risk_score": {
        "reason": "The internal credit risk score for this application.",
        "ecoa_category": "Credit history",
    },
    # --- application characteristics ---------------------------------------------------------
    "zip_count_4w": {
        "reason": "An unusually high number of recent applications from the same postal area.",
        "ecoa_category": "Application characteristics",
    },
    "velocity_6h": {
        "reason": "An unusually high number of applications received in the last few hours.",
        "ecoa_category": "Application characteristics",
    },
    "velocity_24h": {
        "reason": "An unusually high number of applications received in the last day.",
        "ecoa_category": "Application characteristics",
    },
    "velocity_4w": {
        "reason": "An unusually high number of applications received over the last few weeks.",
        "ecoa_category": "Application characteristics",
    },
    "proposed_credit_limit": {
        "reason": "The credit limit requested on this application.",
        "ecoa_category": "Application characteristics",
    },
    "intended_balcon_amount": {
        "reason": "The balance transfer amount requested on this application.",
        "ecoa_category": "Application characteristics",
    },
    "days_since_request": {
        "reason": "The time between the initial enquiry and this application being submitted.",
        "ecoa_category": "Application characteristics",
    },
    "payment_type": {
        "reason": "The payment type selected on the application.",
        "ecoa_category": "Application characteristics",
    },
    # --- channel and device -------------------------------------------------------------------
    "email_is_free": {
        "reason": "The application used a free email provider rather than a personal or work domain.",
        "ecoa_category": "Other - application channel and device",
    },
    "foreign_request": {
        "reason": "The application was submitted from outside the expected country.",
        "ecoa_category": "Other - application channel and device",
    },
    "session_length_in_minutes": {
        "reason": "The length of the online session was unusual for a genuine application.",
        "ecoa_category": "Other - application channel and device",
    },
    "session_length_in_minutes_missing": {
        "reason": "The length of the online application session could not be measured.",
        "ecoa_category": "Other - application channel and device",
    },
    "keep_alive_session": {
        "reason": "The online session behaved differently from a typical genuine application.",
        "ecoa_category": "Other - application channel and device",
    },
    "source": {
        "reason": "The channel through which the application was received.",
        "ecoa_category": "Other - application channel and device",
    },
    "device_os": {
        "reason": "The operating system of the device used to apply.",
        "ecoa_category": "Other - application channel and device",
    },
}


def validate(feature_order) -> None:
    """Raise if any model feature lacks a mapping, or any category is off-vocabulary.

    ml/tests/test_reason_codes.py calls this; so does train.py, so a feature can never reach
    Lane A's explainability path without applicant-facing text behind it.
    """
    missing = [f for f in feature_order if f not in REASON_CODES]
    if missing:
        raise ValueError(f"features with no reason code mapping: {missing}")

    extra = [f for f in REASON_CODES if f not in set(feature_order)]
    if extra:
        raise ValueError(f"reason codes for features that are not in the model: {extra}")

    bad = {
        f: entry["ecoa_category"]
        for f, entry in REASON_CODES.items()
        if entry.get("ecoa_category") not in ECOA_CATEGORIES
    }
    if bad:
        raise ValueError(f"off-vocabulary ECOA categories: {bad}")

    empty = [f for f, entry in REASON_CODES.items() if not entry.get("reason", "").strip()]
    if empty:
        raise ValueError(f"features with empty reason text: {empty}")
