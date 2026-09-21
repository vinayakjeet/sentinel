import threading
import time
from collections import deque

import numpy as np

from app.schemas.decision import Band
from app.schemas.metrics import MetricsResponse

WINDOW = 1000  # decisions kept for percentiles / band mix
RATE_SECONDS = 10.0  # decisions_per_sec is measured over this trailing interval


class MetricsCollector:
    """Rolling in-process service metrics, fed by every decision (API and replay)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._window: deque[tuple[float, float, str]] = deque(maxlen=WINDOW)  # (monotonic ts, latency, band)
        self._total = 0

    def record(self, latency_ms: float, band: str) -> None:
        with self._lock:
            self._window.append((time.monotonic(), latency_ms, band))
            self._total += 1

    def snapshot(self) -> MetricsResponse:
        with self._lock:
            rows = list(self._window)
            total = self._total
        if not rows:
            return MetricsResponse(
                p50=0.0, p95=0.0, p99=0.0, decisions_per_sec=0.0,
                band_mix={b.value: 0.0 for b in Band}, window=0, total_decisions=total,
            )
        lat = np.array([r[1] for r in rows])
        now = time.monotonic()
        recent = sum(1 for r in rows if now - r[0] <= RATE_SECONDS)
        bands = [r[2] for r in rows]
        return MetricsResponse(
            p50=round(float(np.percentile(lat, 50)), 2),
            p95=round(float(np.percentile(lat, 95)), 2),
            p99=round(float(np.percentile(lat, 99)), 2),
            decisions_per_sec=round(recent / RATE_SECONDS, 2),
            band_mix={b.value: round(bands.count(b.value) / len(bands), 4) for b in Band},
            window=len(rows),
            total_decisions=total,
        )
