import asyncio
import json
import threading
import uuid

import numpy as np
import pandas as pd
from sqlalchemy import select

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models import AuditLog, DriftEvent
from app.schemas.decision import Thresholds
from app.services.broadcaster import QUEUE_SIZE, Broadcaster
from app.services.drift import DriftMonitor
from app.services.drift_service import DriftService
from app.services.policy import PolicyEngine
from app.services.replay import base_rows, fraud_wave_rows


def shifted_stream(n=2000, before=0.2, after=0.5, seed=0):
    rng = np.random.default_rng(seed)
    return np.clip(np.concatenate([rng.normal(before, 0.05, n), rng.normal(after, 0.05, n)]), 0, 1)


def test_adwin_fires_on_synthetic_mean_shift_and_not_before():
    monitor = DriftMonitor(delta=0.1, label_lag=200, cooldown_events=500)
    fired_at = [i for i, x in enumerate(shifted_stream()) for d in monitor.observe(float(x)) if d.stream == "score"]
    assert fired_at, "ADWIN never fired on a 0.2 -> 0.5 mean shift"
    assert all(i >= 2000 for i in fired_at), f"false alarm before the shift: {fired_at}"
    assert fired_at[0] - 2000 < 200, f"detection too slow: {fired_at[0] - 2000} events after the shift"


def test_error_stream_waits_for_delayed_labels():
    monitor = DriftMonitor(delta=0.1, label_lag=200, cooldown_events=10_000)
    # Model perfectly right for 1000 events, then perfectly wrong: error jumps 0 -> 1.
    seen_error = []
    for i in range(2000):
        wrong = i >= 1000
        for d in monitor.observe(0.9 if wrong else 0.1, label=0):
            if d.stream == "error":
                seen_error.append(i)
    assert seen_error and seen_error[0] >= 1000 + 200, seen_error  # cannot fire before the lagged label arrives


def test_cooldown_suppresses_repeat_detections():
    monitor = DriftMonitor(delta=0.1, label_lag=200, cooldown_events=10_000)
    detections = [d for x in shifted_stream() for d in monitor.observe(float(x))]
    assert len(detections) == 1


def test_drift_service_tightens_persists_caps_and_resets():
    s = get_settings()
    policy = PolicyEngine(Thresholds(step_up=300, review=650, decline=850))
    svc = DriftService(s, policy, Broadcaster())
    svc.monitor.cooldown_events = 0  # every detection acts
    source = f"test-{uuid.uuid4().hex[:6]}"
    for x in np.concatenate([shifted_stream(seed=1), shifted_stream(before=0.5, after=0.9, seed=2)]):
        svc.observe(float(x), None, source)

    d = s.drift_tighten_delta
    assert policy.thresholds == Thresholds(step_up=300 - 2 * d, review=650 - 2 * d, decline=850 - 2 * d)  # capped at 2
    with SessionLocal() as db:
        events = db.scalars(select(DriftEvent).where(DriftEvent.details["source"].astext == source)).all()
        assert len(events) >= 2
        first = min(events, key=lambda e: e.id)
        assert first.old_thresholds == {"step_up": 300, "review": 650, "decline": 850}
        assert first.new_thresholds == {"step_up": 300 - d, "review": 650 - d, "decline": 850 - d}
        audit = db.scalars(select(AuditLog).where(AuditLog.resource_id == str(first.id))).one()
        assert audit.action == "drift.detected"

        status = svc.status(db)
        assert status.state == "drift_detected"
        status = svc.reset(db, actor="tester")
        assert status.state == "stable" and status.thresholds == status.base_thresholds


def test_fraud_wave_rate(tmp_path):
    n = 5000
    df = pd.DataFrame({"x": range(n), "fraud_bool": [1 if i % 100 == 0 else 0 for i in range(n)]})  # 1% fraud
    df.to_csv(tmp_path / "shift.csv", index=False)
    rows = fraud_wave_rows(tmp_path / "shift.csv", fraud_rate=0.12, seed=7)
    labels = [next(rows)[1]["fraud_bool"] for _ in range(4000)]
    assert 0.10 < np.mean(labels) < 0.14


def test_metrics_and_drift_endpoints(client, payload):
    client.post("/api/v1/decisions/application", json=payload)
    m = client.get("/api/v1/metrics").json()
    assert m["window"] >= 1 and m["p50"] > 0 and abs(sum(m["band_mix"].values()) - 1) < 1e-3
    d = client.get("/api/v1/metrics/drift").json()
    assert d["state"] in ("stable", "drift_detected") and set(d["thresholds"]) == {"step_up", "review", "decline"}
    st = client.get("/api/v1/stream/status").json()
    assert st["running"] is False and st["source"] in ("base", "shift")


def test_broadcaster_delivers_across_threads_and_drops_oldest():
    """Decisions are published from worker threads; subscribers read on the event loop.

    The HTTP SSE endpoint is verified live: Starlette's TestClient buffers whole bodies, so it cannot read a stream.
    """

    async def scenario():
        b = Broadcaster()
        b.bind(asyncio.get_running_loop())
        q = b.subscribe()
        t = threading.Thread(target=lambda: [b.publish("decision", json.dumps({"n": i})) for i in range(3)])
        t.start()
        t.join()
        got = [await asyncio.wait_for(q.get(), 1) for _ in range(3)]
        assert [json.loads(d)["n"] for _, d in got] == [0, 1, 2]
        for i in range(QUEUE_SIZE + 10):  # overflow: slow subscriber keeps the newest QUEUE_SIZE
            b.publish("decision", str(i))
        await asyncio.sleep(0.05)
        assert q.qsize() == QUEUE_SIZE and (await q.get())[1] == "10"
        b.unsubscribe(q)
        assert b.subscribers == 0

    asyncio.run(scenario())


def test_replay_reads_identifiers_as_strings(tmp_path):
    """Regression: an all-digit phone column parsed as int made every replay row fail strict validation."""
    pd.DataFrame({"phone": ["916000856369"], "device_id": ["123"], "fraud_bool": [0]}).to_csv(
        tmp_path / "s.csv", index=False
    )
    _, record = next(base_rows(tmp_path / "s.csv"))
    assert record["phone"] == "916000856369" and record["device_id"] == "123"


def test_replay_pass_identifiers_are_isolated_from_history_and_other_passes(payload):
    """Each replay pass gets its own entities, and the namespaced row still passes strict validation."""
    from app.schemas.application import ApplicationEvent
    from app.services.entity_resolver import entity_keys
    from app.services.replay import namespace_identifiers

    def keys(row: dict) -> set:
        return set(entity_keys(ApplicationEvent.model_validate(row)))

    history, pass_a, pass_b = payload, namespace_identifiers(payload, 17), namespace_identifiers(payload, 18)
    assert pass_a["applicant_name"] == history["applicant_name"]
    for field in ("device_id", "email", "phone", "address", "ip"):
        assert pass_a[field] != history[field] and pass_a[field] != pass_b[field]
    assert not keys(history) & keys(pass_a)
    assert not keys(pass_a) & keys(pass_b)


def test_starting_the_replay_clears_the_detector_window(client, monkeypatch):
    """A stale window from the previous run must not be compared with the new run's first events.

    The replay itself is stubbed: data/replay/*.csv is gitignored, so it does not exist on a CI runner.
    """
    services = client.app.state.services

    async def fake_start():
        return services.replay.status()

    monkeypatch.setattr(services.replay, "start", fake_start)
    for _ in range(50):
        services.drift.monitor.observe(0.9)
    assert services.drift.monitor.events_seen >= 50

    assert client.post("/api/v1/stream/start").status_code == 200
    assert services.drift.monitor.events_seen == 0
