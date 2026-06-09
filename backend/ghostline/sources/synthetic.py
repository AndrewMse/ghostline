from __future__ import annotations

import asyncio
import time
from typing import AsyncIterator

from ..models import Event, Reset, TrackInfo
from ..synthetic import FigureEight, fly
from .base import Source


class SyntheticSource(Source):
    """Demo mode: a synthetic pilot flying the demo track in real time, forever."""

    sim = "demo"

    def __init__(self, laps_per_run: int = 8, speed: float = 1.0):
        super().__init__()
        self.laps_per_run = laps_per_run
        self.speed = speed
        self.detail = "synthetic pilot"

    async def events(self) -> AsyncIterator[Event]:
        track = FigureEight()
        self.connected = True
        yield TrackInfo(track.name)
        seed = int(time.time())
        while True:
            start = time.monotonic()
            first_t = None
            for sample in fly(track, self.laps_per_run, seed=seed, skill=1.0):
                if first_t is None:
                    first_t = sample.t
                due = start + (sample.t - first_t) / self.speed
                delay = due - time.monotonic()
                if delay > 0:
                    await asyncio.sleep(delay)
                yield sample
            yield Reset()
            seed += 1
