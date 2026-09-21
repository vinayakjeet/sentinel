"""Load the demo database by POSTing applications through the live API (task B4).

Everything goes through `POST /api/v1/decisions/application` rather than straight into Postgres, so
the demo data is produced by exactly the code path a real application takes: the same validation,
the same scoring, the same entity resolution, the same persistence. A direct SQL load would be much
faster and would prove nothing.

Rows are sent with `history: true`, so `fraud_bool` is honoured and sets `fraud_flag` on the
resolved entities — that is what gives the entity graph its confirmed-fraud signal (DESIGN §6).

At the end it reports what the graph actually did: the size of each planted ring's component, and
the mean score of ring members before and after the graph uplift. Then it picks three hero cases
for the demo and writes them to docs/demo_ids.json.

    python ml/scripts/load_demo_db.py --limit 5000        # quick pass
    python ml/scripts/load_demo_db.py                     # the full 150k sample

Auth: set SENTINEL_TOKEN, or pass --username/--password and it will log in. Before Lane A's A6
lands, neither is needed.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
PROC_DIR = REPO / "data" / "processed"
ARTIFACT_DIR = REPO / "ml" / "artifacts"
DOCS_DIR = REPO / "docs"

DEFAULT_BASE_URL = os.environ.get("SENTINEL_API", "http://localhost:8000")
API = "/api/v1"

# ApplicationEvent is strict (extra="forbid", strict=True), so every value must arrive as the exact
# JSON type the model declares. pandas gives float64 for most columns, which strict int fields
# reject, so the cast below is not cosmetic.
INT_FIELDS = (
    "prev_address_months_count", "current_address_months_count", "customer_age", "zip_count_4w",
    "bank_branch_count_8w", "date_of_birth_distinct_emails_4w", "credit_risk_score",
    "email_is_free", "phone_home_valid", "phone_mobile_valid", "bank_months_count",
    "has_other_cards", "foreign_request", "keep_alive_session", "device_distinct_emails_8w",
    "device_fraud_count", "month",
)
FLOAT_FIELDS = (
    "income", "name_email_similarity", "days_since_request", "intended_balcon_amount",
    "velocity_6h", "velocity_24h", "velocity_4w", "proposed_credit_limit",
    "session_length_in_minutes",
)
STR_FIELDS = (
    "payment_type", "employment_status", "housing_status", "source", "device_os",
    "device_id", "email", "phone", "ip", "address", "applicant_name",
)


def log(msg: str = "") -> None:
    print(msg, flush=True)


def section(title: str) -> None:
    log()
    log(title)
    log("-" * len(title))


def to_payload(row: pd.Series, external_ref: str) -> dict:
    payload: dict = {}
    for field in INT_FIELDS:
        if field in row and pd.notna(row[field]):
            payload[field] = int(row[field])
    for field in FLOAT_FIELDS:
        if field in row and pd.notna(row[field]):
            payload[field] = float(row[field])
    for field in STR_FIELDS:
        if field in row and pd.notna(row[field]):
            payload[field] = str(row[field])
    payload["external_ref"] = external_ref
    payload["history"] = True
    if "fraud_bool" in row and pd.notna(row["fraud_bool"]):
        payload["fraud_bool"] = int(row["fraud_bool"])
    return payload


def authenticate(client: httpx.Client, username: str | None, password: str | None) -> str | None:
    token = os.environ.get("SENTINEL_TOKEN")
    if token:
        log("  using SENTINEL_TOKEN from the environment")
        return token
    if not (username and password):
        return None
    r = client.post(f"{API}/auth/login", json={"username": username, "password": password})
    if r.status_code != 200:
        raise SystemExit(f"login failed: HTTP {r.status_code} {r.text[:200]}")
    token = r.json()["access_token"]
    log(f"  logged in as {username}")
    return token


class RateLimiter:
    """Simple token-free rate limit: spread requests evenly across all workers."""

    def __init__(self, per_second: float) -> None:
        self._interval = 1.0 / per_second if per_second > 0 else 0.0
        self._lock = threading.Lock()
        self._next = time.perf_counter()

    def wait(self) -> None:
        if not self._interval:
            return
        with self._lock:
            now = time.perf_counter()
            self._next = max(now, self._next) + self._interval
            target = self._next
        delay = target - time.perf_counter()
        if delay > 0:
            time.sleep(delay)


def select_rows(demo: pd.DataFrame, limit: int, ring_devices: set[str]) -> pd.DataFrame:
    """Rows to send. A limited run still includes every ring member, or the graph demo is pointless."""
    if not limit or limit >= len(demo):
        return demo
    ring_mask = demo["device_id"].isin(ring_devices)
    rings = demo[ring_mask]
    rest = demo[~ring_mask].head(max(0, limit - len(rings)))
    out = pd.concat([rings, rest])
    return out.sample(frac=1.0, random_state=20260921).reset_index(drop=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base-url", default=DEFAULT_BASE_URL)
    ap.add_argument("--limit", type=int, default=0, help="rows to send (0 = all 150k)")
    ap.add_argument("--rate", type=float, default=50.0, help="requests per second")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--username", default=os.environ.get("DEMO_ANALYST_USERNAME"))
    ap.add_argument("--password", default=os.environ.get("DEMO_ANALYST_PASSWORD"))
    args = ap.parse_args()

    demo_path = PROC_DIR / "demo_sample.csv"
    if not demo_path.exists():
        raise SystemExit(f"{demo_path} missing - run ml/scripts/prepare_data.py first")

    rings = json.loads((ARTIFACT_DIR / "fraud_rings.json").read_text(encoding="utf-8"))
    ring_devices = {r["device_id"] for r in rings}

    log("=" * 78)
    log("SENTINEL - load demo database through the API (task B4)")
    log("=" * 78)
    log(f"api    : {args.base_url}")
    log(f"source : {demo_path.relative_to(REPO).as_posix()}")

    demo = pd.read_csv(demo_path)
    rows = select_rows(demo, args.limit, ring_devices)
    n_rings_in = int(rows["device_id"].isin(ring_devices).sum())
    log(f"sending: {len(rows):,} of {len(demo):,} rows "
        f"({int(rows['fraud_bool'].sum()):,} fraud, {n_rings_in} ring members)")
    if args.rate:
        log(f"rate   : ~{args.rate:.0f} req/s across {args.workers} workers "
            f"(~{len(rows) / args.rate / 60:.0f} min)")

    with httpx.Client(base_url=args.base_url, timeout=30.0) as client:
        section("1. Connectivity")
        try:
            health = client.get("/health")
        except httpx.HTTPError as exc:
            raise SystemExit(f"cannot reach {args.base_url}: {exc}") from exc
        log(f"  /health -> {health.status_code}")

        token = authenticate(client, args.username, args.password)
        headers = {"Authorization": f"Bearer {token}"} if token else {}

        section("2. Loading")
        limiter = RateLimiter(args.rate)
        results: list[dict] = []
        failures: dict[int, int] = defaultdict(int)
        started = time.perf_counter()
        lock = threading.Lock()

        def send(item: tuple[int, pd.Series]) -> None:
            idx, row = item
            limiter.wait()
            try:
                r = client.post(
                    f"{API}/decisions/application",
                    json=to_payload(row, external_ref=f"demo-{idx:06d}"),
                    headers=headers,
                )
            except httpx.HTTPError:
                with lock:
                    failures[0] += 1
                return
            if r.status_code not in (200, 201):
                with lock:
                    failures[r.status_code] += 1
                    if len(failures) <= 3 and failures[r.status_code] == 1:
                        log(f"  HTTP {r.status_code}: {r.text[:300]}")
                return
            body = r.json()
            with lock:
                results.append(
                    {
                        "external_ref": body.get("external_ref") or f"demo-{idx:06d}",
                        "decision_id": body["decision_id"],
                        "application_id": body["application_id"],
                        "score": body["score"],
                        "band": body["band"],
                        "graph_uplift": body.get("graph_uplift", 0.0),
                        "graph_signals": body.get("graph_signals", {}),
                        "n_reasons": len(body.get("reason_codes", [])),
                        "latency_ms": body.get("latency_ms", 0.0),
                        "device_id": row["device_id"],
                        "fraud_bool": int(row["fraud_bool"]) if pd.notna(row.get("fraud_bool")) else None,
                    }
                )
                if len(results) % 2000 == 0:
                    rate = len(results) / max(1e-9, time.perf_counter() - started)
                    log(f"  {len(results):,} / {len(rows):,}  ({rate:.0f}/s)")

        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            list(pool.map(send, rows.iterrows()))

        elapsed = time.perf_counter() - started
        log(f"  sent {len(results):,} in {elapsed:.0f}s ({len(results) / max(1e-9, elapsed):.0f}/s)")
        if failures:
            log(f"  FAILURES: {dict(failures)}")
        if not results:
            raise SystemExit("nothing was loaded; aborting before the report")

        loaded = pd.DataFrame(results)

        section("3. Latency")
        log(f"  p50 {loaded['latency_ms'].quantile(0.50):7.1f} ms")
        log(f"  p95 {loaded['latency_ms'].quantile(0.95):7.1f} ms")
        log(f"  p99 {loaded['latency_ms'].quantile(0.99):7.1f} ms   (DESIGN section 11 budget: < 200 ms)")

        section("4. Band mix")
        for band, n in loaded["band"].value_counts().items():
            frauds = int(loaded.loc[loaded["band"] == band, "fraud_bool"].sum())
            log(f"  {band:<9} {n:>7,} ({n / len(loaded) * 100:5.2f}%)  frauds {frauds:>5,}")

        section("5. Planted fraud rings - did the graph find them?")
        log(f"  {'ring':<6} {'device':<14} {'members':>8} {'component':>10} "
            f"{'score before':>13} {'score after':>12} {'uplift':>8}")
        ring_report = []
        for r in rings:
            members = loaded[loaded["device_id"] == r["device_id"]]
            if members.empty:
                log(f"  {r['ring']:<6} {r['device_id']:<14} {'0':>8}  (not loaded)")
                continue
            # score already includes the uplift; recover the pre-uplift score from graph_uplift
            after = members["score"].mean()
            before = (members["score"] - (members["graph_uplift"] * 1000)).clip(lower=0).mean()
            component = members["graph_signals"].apply(
                lambda g: (g or {}).get("component_size", 0)
            ).max()
            log(f"  {r['ring']:<6} {r['device_id']:<14} {len(members):>8} {int(component):>10} "
                f"{before:>13.1f} {after:>12.1f} {after - before:>8.1f}")
            ring_report.append(
                {
                    "ring": r["ring"], "device_id": r["device_id"], "members_loaded": len(members),
                    "component_size": int(component), "mean_score_before_uplift": round(float(before), 1),
                    "mean_score_after_uplift": round(float(after), 1),
                }
            )

        non_ring = loaded[~loaded["device_id"].isin(ring_devices)]
        log(f"\n  mean score, ring members : {loaded[loaded['device_id'].isin(ring_devices)]['score'].mean():.1f}")
        log(f"  mean score, everyone else: {non_ring['score'].mean():.1f}")

        section("6. Hero cases for the demo")
        heroes = pick_heroes(loaded, ring_devices)
        for label, item in heroes.items():
            if item:
                log(f"  {label:<22} score {item['score']:>4} {item['band']:<9} {item['decision_id']}")
            else:
                log(f"  {label:<22} not found in this load")

        payload = {
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "api": args.base_url,
            "rows_loaded": len(loaded),
            "heroes": heroes,
            "rings": ring_report,
        }
        DOCS_DIR.mkdir(parents=True, exist_ok=True)
        (DOCS_DIR / "demo_ids.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
        log("\n  wrote docs/demo_ids.json")

    return 0


def pick_heroes(loaded: pd.DataFrame, ring_devices: set[str]) -> dict:
    """Three cases that make the demo tell a story.

    1. A ring member that looks clean on its own — low model score, raised by the graph. This is
       the case that justifies building an entity graph at all.
    2. An obvious fraud the model catches unaided.
    3. A clean approval, so the demo shows the system is not simply suspicious of everyone.
    """

    def as_item(row) -> dict:
        return {
            "decision_id": row["decision_id"],
            "application_id": row["application_id"],
            "external_ref": row["external_ref"],
            "score": int(row["score"]),
            "band": row["band"],
            "graph_uplift": float(row["graph_uplift"]),
            "fraud_bool": row["fraud_bool"],
            "component_size": (row["graph_signals"] or {}).get("component_size"),
        }

    heroes: dict = {"clean_looking_ring_member": None, "obvious_fraud": None, "clean_approve": None}

    ring_members = loaded[loaded["device_id"].isin(ring_devices)].copy()
    if not ring_members.empty:
        ring_members["pre_uplift"] = ring_members["score"] - ring_members["graph_uplift"] * 1000
        # the most persuasive one: lowest standalone score, largest lift from the graph
        best = ring_members.sort_values(["pre_uplift", "graph_uplift"], ascending=[True, False]).iloc[0]
        heroes["clean_looking_ring_member"] = as_item(best)

    frauds = loaded[(loaded["fraud_bool"] == 1) & (~loaded["device_id"].isin(ring_devices))]
    if not frauds.empty:
        heroes["obvious_fraud"] = as_item(frauds.sort_values("score", ascending=False).iloc[0])

    clean = loaded[(loaded["fraud_bool"] == 0) & (loaded["band"] == "APPROVE")]
    if not clean.empty:
        heroes["clean_approve"] = as_item(clean.sort_values("score").iloc[0])

    return heroes


if __name__ == "__main__":
    sys.exit(main())
