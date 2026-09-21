import pytest

URL = "/api/v1/decisions/application"


@pytest.mark.parametrize(
    "field, value",
    [
        ("name_email_similarity", 1.5),  # out of [0, 1]
        ("customer_age", 5),  # below bound
        ("month", 8),  # BAF months are 0-7
        ("payment_type", "ZZ"),  # unknown category
        ("device_os", "Windows"),  # categories are case-sensitive
        ("email_is_free", 2),  # binary
        ("zip_count_4w", "12"),  # strict: no string -> int coercion
        ("prev_address_months_count", -2),  # only -1 is the missing sentinel
        ("email", "not-an-email"),
        ("ip", "999.1.1.1"),
        ("applicant_name", "   "),
    ],
)
def test_invalid_field_returns_422(client, payload, field, value):
    payload[field] = value
    r = client.post(URL, json=payload)
    assert r.status_code == 422, r.text
    assert any(field in err["loc"] for err in r.json()["detail"])


def test_missing_required_field_returns_422(client, payload):
    del payload["credit_risk_score"]
    assert client.post(URL, json=payload).status_code == 422


def test_unknown_field_rejected(client, payload):
    payload["is_fraud_obviously"] = True
    assert client.post(URL, json=payload).status_code == 422


def test_missing_sentinel_minus_one_accepted(client, payload):
    payload["bank_months_count"] = -1
    payload["session_length_in_minutes"] = -1
    assert client.post(URL, json=payload).status_code == 201
