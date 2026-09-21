"""In-process replay of data/replay/*.csv through the same DecisionService path as the API (DESIGN §7)."""

import asyncio
import logging
import random
import threading
from collections.abc import Iterator
from pathlib import Path

import pandas as pd
from pydantic import ValidationError

from app.core.config import Settings
from app.db.session import SessionLocal
from app.schemas.application import IDENTIFIER_FIELDS, ApplicationEvent
from app.schemas.stream import StreamSource, StreamStatus
from app.services.broadcaster import Broadcaster
from app.services.decision_service import DecisionService

logger = logging.getLogger(__name__)

CHUNK = 2000
# Identifiers must stay strings (an all-digit phone would otherwise parse as int and fail strict validation).
STR_COLUMNS = dict.fromkeys(IDENTIFIER_FIELDS, str)
Row = tuple[int, dict]  # (row index in file, record incl. fraud_bool)


def _chunks(path: Path, legit_only: bool = False) -> Iterator[Row]:
    for chunk in pd.read_csv(path, chunksize=CHUNK, dtype=STR_COLUMNS):
        if legit_only:
            chunk = chunk[chunk["fraud_bool"] == 0]
        yield from zip(chunk.index.tolist(), chunk.to_dict("records"), strict=True)


def base_rows(path: Path) -> Iterator[Row]:
    while True:  # loop the file for long demos
        yield from _chunks(path)


def fraud_wave_rows(path: Path, fraud_rate: float, seed: int) -> Iterator[Row]:
    """Variant-file rows in file order, with real variant fraud rows swapped in at `fraud_rate` (simulated wave)."""
    frauds = [
        row
        for chunk in pd.read_csv(path, chunksize=50_000, dtype=STR_COLUMNS)
        for row in zip(chunk.index[chunk["fraud_bool"] == 1].tolist(),
                       chunk[chunk["fraud_bool"] == 1].to_dict("records"), strict=True)
    ]
    rng = random.Random(seed)
    while True:
        for row in _chunks(path, legit_only=True):
            yield rng.choice(frauds) if rng.random() < fraud_rate else row


class ReplayService:
    def __init__(self, settings: Settings, decisions: DecisionService, broadcaster: Broadcaster) -> None:
        self.s = settings
        self.decisions = decisions
        self.broadcaster = broadcaster
        self.source: StreamSource = "base"
        self.events_emitted = 0
        self.invalid_rows = 0
        self._count_lock = threading.Lock()
        self._rows: Iterator[Row] | None = None
        self._task: asyncio.Task | None = None

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def status(self) -> StreamStatus:
        return StreamStatus(
            running=self.running,
            source=self.source,
            events_emitted=self.events_emitted,
            rate_per_sec=self.s.replay_rate_per_sec,
            subscribers=self.broadcaster.subscribers,
        )

    def _open(self, source: StreamSource) -> Iterator[Row]:
        d = Path(self.s.replay_dir)
        if source == "base":
            return base_rows(d / "stream_base.csv")
        if self.s.replay_shift_fraud_rate > 0:
            return fraud_wave_rows(d / "stream_shift.csv", self.s.replay_shift_fraud_rate, self.s.replay_seed)
        return base_rows(d / "stream_shift.csv")

    async def start(self) -> StreamStatus:
        if not self.running:
            if self._rows is None:
                self._rows = await asyncio.to_thread(self._open, self.source)
            self._task = asyncio.create_task(self._run(), name="replay")
            logger.info("replay started", extra={"source": self.source})
        return self.status()

    async def stop(self) -> StreamStatus:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
            logger.info("replay stopped", extra={"events_emitted": self.events_emitted})
        return self.status()

    async def switch(self, source: StreamSource) -> StreamStatus:
        rows = await asyncio.to_thread(self._open, source)  # may scan the file for fraud rows: off the loop
        self.source, self._rows = source, rows
        logger.info("replay source switched", extra={"source": source, "fraud_rate": self.s.replay_shift_fraud_rate})
        return self.status()

    async def _run(self) -> None:
        interval = 1.0 / self.s.replay_rate_per_sec
        slots = asyncio.Semaphore(self.s.replay_workers)
        loop = asyncio.get_running_loop()
        next_at = loop.time()
        inflight: set[asyncio.Task] = set()
        try:
            while True:
                await slots.acquire()
                rows = self._rows
                idx, record = await asyncio.to_thread(next, rows)  # may read a CSV chunk: off the loop
                source = self.source
                t = asyncio.create_task(self._one(idx, record, source, slots))
                inflight.add(t)
                t.add_done_callback(inflight.discard)
                next_at += interval
                await asyncio.sleep(max(0.0, next_at - loop.time()))
                if loop.time() - next_at > 1.0:  # fell behind (scoring slower than the rate): don't burst
                    next_at = loop.time()
        finally:
            for t in inflight:
                t.cancel()

    async def _one(self, idx: int, record: dict, source: str, slots: asyncio.Semaphore) -> None:
        try:
            await asyncio.to_thread(self._decide, idx, dict(record), source)
        except Exception:
            logger.exception("replay decision failed", extra={"row": idx, "source": source})
        finally:
            slots.release()

    def _decide(self, idx: int, record: dict, source: str) -> None:
        label = int(record.pop("fraud_bool"))
        try:
            event = ApplicationEvent.model_validate({**record, "external_ref": f"{source}-{idx}"})
        except ValidationError as exc:
            with self._count_lock:
                self.invalid_rows += 1
            errors = [f"{'.'.join(map(str, e['loc']))}:{e['type']}" for e in exc.errors()]  # never the values
            logger.warning("replay row rejected by schema", extra={"row": idx, "source": source, "errors": errors})
            return
        with SessionLocal() as db:
            response = self.decisions.decide(
                db, event, actor="replay", source_stream=f"replay_{source}", drift_label=label
            )
        with self._count_lock:
            self.events_emitted += 1
        if response.band != "APPROVE":  # analysts open these cases; embed them for similar-cases
            from app.semantic import embed_decision

            embed_decision(response.decision_id)

