"""Backfill case_embeddings for decisions already in the database (DESIGN §8).

Decisions written before the semantic layer existed — or while it was down — have no embedding,
so they are invisible to similarity search. This walks the gap in batches and is safe to re-run:
the upsert is idempotent and the worklist only ever contains decisions with no row.

Run from the repo root, against the Postgres in .env:

    python ml/scripts/backfill_embeddings.py               # everything missing
    python ml/scripts/backfill_embeddings.py --limit 500   # a slice, for a quick check
    python ml/scripts/backfill_embeddings.py --recompute   # refit the corpus mean, re-embed EVERY row

    python ml/scripts/backfill_embeddings.py --fix-uncentered  # center rows written by a not-yet-restarted API

`--recompute` is the mean-centering step (see app/semantic/embedder.py): it encodes every distinct
narrative once, fits the corpus mean, writes ml/artifacts/embedding_mean_v1.json, and rewrites every
stored vector as normalise(v - mean). Run it again only if the narrative wording or the corpus
changes materially; new decisions are centered against the stored mean as they arrive.
"""

from __future__ import annotations

import argparse
import json
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
from app.semantic.embedder import (  # noqa: E402
    EMBEDDING_DIM,
    MODEL_NAME,
    center_and_normalise,
    get_embedder,
    mean_path,
)
from app.semantic.narrative import build_narrative, narrative_metadata  # noqa: E402
from sqlalchemy import text  # noqa: E402

BATCH = 256


def fix_uncentered(db, embedder) -> None:
    """Center any stored vector still in raw form, using the stored mean (no refit, no encoding).

    A process running the pre-centering code keeps writing raw vectors until it is restarted; this
    converts them. Idempotent: already-centered rows are not selected.
    """
    import numpy as np

    mean = embedder.mean
    if mean is None:
        raise SystemExit(f"{mean_path()} missing - run --recompute first")
    direction = mean / np.linalg.norm(mean)
    fixed = 0
    while True:
        rows = repository.uncentered_embeddings(db, direction.tolist(), limit=2000)
        if not rows:
            break
        vectors = center_and_normalise(np.asarray([v for _, v in rows]), mean)
        for (decision_id, _), vec in zip(rows, vectors, strict=True):
            db.execute(
                text("UPDATE case_embeddings SET embedding = CAST(:e AS vector) WHERE decision_id = :d"),
                {"e": repository._to_pgvector(vec.tolist()), "d": str(decision_id)},
            )
        db.commit()
        fixed += len(rows)
        print(f"  centered {fixed:,} rows", flush=True)
    print(f"centered {fixed:,} previously-raw rows")


def recompute(db, embedder) -> None:
    """Fit the corpus mean over every decision's narrative and rewrite all stored vectors."""
    import numpy as np

    started = time.perf_counter()
    items: list[tuple] = []  # (decision_id, narrative, metadata)
    after = None
    while True:
        page = repository.decisions_page_for_embedding(db, after, 2000)
        if not page:
            break
        for r in page:
            narrative = build_narrative(
                band=r["band"], decision=r.get("decision"), reason_codes=r.get("reason_codes"),
                graph_signals=r.get("graph_signals"), graph_uplift=r.get("graph_uplift"),
            )
            meta = narrative_metadata(
                band=r["band"], reason_codes=r.get("reason_codes"), graph_signals=r.get("graph_signals")
            )
            meta["narrative"] = narrative
            items.append((r["decision_id"], narrative, meta))
        after = page[-1]["decision_id"]
    print(f"loaded {len(items):,} decisions", flush=True)

    unique = sorted({n for _, n, _ in items})
    print(f"encoding {len(unique):,} distinct narratives (raw MiniLM)", flush=True)
    raw = embedder.encode_raw_many(unique)
    index = {n: i for i, n in enumerate(unique)}
    row_idx = np.fromiter((index[n] for _, n, _ in items), dtype=np.int64, count=len(items))

    # Mean over decisions (not over distinct narratives): the corpus is what queries are compared to.
    mean = raw[row_idx].mean(axis=0)
    centered = center_and_normalise(raw, mean)

    rng = np.random.default_rng(0)
    a, b = rng.integers(0, len(items), 100_000), rng.integers(0, len(items), 100_000)
    before = (raw[row_idx[a]] * raw[row_idx[b]]).sum(1)
    after_ = (centered[row_idx[a]] * centered[row_idx[b]]).sum(1)
    stats = {
        "random_pair_cosine_before": {"mean": float(before.mean()), "std": float(before.std())},
        "random_pair_cosine_after": {"mean": float(after_.mean()), "std": float(after_.std())},
    }

    mean_file = mean_path()
    mean_file.write_text(
        json.dumps(
            {
                "model": MODEL_NAME, "dim": EMBEDDING_DIM, "n_decisions": len(items),
                "n_distinct_narratives": len(unique), "narrative_version": 1,
                "transform": "normalise(v_unit - mean)", "stats": stats, "mean": mean.tolist(),
            }
        ),
        encoding="utf-8",
    )
    embedder.mean = mean
    print(f"wrote {mean_file}", flush=True)
    print(f"random-pair cosine: {stats['random_pair_cosine_before']} -> "
          f"{stats['random_pair_cosine_after']}", flush=True)

    for start in range(0, len(items), 500):
        for (decision_id, _, meta), i in zip(items[start:start + 500], row_idx[start:start + 500], strict=True):
            repository.upsert_embedding(db, decision_id, centered[i].tolist(), meta)
        db.commit()
        done = min(start + 500, len(items))
        if done % 5000 == 0 or done == len(items):
            print(f"  rewrote {done:,}/{len(items):,} ({time.perf_counter() - started:.0f}s)", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, default=0, help="stop after this many (0 = all)")
    ap.add_argument("--batch", type=int, default=BATCH)
    ap.add_argument("--fix-uncentered", action="store_true",
                    help="center rows still in raw form (written by an API not yet restarted)")
    ap.add_argument("--recompute", action="store_true",
                    help="refit the corpus mean and re-embed every decision (mean-centering)")
    args = ap.parse_args()

    started = time.perf_counter()
    db = SessionLocal()
    try:
        existing = repository.count_embeddings(db)
        print(f"case_embeddings currently holds {existing:,} rows", flush=True)

        embedder = get_embedder()
        print(f"embedder ready: {embedder.model_name}", flush=True)

        if args.fix_uncentered:
            fix_uncentered(db, embedder)
            return 0

        if args.recompute:
            recompute(db, embedder)
            print(f"case_embeddings now holds {repository.count_embeddings(db):,} rows")
            return 0

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

            for row, narrative, vector in zip(rows, narratives, vectors, strict=False):
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
