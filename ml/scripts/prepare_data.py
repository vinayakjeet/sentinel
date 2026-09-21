"""SENTINEL — data preparation (DESIGN §2).

Reads the Feedzai Bank Account Fraud (BAF, NeurIPS 2022) CSVs and produces every
downstream data artifact:

    data/processed/train.parquet     months 0-5 (month 5 is the early-stopping validation slice)
    data/processed/test.parquet      months 6-7
    data/processed/demo_sample.csv   150k stratified rows: every fraud + a month-proportional legit sample
    data/replay/stream_base.csv      Base test months, for the "no drift" replay
    data/replay/stream_shift.csv     Variant test months, same row count, for the drift replay
    ml/artifacts/raw_columns.json    column contract for Lane A's strict ApplicationEvent

BAF ships no identifiers, so we synthesise six of them (device_id, email, phone, ip, address,
applicant_name) from a seeded RNG and then plant four fraud rings that share a device and a phone.
This is disclosed in the README: the linkage is synthetic and exists to demonstrate the entity
graph, it is not a property of the published dataset.

Run:  python ml/scripts/prepare_data.py
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
RAW_DIR = REPO / "data" / "raw"
PROC_DIR = REPO / "data" / "processed"
REPLAY_DIR = REPO / "data" / "replay"
ARTIFACT_DIR = REPO / "ml" / "artifacts"

SEED = 20260921
VARIANT_SEED = SEED + 7919  # separate identifier namespace, so the shift stream invents its own entities

LABEL = "fraud_bool"
TIME_COL = "month"
TRAIN_MONTHS = (0, 1, 2, 3, 4, 5)
VAL_MONTH = 5
TEST_MONTHS = (6, 7)
DEMO_N = 150_000

# DESIGN §2: BAF encodes "not applicable / unknown" as -1 in these columns. We keep the -1 and add
# an explicit <col>_missing flag in featurize.py rather than imputing.
MISSING_SENTINEL = -1
SENTINEL_COLS = (
    "prev_address_months_count",
    "current_address_months_count",
    "bank_months_count",
    "session_length_in_minutes",
    "device_distinct_emails_8w",
)

CATEGORICAL_COLS = ("payment_type", "employment_status", "housing_status", "source", "device_os")
IDENTIFIER_COLS = ("device_id", "email", "phone", "ip", "address", "applicant_name")

# Fraud rings: N rings of 8-15 fraud applications each, sharing a device_id and a phone.
N_RINGS = 4
RING_MIN, RING_MAX = 8, 15
RING_IP_SHARE = 0.5  # fraction of each ring that also shares an IP

FIRST_NAMES = (
    "Aarav Aditi Ananya Arjun Bhavna Chetan Damini Devika Farhan Gaurav Harini Ishaan Jaya Kabir "
    "Kavya Lakshmi Manav Meera Naveen Nisha Omkar Pooja Pranav Priya Rahul Rakesh Ravi Riya Rohan "
    "Sanjana Shreya Siddharth Simran Tanvi Tarun Uday Varun Vikram Nandini Yash Zara Aliya Imran "
    "Nikhil Sneha Rajat Kiran Deepak"
).split()
LAST_NAMES = (
    "Agarwal Banerjee Bhatia Chandra Chopra Desai Dutta Gandhi Ghosh Gupta Iyer Jain Joshi Kapoor "
    "Kaur Khanna Kulkarni Kumar Malhotra Mehta Menon Mishra Nair Pandey Patel Pillai Rao Reddy "
    "Saxena Sharma Shetty Singh Sinha Subramanian Trivedi Varma Verma Yadav Bose Chauhan"
).split()
EMAIL_DOMAINS = ("gmail.com", "yahoo.co.in", "outlook.com", "hotmail.com", "rediffmail.com", "protonmail.com")
STREETS = (
    "MG Road", "Nehru Street", "Park Lane", "Gandhi Marg", "Church Street", "Brigade Road",
    "Linking Road", "Anna Salai", "Residency Road", "Hill View", "Lake Road", "Station Road",
)
CITIES = (
    "Mumbai", "Delhi", "Bengaluru", "Hyderabad", "Chennai", "Kolkata", "Pune", "Ahmedabad",
    "Jaipur", "Lucknow", "Kochi", "Indore",
)


def log(msg: str = "") -> None:
    print(msg, flush=True)


def section(title: str) -> None:
    log()
    log(f"{title}")
    log("-" * len(title))


def _padded(values: np.ndarray, width: int) -> np.ndarray:
    """Vectorised zero-padded string conversion (np.char is far faster than .map over 1M rows)."""
    return np.char.zfill(values.astype(str), width)


def make_identifiers(n: int, seed: int) -> pd.DataFrame:
    """Deterministic synthetic identifiers for n rows.

    Pool sizes are deliberately just under n so that a small, realistic fraction of applications
    naturally share a device/ip/address — background noise the entity graph has to cope with —
    without creating giant components. Rings are planted on top of this (see plant_rings).
    """
    rng = np.random.default_rng(seed)

    device_idx = rng.integers(0, max(1, int(n * 0.92)), size=n)
    phone_idx = rng.integers(0, max(1, int(n * 0.95)), size=n)
    ip_idx = rng.integers(0, max(1, int(n * 0.90)), size=n)
    addr_idx = rng.integers(0, max(1, int(n * 0.93)), size=n)

    first = np.asarray(FIRST_NAMES)[rng.integers(0, len(FIRST_NAMES), size=n)]
    last = np.asarray(LAST_NAMES)[rng.integers(0, len(LAST_NAMES), size=n)]
    applicant_name = np.char.add(np.char.add(first, " "), last)

    email_num = rng.integers(1, 9999, size=n)
    domains = np.asarray(EMAIL_DOMAINS)[rng.integers(0, len(EMAIL_DOMAINS), size=n)]
    local = np.char.add(
        np.char.add(np.char.add(np.char.lower(first), "."), np.char.lower(last)),
        email_num.astype(str),
    )
    email = np.char.add(np.char.add(local, "@"), domains)

    # Private (RFC 1918) space only — never anything that could be mistaken for a routable address.
    ip = np.char.add(
        "10.",
        np.char.add(
            np.char.add((ip_idx // 65536 % 254 + 1).astype(str), "."),
            np.char.add(np.char.add((ip_idx // 256 % 256).astype(str), "."), (ip_idx % 256).astype(str)),
        ),
    )

    house = (addr_idx % 900 + 1).astype(str)
    street = np.asarray(STREETS)[addr_idx % len(STREETS)]
    city = np.asarray(CITIES)[(addr_idx // 7) % len(CITIES)]
    address = np.char.add(
        np.char.add(np.char.add(house, " "), street),
        np.char.add(", ", city),
    )

    return pd.DataFrame(
        {
            "device_id": np.char.add("DEV-", _padded(device_idx, 8)),
            "email": email,
            "phone": np.char.add("+91", _padded(phone_idx + 6000000000, 10)),
            "ip": ip,
            "address": address,
            "applicant_name": applicant_name,
        }
    )


def plant_rings(df: pd.DataFrame, seed: int) -> list[dict]:
    """Overwrite identifiers on N_RINGS groups of fraud rows so each group shares a device + phone.

    Mutates df in place. Returns one summary dict per ring.
    """
    rng = np.random.default_rng(seed + 1)
    fraud_pos = np.flatnonzero(df[LABEL].to_numpy() == 1)
    if len(fraud_pos) < N_RINGS * RING_MAX:
        raise SystemExit(f"not enough fraud rows ({len(fraud_pos)}) to plant {N_RINGS} rings")

    chosen = rng.choice(fraud_pos, size=N_RINGS * RING_MAX, replace=False)
    rings: list[dict] = []
    cursor = 0
    for r in range(N_RINGS):
        size = int(rng.integers(RING_MIN, RING_MAX + 1))
        members = chosen[cursor : cursor + size]
        cursor += size

        device = f"DEV-RING{r + 1:02d}"
        phone = f"+91{9900000000 + r}"
        df.iloc[members, df.columns.get_loc("device_id")] = device
        df.iloc[members, df.columns.get_loc("phone")] = phone

        n_ip = max(2, int(size * RING_IP_SHARE))
        shared_ip = f"10.99.{r + 1}.{r + 1}"
        df.iloc[members[:n_ip], df.columns.get_loc("ip")] = shared_ip

        months = sorted(df.iloc[members][TIME_COL].unique().tolist())
        rings.append(
            {
                "ring": r + 1,
                "size": size,
                "device_id": device,
                "phone": phone,
                "shared_ip": shared_ip,
                "members_sharing_ip": n_ip,
                "months": months,
                "row_positions": members.tolist(),
            }
        )
    return rings


def build_raw_columns_contract(df: pd.DataFrame, n_rows: int) -> dict:
    """Column contract for Lane A's strict Pydantic ApplicationEvent (bounds come from real data)."""
    columns: dict[str, dict] = {}
    for col in df.columns:
        if col in IDENTIFIER_COLS:
            continue
        s = df[col]
        if col in CATEGORICAL_COLS:
            columns[col] = {
                "kind": "categorical",
                "dtype": "str",
                "categories": sorted(s.dropna().unique().tolist()),
            }
        else:
            arr = s.to_numpy()
            is_int = np.issubdtype(arr.dtype, np.integer) or bool((arr == arr.astype(np.int64)).all())
            columns[col] = {
                "kind": "numeric",
                "dtype": "int" if is_int else "float",
                "min": float(np.min(arr)),
                "max": float(np.max(arr)),
                "n_unique": int(s.nunique()),
                "has_missing_sentinel": bool((arr == MISSING_SENTINEL).any()),
            }
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "data/raw/Base.csv (Feedzai BAF, NeurIPS 2022)",
        "n_rows": int(n_rows),
        "label_column": LABEL,
        "time_column": TIME_COL,
        "train_months": list(TRAIN_MONTHS),
        "validation_month": VAL_MONTH,
        "test_months": list(TEST_MONTHS),
        "missing_sentinel": MISSING_SENTINEL,
        "missing_sentinel_columns": list(SENTINEL_COLS),
        "categorical_columns": list(CATEGORICAL_COLS),
        "protected_attributes_never_features": ["customer_age", "employment_status", "income"],
        "identifier_columns": {
            "note": "synthetic, generated by ml/scripts/prepare_data.py; not part of published BAF",
            "columns": list(IDENTIFIER_COLS),
            "dtype": "str",
        },
        "columns": columns,
    }


def report_raw(df: pd.DataFrame) -> None:
    section("1. Raw dataset")
    n = len(df)
    n_fraud = int(df[LABEL].sum())
    log(f"shape                : {df.shape[0]:,} rows x {df.shape[1]} columns")
    log(f"fraud_bool = 1       : {n_fraud:,}  ({n_fraud / n * 100:.3f}%)")
    log(f"months present       : {sorted(df[TIME_COL].unique().tolist())}")

    section("2. Missing sentinel (-1) counts")
    found_any = False
    for col in df.columns:
        if df[col].dtype.kind not in "ifu":
            continue
        cnt = int((df[col] == MISSING_SENTINEL).sum())
        if cnt:
            found_any = True
            flag = "  <- flagged in featurize" if col in SENTINEL_COLS else "  <- real value, not a sentinel (column range is genuinely negative)"
            log(f"  {col:<34} {cnt:>9,}  ({cnt / n * 100:5.2f}%){flag}")
    if not found_any:
        log("  none found")

    section("3. Fraud rate by month")
    by_month = df.groupby(TIME_COL)[LABEL].agg(["size", "sum"])
    by_month["rate_pct"] = by_month["sum"] / by_month["size"] * 100
    log(f"  {'month':>5}  {'rows':>9}  {'frauds':>7}  {'rate %':>7}  split")
    for month, row in by_month.iterrows():
        split = "test" if month in TEST_MONTHS else ("train+val" if month == VAL_MONTH else "train")
        log(f"  {month:>5}  {int(row['size']):>9,}  {int(row['sum']):>7,}  {row['rate_pct']:>7.3f}  {split}")


def build_demo_sample(df: pd.DataFrame, seed: int) -> pd.DataFrame:
    """Every fraud row + a month-proportional legit sample, to DEMO_N rows total."""
    rng = np.random.default_rng(seed + 2)
    fraud = df[df[LABEL] == 1]
    legit = df[df[LABEL] == 0]
    n_legit = DEMO_N - len(fraud)
    if n_legit <= 0:
        raise SystemExit(f"DEMO_N={DEMO_N} is smaller than the fraud count {len(fraud)}")

    share = legit[TIME_COL].value_counts(normalize=True).sort_index()
    picks = []
    for month, frac in share.items():
        pool = legit.index[legit[TIME_COL] == month].to_numpy()
        take = min(len(pool), int(round(n_legit * frac)))
        picks.append(rng.choice(pool, size=take, replace=False))
    legit_idx = np.concatenate(picks)

    # rounding can leave us a few short or long; correct against the untouched remainder
    if len(legit_idx) < n_legit:
        remainder = np.setdiff1d(legit.index.to_numpy(), legit_idx, assume_unique=False)
        extra = rng.choice(remainder, size=n_legit - len(legit_idx), replace=False)
        legit_idx = np.concatenate([legit_idx, extra])
    elif len(legit_idx) > n_legit:
        legit_idx = rng.choice(legit_idx, size=n_legit, replace=False)

    demo = pd.concat([fraud, df.loc[legit_idx]]).sort_values(TIME_COL, kind="stable")
    return demo.reset_index(drop=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base", default=str(RAW_DIR / "Base.csv"))
    ap.add_argument("--variant", default=None, help="defaults to the first 'Variant *.csv' in data/raw/")
    args = ap.parse_args()

    started = time.perf_counter()
    base_path = Path(args.base)
    if args.variant:
        variant_path = Path(args.variant)
    else:
        candidates = sorted(RAW_DIR.glob("Variant *.csv"))
        if not candidates:
            raise SystemExit(f"no 'Variant *.csv' found in {RAW_DIR}")
        variant_path = candidates[0]

    for p in (base_path, variant_path):
        if not p.exists():
            raise SystemExit(f"missing input file: {p}")

    for d in (PROC_DIR, REPLAY_DIR, ARTIFACT_DIR):
        d.mkdir(parents=True, exist_ok=True)

    log("=" * 78)
    log("SENTINEL - prepare_data (DESIGN section 2)")
    log("=" * 78)
    log(f"base    : {base_path.name}")
    log(f"variant : {variant_path.name}")
    log(f"seed    : {SEED}")

    df = pd.read_csv(base_path)
    report_raw(df)

    section("4. Synthetic identifiers + planted fraud rings")
    ids = make_identifiers(len(df), SEED)
    df = pd.concat([df, ids], axis=1)
    rings = plant_rings(df, SEED)
    for r in rings:
        log(
            f"  ring {r['ring']}: {r['size']:>2} fraud rows | device={r['device_id']} "
            f"phone={r['phone']} | {r['members_sharing_ip']} share ip {r['shared_ip']} | months={r['months']}"
        )
    # acceptance assertions — a silently broken ring would waste Lane A's entity-graph demo
    for r in rings:
        members = df.iloc[r["row_positions"]]
        assert members["device_id"].nunique() == 1, f"ring {r['ring']} device not shared"
        assert members["phone"].nunique() == 1, f"ring {r['ring']} phone not shared"
        assert (members[LABEL] == 1).all(), f"ring {r['ring']} contains a non-fraud row"
    log(f"  asserted: all {N_RINGS} rings share one device_id and one phone, all members are fraud")

    shared_dev = int((df["device_id"].value_counts() > 1).sum())
    log(f"  background device sharing: {shared_dev:,} device_ids used by >1 application")

    section("5. Temporal split (DESIGN section 2 - never random)")
    train = df[df[TIME_COL].isin(TRAIN_MONTHS)].reset_index(drop=True)
    test = df[df[TIME_COL].isin(TEST_MONTHS)].reset_index(drop=True)
    assert set(train[TIME_COL]).isdisjoint(set(test[TIME_COL])), "train/test months overlap"
    train.to_parquet(PROC_DIR / "train.parquet", index=False)
    test.to_parquet(PROC_DIR / "test.parquet", index=False)
    log(f"  train.parquet : {len(train):>9,} rows  months {sorted(int(m) for m in train[TIME_COL].unique())}  "
        f"fraud {train[LABEL].mean() * 100:.3f}%")
    log(f"  test.parquet  : {len(test):>9,} rows  months {sorted(int(m) for m in test[TIME_COL].unique())}  "
        f"fraud {test[LABEL].mean() * 100:.3f}%")
    log(f"  (month {VAL_MONTH} inside train is the early-stopping validation slice - train.py splits it)")

    section("6. Demo sample")
    demo = build_demo_sample(df, SEED)
    demo.to_csv(PROC_DIR / "demo_sample.csv", index=False)
    n_ring_rows = sum(r["size"] for r in rings)
    ring_devices = {r["device_id"] for r in rings}
    ring_in_demo = int(demo["device_id"].isin(ring_devices).sum())
    log(f"  demo_sample.csv: {len(demo):>9,} rows  fraud {demo[LABEL].mean() * 100:.3f}% "
        f"({int(demo[LABEL].sum()):,} frauds)")
    log(f"  all frauds present: {int(demo[LABEL].sum()) == int(df[LABEL].sum())}")
    log(f"  ring members present: {ring_in_demo}/{n_ring_rows}")
    assert ring_in_demo == n_ring_rows, "ring members missing from demo_sample"

    section("7. Replay streams (DESIGN section 2)")
    variant = pd.read_csv(variant_path)
    variant = pd.concat([variant, make_identifiers(len(variant), VARIANT_SEED)], axis=1)
    base_stream = df[df[TIME_COL].isin(TEST_MONTHS)].reset_index(drop=True)
    shift_stream = variant[variant[TIME_COL].isin(TEST_MONTHS)].reset_index(drop=True)
    n_stream = min(len(base_stream), len(shift_stream))
    base_stream = base_stream.iloc[:n_stream]
    shift_stream = shift_stream.iloc[:n_stream]
    base_stream.to_csv(REPLAY_DIR / "stream_base.csv", index=False)
    shift_stream.to_csv(REPLAY_DIR / "stream_shift.csv", index=False)
    log(f"  stream_base.csv : {len(base_stream):>9,} rows  fraud {base_stream[LABEL].mean() * 100:.3f}%  (Base, months {list(TEST_MONTHS)})")
    log(f"  stream_shift.csv: {len(shift_stream):>9,} rows  fraud {shift_stream[LABEL].mean() * 100:.3f}%  ({variant_path.name}, months {list(TEST_MONTHS)})")
    log("  identifiers in the shift stream use a separate seed, so it brings its own entities")

    # a quick, honest look at whether the variant actually shifts — Lane A's ADWIN demo depends on it
    section("8. Distribution shift check (base vs shift)")
    log(f"  {'column':<34} {'base mean':>12} {'shift mean':>12} {'rel change':>11}")
    movers = []
    for col in base_stream.columns:
        if col in IDENTIFIER_COLS or col in CATEGORICAL_COLS or col == TIME_COL:
            continue
        b, s = base_stream[col].mean(), shift_stream[col].mean()
        if b != 0 and np.isfinite(b) and np.isfinite(s):
            movers.append((abs((s - b) / abs(b)), col, b, s))
    movers.sort(reverse=True)
    for rel, col, b, s in movers[:8]:
        log(f"  {col:<34} {b:>12.4f} {s:>12.4f} {rel * 100:>10.1f}%")
    log(f"  (largest movers shown; Lane A's A5 needs a visible shift for ADWIN to fire)")

    section("9. Column contract for Lane A")
    contract = build_raw_columns_contract(df, len(df))
    contract_path = ARTIFACT_DIR / "raw_columns.json"
    contract_path.write_text(json.dumps(contract, indent=2), encoding="utf-8")
    log(f"  wrote {contract_path.relative_to(REPO)} - {len(contract['columns'])} raw columns "
        f"+ {len(IDENTIFIER_COLS)} synthetic identifiers")

    ring_meta = ARTIFACT_DIR / "fraud_rings.json"
    ring_meta.write_text(
        json.dumps([{k: v for k, v in r.items() if k != "row_positions"} for r in rings], indent=2),
        encoding="utf-8",
    )
    log(f"  wrote {ring_meta.relative_to(REPO)} - ring devices/phones for the B4 demo")

    section("Done")
    for p in (
        PROC_DIR / "train.parquet",
        PROC_DIR / "test.parquet",
        PROC_DIR / "demo_sample.csv",
        REPLAY_DIR / "stream_base.csv",
        REPLAY_DIR / "stream_shift.csv",
        ARTIFACT_DIR / "raw_columns.json",
        ARTIFACT_DIR / "fraud_rings.json",
    ):
        log(f"  {p.relative_to(REPO).as_posix():<40} {p.stat().st_size / 1e6:>8.1f} MB")
    log(f"\nelapsed: {time.perf_counter() - started:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
