"""Backfill case_embeddings for decisions already in the database (DESIGN §8).

Decisions written before the semantic layer existed — or while it was down — have no embedding,
so they are invisible to similarity search. This walks the gap in batches and is safe to re-run:
the upsert is idempotent and the worklist only ever contains decisions with no row.

Run from the repo root, against the Postgres in .env:

    python ml/scripts/backfill_embeddings.py               # everything missing
    python ml/scripts/backfill_embeddings.py --limit 500   # a slice, for a quick check
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "backend"))

# The scripts run on the host, where .env holds localhost credentials; the API runs in a container
# where compose overrides POSTGRES_HOST. Load .env before importing app config.
def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


_load_dotenv(REPO / ".env")

from app.db.session import SessionLocal  # noqa: E402
from app.semantic import repository  # noqa: E402
from app.semantic.embedder import get_embedder  # noqa: E402
from app.semantic.narrative import build_narrative, narrative_metadata  # noqa: E402

BATCH = 256


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, default=0, help="stop after this many (0 = all)")
    ap.add_argument("--batch", type=int, default=BATCH)
    args = ap.parse_args()

    started = time.perf_counter()
    db = SessionLocal()
    try:
        existing = repository.count_embeddings(db)
        print(f"case_embeddings currently holds {existing:,} rows", flush=True)

        embedder = get_embedder()
        print(f"embedder ready: {embedder.model_name}", flush=True)

        done = 0
        while True:
            take = args.batch
            if args.limit:
                take = min(take, args.limit - done)
                if take <= 0:
                    break

            rows = repository.decisions_missing_embeddings(db, limit=take)
            if not rows:
                break

            narratives = [
                build_narrative(
                    band=r["band"],
                    decision=r.get("decision"),
                    reason_codes=r.get("reason_codes"),
                    graph_signals=r.get("graph_signals"),
                    graph_uplift=r.get("graph_uplift"),
                )
                for r in rows
            ]
            vectors = embedder.encode_many(narratives)

            for row, narrative, vector in zip(rows, narratives, vectors):
                meta = narrative_metadata(
                    band=row["band"],
                    reason_codes=row.get("reason_codes"),
                    graph_signals=row.get("graph_signals"),
                )
                meta["narrative"] = narrative
                repository.upsert_embedding(db, row["decision_id"], vector, meta)
            db.commit()

            done += len(rows)
            rate = done / max(1e-9, time.perf_counter() - started)
            print(f"  embedded {done:,} ({rate:.0f}/s)", flush=True)

        total = repository.count_embeddings(db)
        elapsed = time.perf_counter() - started
        print(f"\nbackfilled {done:,} decisions in {elapsed:.1f}s")
        print(f"case_embeddings now holds {total:,} rows")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
