"""Lap timing.

Two ways a lap gets timed:

* **native** — Velocidrone reports gate crossings during a race. A lap boundary
  is a crossing where the lap counter goes up (or the finishing crossing);
  every other crossing is an intermediate split.
* **virtual** — for Liftoff, and for Velocidrone free flight, laps are timed by
  a plane in space (a `VirtualGate`). The crossing time is interpolated
  between frames, so timing is sub-frame accurate.

`LapTimer` is incremental so the live view and the batch re-segmentation of
stored sessions run exactly the same code.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

import numpy as np

from .models import GateCrossing

MIN_LAP_S = 3.0
MAX_LAP_S = 600.0


@dataclass(slots=True)
class VirtualGate:
    center: tuple[float, float, float]
    normal: tuple[float, float, float]  # unit vector, direction of travel
    radius: float = 6.0

    def to_dict(self) -> dict:
        return {"center": list(self.center), "normal": list(self.normal), "radius": self.radius}

    @classmethod
    def from_dict(cls, d: dict) -> "VirtualGate":
        return cls(tuple(d["center"]), tuple(d["normal"]), float(d.get("radius", 6.0)))

    @classmethod
    def from_motion(cls, pos, vel, radius: float = 6.0) -> "VirtualGate":
        v = np.asarray(vel, dtype=float)
        n = v / max(np.linalg.norm(v), 1e-9)
        return cls(tuple(float(x) for x in pos), tuple(float(x) for x in n), radius)

    def crossing(self, t0: float, p0, t1: float, p1) -> float | None:
        """Time at which the segment p0→p1 crosses the gate forwards, if it does."""
        c = np.asarray(self.center)
        n = np.asarray(self.normal)
        a = np.asarray(p0, dtype=float)
        b = np.asarray(p1, dtype=float)
        d0 = float(np.dot(a - c, n))
        d1 = float(np.dot(b - c, n))
        if not (d0 < 0.0 <= d1):
            return None
        alpha = d0 / (d0 - d1)
        hit = a + alpha * (b - a)
        if np.linalg.norm(hit - c) > self.radius:
            return None
        return t0 + alpha * (t1 - t0)


@dataclass(slots=True)
class CompletedLap:
    run: int
    t_start: float
    t_end: float
    timing: str  # "native" | "virtual"
    splits: list[float] = field(default_factory=list)  # seconds from lap start at each intermediate gate

    @property
    def duration(self) -> float:
        return self.t_end - self.t_start


class LapTimer:
    """Feed it samples and native crossings in time order; it returns laps as they complete."""

    def __init__(self, gate: VirtualGate | None = None, min_lap: float = MIN_LAP_S):
        self.gate = gate
        self.min_lap = min_lap
        self.run = 0
        self.mode = "virtual"
        self.lap_start: float | None = None
        self.splits: list[float] = []
        self._prev: tuple[float, tuple] | None = None
        self._native_lap: int | None = None

    def set_gate(self, gate: VirtualGate | None) -> None:
        self.gate = gate
        if self.mode == "virtual":
            self.lap_start = None

    def reset(self, run: int) -> None:
        self.run = run
        self.mode = "virtual"
        self.lap_start = None
        self.splits = []
        self._prev = None
        self._native_lap = None

    def sample(self, t: float, pos) -> CompletedLap | None:
        prev, self._prev = self._prev, (t, pos)
        if self.mode != "virtual" or self.gate is None or prev is None:
            return None
        tc = self.gate.crossing(prev[0], prev[1], t, pos)
        if tc is None:
            return None
        return self._boundary(tc, timing="virtual")

    def crossing(self, t: float, c: GateCrossing) -> CompletedLap | None:
        if self.mode != "native":
            # The sim is timing this run; drop any half-lap the virtual gate started.
            self.mode = "native"
            self.lap_start = None
            self.splits = []
        prev_lap, self._native_lap = self._native_lap, c.lap
        if prev_lap is None:
            is_boundary = c.finished or (c.lap >= 1 and c.gate == 1)
        else:
            is_boundary = c.finished or c.lap > prev_lap
        if not is_boundary:
            if self.lap_start is not None:
                self.splits.append(t - self.lap_start)
            return None
        lap = self._boundary(t, timing="native")
        if c.finished:
            self.lap_start = None
        return lap

    def _boundary(self, t: float, timing: str) -> CompletedLap | None:
        if self.lap_start is not None and t - self.lap_start < self.min_lap:
            return None  # jitter around the gate plane
        done = None
        if self.lap_start is not None and t - self.lap_start <= MAX_LAP_S:
            done = CompletedLap(self.run, self.lap_start, t, timing, self.splits)
        self.lap_start = t
        self.splits = []
        return done


def segment(
    t: np.ndarray,
    pos: np.ndarray,
    run: np.ndarray,
    crossings: Iterable[tuple[float, int, GateCrossing]],
    gate: VirtualGate | None,
    timer: LapTimer | None = None,
) -> list[CompletedLap]:
    """Re-time a whole stored session with the same LapTimer that times live.

    Pass `timer` to keep it afterwards: it ends in the state of the last run,
    ready to carry on timing live samples.
    """
    by_run: dict[int, list[tuple[float, GateCrossing]]] = {}
    for ct, crun, c in crossings:
        by_run.setdefault(crun, []).append((ct, c))

    laps: list[CompletedLap] = []
    if timer is None:
        timer = LapTimer(gate)
    else:
        timer.gate = gate
    if len(t) == 0:
        return laps
    current_run = int(run[0])
    timer.reset(current_run)
    pending = sorted(by_run.get(current_run, []), key=lambda x: x[0])
    ci = 0
    for i in range(len(t)):
        r = int(run[i])
        if r != current_run:
            current_run = r
            timer.reset(r)
            pending = sorted(by_run.get(r, []), key=lambda x: x[0])
            ci = 0
        while ci < len(pending) and pending[ci][0] <= t[i]:
            lap = timer.crossing(*pending[ci])
            if lap:
                laps.append(lap)
            ci += 1
        lap = timer.sample(float(t[i]), pos[i])
        if lap:
            laps.append(lap)
    # Crossings after the last sample of their run (e.g. the finish).
    while ci < len(pending):
        lap = timer.crossing(*pending[ci])
        if lap:
            laps.append(lap)
        ci += 1
    return laps


def _gate_crossings(gate_c: np.ndarray, gate_n: np.ndarray, radius: float,
                    t: np.ndarray, pos: np.ndarray, run: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    d = (pos - gate_c) @ gate_n
    idx = np.nonzero((d[:-1] < 0) & (d[1:] >= 0) & (run[:-1] == run[1:]))[0]
    if len(idx) == 0:
        return idx.astype(float), idx
    alpha = d[idx] / (d[idx] - d[idx + 1])
    hit = pos[idx] + alpha[:, None] * (pos[idx + 1] - pos[idx])
    ok = np.linalg.norm(hit - gate_c, axis=1) <= radius
    tc = t[idx] + alpha * (t[idx + 1] - t[idx])
    return tc[ok], run[idx][ok]


def lap_times_through(gate: VirtualGate, t: np.ndarray, pos: np.ndarray, run: np.ndarray,
                      min_lap: float = MIN_LAP_S) -> list[float]:
    tc, rc = _gate_crossings(np.asarray(gate.center), np.asarray(gate.normal), gate.radius, t, pos, run)
    laps: list[float] = []
    last_t, last_r = None, None
    for ct, cr in zip(tc, rc):
        if last_t is not None and cr == last_r:
            dt = ct - last_t
            if dt < min_lap:
                continue
            if dt <= MAX_LAP_S:
                laps.append(float(dt))
        last_t, last_r = ct, cr
    return laps


def find_gate(t: np.ndarray, pos: np.ndarray, run: np.ndarray, *, radius: float = 6.0,
              search_s: float = 90.0, step_s: float = 0.5, min_median_lap: float = 5.0) -> VirtualGate | None:
    """Guess a start/finish gate from nothing but the flight path.

    Tries candidate planes along the first `search_s` seconds of flying (each at
    the drone's position, facing its direction of travel) and keeps the one that
    yields the most laps of consistent length. Ties go to the earliest
    candidate, which on a race track is usually the start/finish line.
    """
    if len(t) < 10:
        return None
    vel = np.gradient(pos, t, axis=0)
    speed = np.linalg.norm(vel, axis=1)
    moving = np.nonzero(speed > 4.0)[0]
    if len(moving) == 0:
        return None
    t_first = t[moving[0]]
    candidates: list[int] = []
    next_t = t_first
    for i in moving:
        if t[i] > t_first + search_s:
            break
        if t[i] >= next_t:
            candidates.append(int(i))
            next_t = t[i] + step_s

    best: tuple[int, VirtualGate] | None = None
    for i in candidates:
        gate = VirtualGate.from_motion(pos[i], vel[i], radius)
        laps = lap_times_through(gate, t, pos, run)
        if len(laps) < 2:
            continue
        med = float(np.median(laps))
        if med < min_median_lap:
            continue
        score = sum(1 for x in laps if 0.8 * med <= x <= 1.3 * med)
        if best is None or score > best[0]:
            best = (score, gate)
    return best[1] if best and best[0] >= 2 else None
