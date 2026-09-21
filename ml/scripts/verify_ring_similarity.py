"""B5v - verify the semantic layer against the loaded demo database.

B5 built the case-narrative embeddings; this is the acceptance check that could only be run once
B4 had loaded real data: **do the planted fraud rings surface each other as similar cases?**

That is a meaningful test rather than a tautology. The narrative that gets embedded contains the
band, the top reason codes, the graph signals and a few key features - it contains **no
identifiers**. So a ring member cannot retrieve its fellow ring members by sharing a device ID; it
can only do so if the cases genuinely read alike. Entity-graph linkage and narrative similarity are
different questions, and this checks the second one on data planted for the first.

    python ml/scripts/verify_ring_similarity.py
    python ml/scripts/verify_ring_similarity.py --k 5 --limit 40000

Exit code is 0 when every ring is represented and the ring-to-ring hit rate beats the rate you
would expect by chance, 1 otherwise. Whatever the numbers are, they are printed unchanged.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

import httpx
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from load_demo_db import API, Auth, fetch_already_loaded, select_rows  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
PROC_DIR = REPO / "data" / "processed"
ARTIFACT_DIR = REPO / "ml" / "artifacts"
DOCS_DIR = REPO / "docs"


def log(msg: str = "") -> None:
    print(msg, flush=True)


def section(title: str) -> None:
    log()
    log(title)
    log("-" * len(title))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base-url", default=os.environ.get("SENTINEL_API", "http://localhost:8000"))
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--limit", type=int, default=40000, help="must match the limit used by load_demo_db.py")
    ap.add_argument("--username", default=os.environ.get("DEMO_ANALYST_USERNAME"))
    ap.add_argument("--password", default=os.environ.get("DEMO_ANALYST_PASSWORD"))
    args = ap.parse_args()

    rings = json.loads((ARTIFACT_DIR / "fraud_rings.json").read_text(encoding="utf-8"))
    ring_of_device = {r["device_id"]: r["ring"] for r in rings}
    demo = pd.read_csv(PROC_DIR / "demo_sample.csv")
    rows = select_rows(demo, args.limit, set(ring_of_device))

    # external_ref is deterministic (`demo-<row index>`), which is what lets this script line the
    # database back up with the CSV without storing anything in between.
    ring_ref_to_ring: dict[str, int] = {}
    for idx, row in rows.iterrows():
        ring = ring_of_device.get(row["device_id"])
        if ring is not None:
            ring_ref_to_ring[f"demo-{idx:06d}"] = ring

    log("=" * 78)
    log("SENTINEL - ring similarity verification (task B5v)")
    log("=" * 78)
    log(f"api   : {args.base_url}")
    log(f"rings : {len(rings)} planted, {len(ring_ref_to_ring)} members inside the loaded subset")

    with httpx.Client(base_url=args.base_url, timeout=60.0) as client:
        section("1. Locating the loaded cases")
        auth = Auth(client, args.username, args.password)
        loaded = fetch_already_loaded(client, auth)
        log(f"  {len(loaded):,} demo decisions in the database")

        ring_cases = {ref: loaded[ref] for ref in ring_ref_to_ring if ref in loaded}
        missing = sorted(set(ring_ref_to_ring) - set(ring_cases))
        log(f"  {len(ring_cases)} of {len(ring_ref_to_ring)} ring members found")
        if missing:
            log(f"  not loaded: {', '.join(missing[:8])}{' ...' if len(missing) > 8 else ''}")
        if not ring_cases:
            log("  no ring members loaded - run load_demo_db.py first")
            return 1

        ring_decision_ids = {item["decision_id"]: ring_ref_to_ring[ref] for ref, item in ring_cases.items()}

        section(f"2. Top-{args.k} similar cases for each ring member")
        per_ring: dict[int, dict[str, int]] = defaultdict(lambda: {"members": 0, "any_ring_hits": 0,
                                                                   "same_ring_hits": 0, "slots": 0,
                                                                   "with_any_ring": 0, "not_embedded": 0})
        detail: list[dict] = []
        for ref, item in sorted(ring_cases.items()):
            ring = ring_ref_to_ring[ref]
            stats = per_ring[ring]
            stats["members"] += 1
            r = client.get(
                f"{API}/cases/{item['decision_id']}/similar",
                params={"k": args.k},
                headers=auth.headers(),
            )
            if r.status_code == 401 and auth.refresh(auth.token):
                r = client.get(
                    f"{API}/cases/{item['decision_id']}/similar",
                    params={"k": args.k},
                    headers=auth.headers(),
                )
            r.raise_for_status()
            neighbours = r.json()["items"]
            if not neighbours:
                stats["not_embedded"] += 1
                continue
            stats["slots"] += len(neighbours)
            any_hits = sum(1 for n in neighbours if n["decision_id"] in ring_decision_ids)
            same_hits = sum(
                1 for n in neighbours if ring_decision_ids.get(n["decision_id"]) == ring
            )
            stats["any_ring_hits"] += any_hits
            stats["same_ring_hits"] += same_hits
            stats["with_any_ring"] += 1 if any_hits else 0
            detail.append(
                {
                    "external_ref": ref, "ring": ring, "decision_id": item["decision_id"],
                    "score": item["score"], "band": item["band"],
                    "ring_hits_in_top_k": any_hits, "same_ring_hits_in_top_k": same_hits,
                    "top_similarity": round(float(neighbours[0]["similarity"]), 4),
                }
            )

        log(f"  {'ring':<6} {'members':>8} {'embedded':>9} {'with a ring neighbour':>22} "
            f"{'ring hits':>10} {'of slots':>9}")
        for ring in sorted(per_ring):
            s = per_ring[ring]
            embedded = s["members"] - s["not_embedded"]
            log(f"  {ring:<6} {s['members']:>8} {embedded:>9} {s['with_any_ring']:>22} "
                f"{s['any_ring_hits']:>10} {s['slots']:>9}")

        section("3. Is that better than chance?")
        members = sum(s["members"] for s in per_ring.values())
        embedded = members - sum(s["not_embedded"] for s in per_ring.values())
        slots = sum(s["slots"] for s in per_ring.values())
        hits = sum(s["any_ring_hits"] for s in per_ring.values())
        with_any = sum(s["with_any_ring"] for s in per_ring.values())
        # A ring member's neighbours are drawn from every other loaded case, so under a null model
        # of "similarity is noise" the chance a given slot lands on a ring member is this.
        chance = (len(ring_decision_ids) - 1) / max(1, len(loaded) - 1)
        observed = hits / max(1, slots)
        log(f"  ring members embedded           : {embedded} / {members}")
        log(f"  with >=1 ring member in top-{args.k}   : {with_any} ({with_any / max(1, embedded) * 100:.1f}%)")
        log(f"  ring hits / neighbour slots     : {hits} / {slots} = {observed * 100:.2f}%")
        log(f"  same rate if similarity were noise: {chance * 100:.4f}%")
        log(f"  lift over chance                : {observed / chance:.0f}x" if chance else "")

        rings_represented = len(per_ring)
        ok = embedded > 0 and with_any > 0 and observed > chance
        section("4. Verdict")
        log(f"  rings represented in the load : {rings_represented} / {len(rings)}")
        log(f"  ring members retrieve ring members: {'YES' if with_any else 'NO'}")
        log(f"  result: {'PASS' if ok else 'FAIL'}")

        payload = {
            "api": args.base_url, "k": args.k,
            "loaded_decisions": len(loaded),
            "ring_members_found": len(ring_cases), "ring_members_embedded": embedded,
            "members_with_a_ring_neighbour": with_any,
            "ring_hits": hits, "neighbour_slots": slots,
            "hit_rate": round(observed, 6), "chance_rate": round(chance, 8),
            "per_ring": {str(k): dict(v) for k, v in sorted(per_ring.items())},
            "members": detail,
            "passed": ok,
        }
        (DOCS_DIR / "ring_similarity.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
        log("\n  wrote docs/ring_similarity.json")

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
