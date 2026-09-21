"""Remove replay-generated rows from the database. Not run in the 22 Sep QA pass: it deletes data, so it needs an OK.

Why it exists: before the replay-isolation fix, every replay pass re-scored the same CSV rows with the same synthetic
identifiers (the stream restarts at row 0 whenever the API restarts or the source is switched), so passes linked to
the 40,000 loaded decisions and to each other. Those `base-*` / `shift-*` rows (52,910 of 93,034 applications at the
time of writing) are still in the database. They no longer affect new replays (each pass now has its own identifiers),
but they:

  * crowd the Alert queue (its top rows are shifted-stream 1000-score declines),
  * sit in hero 1's "Similar past cases" (a replay decline at 800 is now its nearest neighbour),
  * inflate the DECLINE / REVIEW counts on the Alert queue.

Deletes applications whose external_ref starts with `base-` or `shift-`. Their decisions, entity links and case
embeddings go with them through ON DELETE CASCADE; entities that nothing links to any more are removed afterwards.
Left alone: the 40,000 `demo-` rows and the hero cases, the latency/idle probes, `audit_log` (which still records that
every replay decision was made) and `drift_events`.

    python ml/scripts/purge_replay.py            # dry run: counts only
    python ml/scripts/purge_replay.py --apply    # delete (stop the replay first)
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "backend"))


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


_load_dotenv(REPO / ".env")

from app.db.session import SessionLocal  # noqa: E402
from sqlalchemy import text  # noqa: E402

REPLAY = "(external_ref LIKE 'base-%' OR external_ref LIKE 'shift-%')"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="delete (default is a dry run)")
    args = ap.parse_args()

    with SessionLocal() as db:
        n_apps = db.execute(text(f"SELECT count(*) FROM applications WHERE {REPLAY}")).scalar_one()
        n_total = db.execute(text("SELECT count(*) FROM applications")).scalar_one()
        print(f"replay applications: {n_apps} of {n_total}")
        if not args.apply:
            print("dry run; pass --apply to delete them")
            return 0
        db.execute(text(f"DELETE FROM applications WHERE {REPLAY}"))
        orphans = db.execute(
            text("DELETE FROM entities e WHERE NOT EXISTS (SELECT 1 FROM entity_links l WHERE l.entity_id = e.id)")
        ).rowcount
        db.commit()
        left = db.execute(text("SELECT count(*) FROM applications")).scalar_one()
        print(f"deleted {n_apps} replay applications and {orphans} orphaned entities; {left} applications remain")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
