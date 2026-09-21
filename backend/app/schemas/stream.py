from typing import Literal

from pydantic import BaseModel

StreamSource = Literal["base", "shift"]


class StreamStatus(BaseModel):
    running: bool
    source: StreamSource
    events_emitted: int
    rate_per_sec: float
    subscribers: int
