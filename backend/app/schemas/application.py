import ipaddress
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

# Bounds follow the BAF datasheet ranges with headroom, so rows from the variant files (Variant II / V)
# are accepted too. They reject garbage; they are not a data-quality model.
Binary = Literal[0, 1]
Unit = Annotated[float, Field(ge=0.0, le=1.0)]
MonthsOrMissing = Annotated[int, Field(ge=-1, le=600)]  # -1 = missing (BAF sentinel)

PaymentType = Literal["AA", "AB", "AC", "AD", "AE"]
EmploymentStatus = Literal["CA", "CB", "CC", "CD", "CE", "CF", "CG"]
HousingStatus = Literal["BA", "BB", "BC", "BD", "BE", "BF", "BG"]
Source = Literal["INTERNET", "TELEAPP"]
DeviceOs = Literal["windows", "macintosh", "linux", "x11", "other"]

NonEmpty = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class ApplicationEvent(BaseModel):
    """A raw credit application: every BAF column plus synthetic identifiers used for the entity graph.

    Protected attributes (customer_age, employment_status, income) are accepted for fairness evaluation
    but are never model features (enforced in ml/featurize.py).
    """

    model_config = ConfigDict(strict=True, extra="forbid")

    # --- BAF raw columns ---
    income: Annotated[float, Field(ge=0.0, le=1.0)]
    name_email_similarity: Unit
    prev_address_months_count: MonthsOrMissing
    current_address_months_count: MonthsOrMissing
    customer_age: Annotated[int, Field(ge=10, le=100)]
    days_since_request: Annotated[float, Field(ge=0.0, le=120.0)]
    intended_balcon_amount: Annotated[float, Field(ge=-100.0, le=250.0)]
    payment_type: PaymentType
    zip_count_4w: Annotated[int, Field(ge=0, le=20000)]
    velocity_6h: Annotated[float, Field(ge=-1000.0, le=50000.0)]
    velocity_24h: Annotated[float, Field(ge=0.0, le=50000.0)]
    velocity_4w: Annotated[float, Field(ge=0.0, le=50000.0)]
    bank_branch_count_8w: Annotated[int, Field(ge=0, le=10000)]
    date_of_birth_distinct_emails_4w: Annotated[int, Field(ge=0, le=200)]
    employment_status: EmploymentStatus
    credit_risk_score: Annotated[int, Field(ge=-500, le=1000)]
    email_is_free: Binary
    housing_status: HousingStatus
    phone_home_valid: Binary
    phone_mobile_valid: Binary
    bank_months_count: Annotated[int, Field(ge=-1, le=120)]
    has_other_cards: Binary
    proposed_credit_limit: Annotated[float, Field(ge=0.0, le=10000.0)]
    foreign_request: Binary
    source: Source
    session_length_in_minutes: Annotated[float, Field(ge=-1.0, le=500.0)]
    device_os: DeviceOs
    keep_alive_session: Binary
    device_distinct_emails_8w: Annotated[int, Field(ge=-1, le=50)]
    device_fraud_count: Annotated[int, Field(ge=0, le=50)]
    month: Annotated[int, Field(ge=0, le=7)] | None = None

    # --- Synthetic identifiers (BAF has none; generated for the entity graph) ---
    device_id: Annotated[NonEmpty, StringConstraints(max_length=128)]
    email: Annotated[
        NonEmpty, StringConstraints(max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    ]
    phone: Annotated[NonEmpty, StringConstraints(max_length=32, pattern=r"^\+?[0-9 ()\-]{7,31}$")]
    ip: Annotated[NonEmpty, StringConstraints(max_length=45)]
    address: Annotated[NonEmpty, StringConstraints(max_length=256)]
    applicant_name: Annotated[NonEmpty, StringConstraints(max_length=128)]

    # --- Load metadata ---
    external_ref: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9._:-]{1,64}$")] | None = None
    history: bool = False
    # Confirmed label. Honoured only when history=true (simulated confirmed fraud for the entity graph).
    fraud_bool: Binary | None = None

    @field_validator("ip")
    @classmethod
    def _valid_ip(cls, v: str) -> str:
        try:
            return str(ipaddress.ip_address(v))
        except ValueError as exc:
            raise ValueError("ip must be a valid IPv4 or IPv6 address") from exc

    def features(self) -> dict:
        """Raw BAF columns only (what ml.featurize.build_features consumes). No identifiers, no label."""
        return self.model_dump(include=BAF_COLUMNS)

    def label(self) -> int | None:
        return self.fraud_bool if self.history else None


IDENTIFIER_FIELDS = ("device_id", "email", "phone", "ip", "address", "applicant_name")
META_FIELDS = ("external_ref", "history", "fraud_bool")
BAF_COLUMNS = frozenset(ApplicationEvent.model_fields) - set(IDENTIFIER_FIELDS) - set(META_FIELDS)
