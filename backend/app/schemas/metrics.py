from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.decision import Thresholds


class MetricsResponse(BaseModel):
    """Rolling-window service metrics. Latency percentiles in milliseconds."""

    p50: float
    p95: float
    p99: float
    decisions_per_sec: float
    band_mix: dict[str, float] = Field(description="Fraction of decisions per band in the window (sums to 1)")
    window: int = Field(description="Number of decisions in the rolling window")
    total_decisions: int


class DriftEventOut(BaseModel):
    id: int
    ts: datetime
    detector: str
    stream: str
    old_thresholds: Thresholds
    new_thresholds: Thresholds
    details: dict


class DriftStatus(BaseModel):
    state: Literal["stable", "drift_detected"]
    thresholds: Thresholds
    base_thresholds: Thresholds
    events: list[DriftEventOut]
