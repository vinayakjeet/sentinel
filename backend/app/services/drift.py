"""Drift detection (DESIGN §7): river ADWIN on (a) the score stream and (b) a delayed-label error stream.

Pure and thread-safe; knows nothing about the database or HTTP. `DriftService` (drift_service.py) acts on detections.
"""

import threading
from collections import deque
from dataclasses import dataclass

from river.drift import ADWIN


@dataclass(frozen=True)
class Detection:
    stream: str  # "score" | "error"
    events_seen: int
    window_width: float
    window_mean: float


class DriftMonitor:
    """Feeds ADWIN detectors. Scores arrive immediately; labels arrive `label_lag` events later (simulated
    chargeback / confirmation delay), so the error stream |label - p| lags the score stream."""

    def __init__(self, delta: float, label_lag: int, cooldown_events: int) -> None:
        self.delta = delta
        self.label_lag = label_lag
        self.cooldown_events = cooldown_events
        self._lock = threading.Lock()
        self.reset()

    def reset(self) -> None:
        with self._lock:
            self._detectors = {"score": ADWIN(delta=self.delta), "error": ADWIN(delta=self.delta)}
            self._pending: deque[tuple[float, int]] = deque()
            self._seen = 0
            self._last_fired = {"score": -(10**9), "error": -(10**9)}

    @property
    def events_seen(self) -> int:
        return self._seen

    def observe(self, p: float, label: int | None = None) -> list[Detection]:
        """Feed one decision's final probability (and its true label, if known). Returns new detections."""
        with self._lock:
            self._seen += 1
            fired = [self._update("score", p)]
            if label is not None:
                self._pending.append((p, label))
                if len(self._pending) > self.label_lag:
                    p_old, y_old = self._pending.popleft()
                    fired.append(self._update("error", abs(y_old - p_old)))
            return [d for d in fired if d is not None]

    def _update(self, stream: str, value: float) -> Detection | None:
        det = self._detectors[stream]
        det.update(float(value))
        if not det.drift_detected:
            return None
        if self._seen - self._last_fired[stream] < self.cooldown_events:
            return None  # ADWIN keeps firing while the window re-settles; act once per episode
        self._last_fired[stream] = self._seen
        return Detection(stream=stream, events_seen=self._seen, window_width=det.width, window_mean=det.estimation)
