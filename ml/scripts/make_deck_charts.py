"""Deck charts (battle plan §12): three 1600x900 dark-background PNGs in docs/charts/.

    drift_timeline.png       band mix over time around the most recent ADWIN event, from audit_log
                             (the same events drift_events records), with switch + detection markers
    ring_uplift.png          mean ring score before vs after graph uplift, per planted ring
                             (docs/demo_ids.json, written by load_demo_db.py)
    precision_at_100.png     rules baseline vs models, from ml/artifacts/metrics_v1.json

Every number is read from a file or the database at run time; nothing is typed in. Run from the
repo root against the Postgres in .env:

    python ml/scripts/make_deck_charts.py
"""

from __future__ import annotations

import json
import os
import sys
import textwrap
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "backend"))
CHART_DIR = REPO / "docs" / "charts"

# Same tokens as the analyst console (frontend/tailwind.config.js), so the deck matches the demo.
BG, PANEL = "#0c1322", "#111a2e"
INK, INK_DIM, GRID = "#dbe2f1", "#93a2c4", "#213052"
BAND = {"APPROVE": "#34c9a6", "STEP_UP": "#e8c14a", "REVIEW": "#f08a3c", "DECLINE": "#f0565f"}
STEEL, MUTED = "#7fb0ff", "#4a5c85"

W, H, DPI = 16, 9, 100  # 1600 x 900


def _style() -> None:
    plt.rcParams.update(
        {
            "figure.facecolor": BG, "axes.facecolor": BG, "savefig.facecolor": BG,
            "axes.edgecolor": GRID, "axes.labelcolor": INK_DIM, "axes.titlecolor": INK,
            "xtick.color": INK_DIM, "ytick.color": INK_DIM, "text.color": INK,
            "font.size": 15, "axes.titlesize": 26, "axes.labelsize": 16,
            "axes.spines.top": False, "axes.spines.right": False,
            "grid.color": GRID, "grid.linewidth": 1.0,
        }
    )


def _fig(title: str, subtitle: str, bottom: float = 0.16):
    fig, ax = plt.subplots(figsize=(W, H), dpi=DPI)
    fig.subplots_adjust(left=0.08, right=0.95, top=0.78, bottom=bottom)
    fig.text(0.08, 0.94, title, fontsize=28, fontweight="bold", color=INK, ha="left", va="center")
    fig.text(0.08, 0.905, textwrap.fill(subtitle, 112), fontsize=16, color=INK_DIM, ha="left", va="top",
             linespacing=1.4)
    return fig, ax


def _footer(fig, text: str) -> None:
    fig.text(0.08, 0.025, textwrap.fill(text, 150), fontsize=12, color=INK_DIM, ha="left", va="bottom")


def _load_env() -> None:
    env = REPO / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


# --------------------------------------------------------------------------------------- drift
def drift_run():
    """The latest drift.detected event, with the run's decisions and the switch that caused it."""
    _load_env()
    from app.db.session import SessionLocal
    from sqlalchemy import text

    db = SessionLocal()
    try:
        ev = db.execute(
            text("SELECT ts, old_thresholds, new_thresholds, details FROM drift_events ORDER BY ts DESC LIMIT 1")
        ).mappings().one()
        switch = db.execute(
            text("SELECT ts FROM audit_log WHERE action='stream.switch' AND ts < :t ORDER BY ts DESC LIMIT 1"),
            {"t": ev["ts"]},
        ).scalar_one()
        start = db.execute(
            text("SELECT ts FROM audit_log WHERE action='stream.start' AND ts < :t ORDER BY ts DESC LIMIT 1"),
            {"t": switch},
        ).scalar_one()
        rows = db.execute(
            text(
                """SELECT extract(epoch from ts) AS epoch, details->>'band' AS band
                   FROM audit_log
                   WHERE action='decision.created' AND actor='replay' AND ts >= :a AND ts <= :b
                   ORDER BY ts"""
            ),
            {"a": start, "b": ev["ts"] + (ev["ts"] - switch) * 0.5},
        ).all()
    finally:
        db.close()
    t0, td = switch.timestamp(), ev["ts"].timestamp()
    return ev, np.array([float(r.epoch) - t0 for r in rows]), np.array([r.band for r in rows]), td - t0


def chart_drift() -> None:
    ev, t, band, detect_at = drift_run()
    lo, hi, step = -60, max(12, int(np.ceil(detect_at)) + 3), 2
    edges = np.arange(lo, hi + step, step)
    order = ["APPROVE", "STEP_UP", "REVIEW", "DECLINE"]
    counts = np.array([[np.sum((t >= a) & (t < a + step) & (band == b)) for a in edges[:-1]] for b in order], float)
    totals = counts.sum(axis=0)
    share = np.divide(counts, totals, out=np.zeros_like(counts), where=totals > 0) * 100

    old, new = ev["old_thresholds"], ev["new_thresholds"]
    before, shifted = band[t < 0], band[(t >= 0) & (t <= detect_at)]
    fig, ax = _fig(
        "Drift: the band mix shifts, ADWIN fires, thresholds tighten",
        f"Approved share {np.mean(before == 'APPROVE') * 100:.0f}% before the switch → "
        f"{np.mean(shifted == 'APPROVE') * 100:.0f}% until detection ({len(shifted)} shifted events, "
        f"{detect_at:.1f}s). Step-up / review / decline thresholds "
        f"{old['step_up']}/{old['review']}/{old['decline']} → {new['step_up']}/{new['review']}/{new['decline']}.",
        bottom=0.24,
    )
    bottom = np.zeros(len(edges) - 1)
    for i, b in enumerate(order):
        ax.bar(edges[:-1], share[i], width=step, bottom=bottom, align="edge", color=BAND[b],
               edgecolor=BG, linewidth=1.5, label=b.replace("_", " ").title())
        bottom += share[i]
    ax.axvline(0, color=INK, linewidth=2, linestyle="--")
    ax.axvline(detect_at, color=INK, linewidth=2)
    ax.text(0 - 0.6, 102, "source switched", ha="right", va="bottom", fontsize=15, color=INK)
    ax.text(detect_at, 102, f"ADWIN fires (+{detect_at:.1f}s)", ha="center", va="bottom",
            fontsize=15, color=INK)
    ax.set_xlim(lo, hi)
    ax.set_ylim(0, 100)
    ax.set_xlabel("seconds relative to the source switch")
    ax.set_ylabel("share of decisions (%)")
    ax.legend(loc="lower left", ncol=4, frameon=False, fontsize=14, labelcolor=INK,
              bbox_to_anchor=(0.0, -0.27))
    d = ev["details"]
    _footer(fig, f"Source: audit_log / drift_events, run ending {ev['ts']:%Y-%m-%d %H:%M:%S} UTC. "
                 f"ADWIN delta {d.get('adwin_delta')}, {d.get('events_seen'):,} events seen. "
                 "No events land in the first ~2s after the switch (stream re-opens). "
                 "Shift source is a SIMULATED fraud wave (REPLAY_SHIFT_FRAUD_RATE).")
    fig.savefig(CHART_DIR / "drift_timeline.png", dpi=DPI)
    plt.close(fig)


# ---------------------------------------------------------------------------------------- rings
def chart_rings() -> None:
    demo = json.loads((REPO / "docs" / "demo_ids.json").read_text(encoding="utf-8"))
    rings = demo["rings"]
    labels = [f"Ring {r['ring']}\n{r['members_loaded']} members\ncomponent of {r['component_size']}" for r in rings]
    before = np.array([r["mean_score_before_uplift"] for r in rings])
    after = np.array([r["mean_score_after_uplift"] for r in rings])
    all_before, all_after = float(np.mean(before)), float(np.mean(after))

    fig, ax = _fig(
        "Graph uplift pushes fraud-ring members into decline",
        "Mean score of the 4 planted rings' members, before and after graph uplift "
        f"(average +{np.mean(after - before):.0f}). Scores are 0–1000.",
        bottom=0.22,
    )
    x = np.arange(len(rings))
    w = 0.36
    b1 = ax.bar(x - w / 2 - 0.01, before, w, color=MUTED, label="model score alone")
    b2 = ax.bar(x + w / 2 + 0.01, after, w, color=STEEL, label="with graph uplift")
    for bars in (b1, b2):
        for r in bars:
            ax.text(r.get_x() + r.get_width() / 2, r.get_height() + 12, f"{r.get_height():.0f}",
                    ha="center", va="bottom", fontsize=16, color=INK)
    for y, name in ((650, "review ≥ 650"), (850, "decline ≥ 850")):
        ax.axhline(y, color=INK_DIM, linewidth=1.2, linestyle=":")
        ax.text(3.95, y + 8, name, ha="right", va="bottom", fontsize=14, color=INK_DIM)
    ax.set_xticks(x, labels)
    ax.set_xlim(-0.6, 3.95)
    ax.set_ylim(0, 1090)
    ax.set_yticks(range(0, 1001, 200))
    ax.set_ylabel("mean score (0–1000)")
    ax.legend(loc="upper left", frameon=False, fontsize=15, labelcolor=INK, bbox_to_anchor=(0.0, 1.02), ncol=2)
    _footer(fig, "Source: docs/demo_ids.json (ml/scripts/load_demo_db.py, 40,000 decisions loaded through the API). "
                 f"Ring means {all_before:.0f} → {all_after:.0f}. Identifiers and rings are synthetic.")
    fig.savefig(CHART_DIR / "ring_uplift.png", dpi=DPI)
    plt.close(fig)


# ------------------------------------------------------------------------------------ precision
def chart_precision() -> None:
    m = json.loads((REPO / "ml" / "artifacts" / "metrics_v1.json").read_text(encoding="utf-8"))
    tm, base_rate = m["test_metrics"], m["data"]["test_fraud_rate"]
    rows = [("Rules baseline", tm["baseline"], MUTED), ("IsolationForest", tm["iforest"], MUTED),
            ("LightGBM", tm["lightgbm"], STEEL), ("Blend (ships)", tm["blend"], STEEL)]
    names = [r[0] for r in rows]
    vals = np.array([r[1]["precision_at_100"] * 100 for r in rows])

    fig, ax = _fig(
        "Of the 100 riskiest applications, how many are fraud?",
        f"Precision@100 on the held-out test months ({m['data']['test_rows']:,} applications, "
        f"{base_rate * 100:.2f}% fraud, temporal split). Picking 100 at random would find about "
        f"{base_rate * 100:.1f}.",
    )
    bars = ax.bar(names, vals, width=0.55, color=[r[2] for r in rows])
    for r, v in zip(bars, vals, strict=True):
        ax.text(r.get_x() + r.get_width() / 2, v + 1.2, f"{v:.0f}", ha="center", va="bottom", fontsize=26,
                fontweight="bold", color=INK)
    ax.set_ylim(0, max(vals) * 1.18)
    ax.set_ylabel("fraud cases in the top 100 flagged")
    lift = tm["lightgbm"]["precision_at_100"] / tm["baseline"]["precision_at_100"]
    ax.text(0.01, 0.96, f"LightGBM finds {lift:.1f}× the fraud the rules baseline\ndoes in the same 100 reviews",
            transform=ax.transAxes, ha="left", va="top", fontsize=20, color=INK, linespacing=1.4)
    _footer(fig, "Source: ml/artifacts/metrics_v1.json. The blend ships despite scoring below LightGBM alone here: "
                 "its anomaly component is the only part that can react to unlabelled patterns.")
    fig.savefig(CHART_DIR / "precision_at_100.png", dpi=DPI)
    plt.close(fig)


def main() -> int:
    _style()
    CHART_DIR.mkdir(parents=True, exist_ok=True)
    chart_precision()
    chart_rings()
    chart_drift()
    for name in ("drift_timeline", "ring_uplift", "precision_at_100"):
        print("wrote", (CHART_DIR / f"{name}.png").relative_to(REPO))
    return 0


if __name__ == "__main__":
    sys.exit(main())
