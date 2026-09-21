import threading

from app.schemas.decision import BAND_TO_DECISION, Band, DecisionOutcome, Thresholds


class PolicyEngine:
    """Maps a 0-1000 score to a band. Thresholds start from config and can be tightened at runtime (drift)."""

    def __init__(self, base: Thresholds) -> None:
        _validate(base)
        self._base = base
        self._current = base
        self._lock = threading.Lock()

    @property
    def base(self) -> Thresholds:
        return self._base

    @property
    def thresholds(self) -> Thresholds:
        return self._current

    def classify(self, score: int) -> tuple[Band, Thresholds]:
        """Band for `score` plus the exact thresholds used (snapshot, so the pair is consistent under drift)."""
        t = self._current
        return self.band_for(score, t), t

    def band_for(self, score: int, thresholds: Thresholds | None = None) -> Band:
        t = thresholds or self._current
        if score < t.step_up:
            return Band.APPROVE
        if score < t.review:
            return Band.STEP_UP
        if score < t.decline:
            return Band.REVIEW
        return Band.DECLINE

    @staticmethod
    def decision_for(band: Band) -> DecisionOutcome:
        return BAND_TO_DECISION[band]

    def tighten(self, delta: int) -> tuple[Thresholds, Thresholds]:
        """Lower every cut-off by `delta` (never below 1, order preserved). Returns (old, new)."""
        with self._lock:
            old = self._current
            new = Thresholds(
                step_up=max(1, old.step_up - delta),
                review=max(2, old.review - delta),
                decline=max(3, old.decline - delta),
            )
            _validate(new)
            self._current = new
            return old, new

    def reset(self) -> tuple[Thresholds, Thresholds]:
        with self._lock:
            old, self._current = self._current, self._base
            return old, self._base


def _validate(t: Thresholds) -> None:
    if not 0 < t.step_up < t.review < t.decline <= 1000:
        raise ValueError(f"thresholds must satisfy 0 < step_up < review < decline <= 1000, got {t}")
