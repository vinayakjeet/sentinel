import time
import uuid

import pytest
from sqlalchemy import func, select, text

from app.db.session import SessionLocal
from app.models import Entity, EntityLink
from app.repositories import graph_repo
from app.services.normalize import sha256_hex

URL = "/api/v1/decisions/application"


def person(payload: dict, **shared) -> dict:
    """A payload with identifiers unique to this call, except those passed in `shared`."""
    u = uuid.uuid4()
    b = u.bytes
    return {
        **payload,
        "device_id": f"dev-{u.hex[:12]}",
        "email": f"{u.hex[:12]}@example.com",
        "phone": f"+1 555 {int.from_bytes(b[:4]) % 10**7:07d}",
        "ip": f"10.{b[4]}.{b[5]}.{b[6]}",
        "address": f"{u.hex[:6]} Test Road",
        "applicant_name": f"Person {u.hex[:8]}",
        "external_ref": f"t-{u.hex[:10]}",
        **shared,
    }


def post(client, body: dict) -> dict:
    r = client.post(URL, json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_two_apps_sharing_a_device_one_device_node_two_links(client, payload):
    device = f"Dev-Shared-{uuid.uuid4().hex[:8]}"
    a = post(client, person(payload, device_id=device))
    b = post(client, person(payload, device_id=device.lower()))  # normalised to the same entity

    with SessionLocal() as db:
        dev = db.scalars(
            select(Entity).where(Entity.type == "device", Entity.value_hash == sha256_hex(device.lower()))
        ).one()
        n_links = db.scalar(select(func.count()).select_from(EntityLink).where(EntityLink.entity_id == dev.id))
        assert n_links == 2

    assert b["graph_signals"]["component_size"] == 2
    graph = client.get(f"/api/v1/entities/{b['application_id']}/graph").json()
    device_nodes = [n for n in graph["nodes"] if n["type"] == "device"]
    assert [n["id"] for n in device_nodes] == [f"ent:{dev.id}"]
    linked = {e["source"] for e in graph["edges"] if e["target"] == f"ent:{dev.id}"}
    assert linked == {f"app:{a['application_id']}", f"app:{b['application_id']}"}
    # display depth 3: both applications plus each one's own four other identifiers
    assert sum(n["type"] == "application" for n in graph["nodes"]) == 2
    assert len(graph["nodes"]) == 2 + 1 + 4 + 4


def test_identifiers_are_normalised_before_hashing(client, payload):
    email = f"Mixed.Case.{uuid.uuid4().hex[:6]}@Example.COM"
    a = post(client, person(payload, email=f"  {email}  "))
    b = post(client, person(payload, email=email.lower()))
    assert b["graph_signals"]["component_size"] == 2, (a, b)


def test_history_fraud_propagates_live_label_ignored(client, payload):
    phone = f"+44 20 {uuid.uuid4().int % 10**8:08d}"
    live = post(client, {**person(payload, phone=phone), "fraud_bool": 1})  # live: label must be ignored
    probe = post(client, person(payload, phone=phone))
    assert probe["graph_signals"]["known_fraud_2hop"] == 0

    post(client, {**person(payload, phone=phone), "fraud_bool": 1, "history": True})
    probe2 = post(client, person(payload, phone=phone))
    assert probe2["graph_signals"]["known_fraud_2hop"] == 1
    assert probe2["graph_uplift"] == pytest.approx(0.15)

    graph = client.get(f"/api/v1/entities/{probe2['application_id']}/graph").json()
    phone_nodes = [n for n in graph["nodes"] if n["type"] == "phone"]
    assert len(phone_nodes) == 1 and phone_nodes[0]["fraud"] is True
    assert live["graph_uplift"] == 0.0


def test_uplift_component_size_and_names_per_device(client, payload):
    device = f"dev-ring-{uuid.uuid4().hex[:8]}"
    last = None
    for _ in range(5):
        last = post(client, person(payload, device_id=device))  # 5 different names on one device
    g = last["graph_signals"]
    assert g["component_size"] == 5 and g["distinct_names_per_device"] == 5
    assert last["graph_uplift"] == pytest.approx(0.10 + 0.05)
    assert last["score"] >= 150  # uplift of 0.15 is 150 points on top of the model


def test_graph_never_exposes_raw_identifiers(client, payload):
    body = person(payload)
    d = post(client, body)
    raw = client.get(f"/api/v1/entities/{d['application_id']}/graph").text
    for field in ("device_id", "email", "phone", "ip", "address", "applicant_name"):
        assert body[field] not in raw


def test_graph_unknown_application_404(client):
    assert client.get(f"/api/v1/entities/{uuid.uuid4()}/graph").status_code == 404


def test_hub_is_bounded_to_200_nodes_and_cte_is_fast():
    """300 applications on one shared IP: the walk must stop at 200 nodes and stay well under 50 ms."""
    with SessionLocal() as db:
        hub = db.execute(
            text("INSERT INTO entities(type, value_hash) VALUES ('ip', :h) RETURNING id"), {"h": uuid.uuid4().hex * 2}
        ).scalar_one()
        app_ids = [uuid.uuid4() for _ in range(300)]
        db.execute(
            text(
                "INSERT INTO applications(id, features, name_hash, source_stream, is_history) "
                "SELECT unnest(CAST(:ids AS uuid[])), '{}'::jsonb, 'x', 'test', false"
            ),
            {"ids": [str(a) for a in app_ids]},
        )
        db.execute(
            text("INSERT INTO entity_links(application_id, entity_id) SELECT unnest(CAST(:ids AS uuid[])), :e"),
            {"ids": [str(a) for a in app_ids], "e": hub},
        )
        db.commit()

        graph_repo.neighbourhood(db, app_ids[0], max_depth=2, max_nodes=200, fanout=200)  # warm
        t0 = time.perf_counter()
        hood = graph_repo.neighbourhood(db, app_ids[0], max_depth=2, max_nodes=200, fanout=200)
        elapsed_ms = (time.perf_counter() - t0) * 1000

        assert len(hood.application_ids) + len(hood.entity_ids) == 200
        assert hood.truncated is True
        assert elapsed_ms < 50, f"neighbourhood CTE took {elapsed_ms:.1f} ms"
