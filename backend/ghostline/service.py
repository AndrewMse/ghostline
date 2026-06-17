"""Operations shared by the HTTP API and the live recorder."""

from __future__ import annotations

import threading
from collections import OrderedDict
from typing import Callable, Hashable, TypeVar

import numpy as np

from . import analysis, timing
from .db import Database
from .timing import CompletedLap, LapTimer, VirtualGate

T = TypeVar("T")


def _positions(d: dict[str, np.ndarray]) -> np.ndarray:
    return np.column_stack([d["x"], d["y"], d["z"]])


def _r(a, nd: int = 3) -> list:
    return np.round(np.asarray(a, dtype=float), nd).tolist()


def _key(lap: dict) -> tuple:
    # The lap's time span is part of the key: re-timing replaces laps, and ids can be reused.
    return (lap["id"], lap["session_id"], lap["t_start"], lap["t_end"])


def _lap_meta(lap: dict) -> dict:
    return {k: lap[k] for k in ("id", "session_id", "track_id", "number", "duration", "timing", "started_at")}


class _LRU:
    """API requests run on worker threads, so the caches are locked."""

    def __init__(self, size: int):
        self.size = size
        self._d: OrderedDict = OrderedDict()
        self._lock = threading.RLock()

    def get(self, key: Hashable, make: Callable[[], T]) -> T:
        with self._lock:
            if key in self._d:
                self._d.move_to_end(key)
                return self._d[key]
            value = self._d[key] = make()
            if len(self._d) > self.size:
                self._d.popitem(last=False)
            return value


def sector_bounds(ref_lap: dict, line: analysis.ReferenceLine, count: int = 6) -> np.ndarray:
    """Sector boundaries in metres: at the sim's gates when it timed the lap, else evenly spaced."""
    splits = ref_lap.get("splits") or []
    if ref_lap.get("timing") == "native" and splits:
        s = np.interp(splits, line.t, line.s)
        return np.concatenate([[0.0], s, [line.length]])
    return np.linspace(0.0, line.length, count + 1)


class Coach:
    def __init__(self, db: Database):
        self.db = db
        self._traces = _LRU(256)
        self._lines = _LRU(32)
        self._sectors = _LRU(4096)

    # timing

    def resegment_session(self, session_id: int, timer: LapTimer | None = None) -> list[CompletedLap]:
        """Re-time a session from its stored samples with the track's current gate."""
        session = self.db.session(session_id)
        if session is None:
            return []
        gate = self.db.track_gate(session["track_id"])
        d = self.db.samples(session_id, cols=("run", "t", "x", "y", "z"))
        laps = timing.segment(d["t"], _positions(d), d["run"].astype(int), self.db.crossings(session_id),
                              gate, timer)
        self.db.replace_laps(session_id, laps)
        return laps

    def resegment_track(self, track_id: int) -> None:
        for s in self.db.sessions(track_id):
            self.resegment_session(s["id"])

    def detect_gate(self, session_id: int) -> VirtualGate | None:
        d = self.db.samples(session_id, cols=("run", "t", "x", "y", "z"))
        return timing.find_gate(d["t"], _positions(d), d["run"].astype(int))

    def gate_at(self, session_id: int, t: float, radius: float = 6.0) -> VirtualGate | None:
        """A gate where the drone was at session time `t`, facing the way it was flying."""
        d = self.db.samples(session_id, t - 0.25, t + 0.25, cols=("t", "x", "y", "z"))
        if len(d["t"]) < 2:
            return None
        pos = _positions(d)
        i = int(np.argmin(np.abs(d["t"] - t)))
        j0, j1 = max(i - 1, 0), min(i + 1, len(pos) - 1)
        vel = (pos[j1] - pos[j0]) / max(d["t"][j1] - d["t"][j0], 1e-6)
        if np.linalg.norm(vel) < 1.0:
            return None
        return VirtualGate.from_motion(pos[i], vel, radius)

    # traces and reference lines

    def lap_trace(self, lap: dict) -> analysis.LapTrace:
        def load() -> analysis.LapTrace:
            d = self.db.samples(lap["session_id"], lap["t_start"] - 0.1, lap["t_end"] + 0.1,
                                cols=("t", "x", "y", "z"))
            return analysis.extract_lap(d["t"], _positions(d), lap["t_start"], lap["t_end"])
        return self._traces.get(_key(lap), load)

    def reference_line(self, lap: dict) -> analysis.ReferenceLine:
        return self._lines.get(_key(lap), lambda: analysis.ReferenceLine(self.lap_trace(lap)))

    def _sector_times(self, lap: dict, ref: dict, bounds: np.ndarray) -> np.ndarray:
        def compute() -> np.ndarray:
            s, t, _ = analysis.time_at_distance(self.lap_trace(lap), self.reference_line(ref))
            return np.diff(np.interp(bounds, s, t))
        return self._sectors.get((_key(lap), _key(ref), tuple(bounds)), compute)

    # views

    def lap_detail(self, lap_id: int) -> dict | None:
        lap = self.db.lap(lap_id)
        if lap is None:
            return None
        d = self.db.samples(lap["session_id"], lap["t_start"], lap["t_end"])
        pos = _positions(d)
        speed = np.linalg.norm(np.gradient(pos, d["t"], axis=0), axis=1) if len(pos) > 1 else np.zeros(len(pos))
        has_sticks = len(pos) > 0 and not np.all(np.isnan(d["throttle"]))
        return {
            **lap,
            "t": _r(d["t"] - lap["t_start"]),
            "pos": _r(pos, 2),
            "speed": _r(speed, 2),
            "sticks": {k: _r(np.nan_to_num(d[k])) for k in ("throttle", "yaw", "pitch", "roll")}
            if has_sticks else None,
        }

    def compare(self, lap_id: int, ref_id: int, sectors: int = 6) -> dict | None:
        lap, ref = self.db.lap(lap_id), self.db.lap(ref_id)
        if lap is None or ref is None:
            return None
        trace, ref_trace = self.lap_trace(lap), self.lap_trace(ref)
        line = self.reference_line(ref)
        bounds = sector_bounds(ref, line, sectors)
        c = analysis.compare(trace, ref_trace, sector_bounds=bounds, ref_line=line)

        # Where each lap was at every grid distance, so hovering the charts can
        # put both drones on the map at the same place on track.
        s_lap, t_lap, _ = analysis.time_at_distance(trace, line)
        t_on_grid = np.interp(c.s, s_lap, t_lap)
        lap_on_grid = np.column_stack([np.interp(t_on_grid, trace.t, trace.pos[:, k]) for k in range(3)])

        return {
            "lap": _lap_meta(lap),
            "ref": _lap_meta(ref),
            "length": round(c.length, 2),
            "s": _r(c.s, 1),
            "delta": _r(c.delta),
            "speed_lap": _r(c.speed_lap, 2),
            "speed_ref": _r(c.speed_ref, 2),
            "lateral": _r(c.lateral, 2),
            "vertical": _r(c.vertical, 2),
            "t_lap": _r(t_on_grid),
            "t_ref": _r(line.time_at(c.s)),
            "pos_lap": _r(lap_on_grid, 2),
            "pos_ref": _r(line.point_at(c.s), 2),
            "sectors": [
                {"index": i + 1, "start": round(float(bounds[i]), 1), "end": round(float(bounds[i + 1]), 1),
                 "lap": round(float(c.sectors_lap[i]), 3), "ref": round(float(c.sectors_ref[i]), 3),
                 "delta": round(float(c.sectors_lap[i] - c.sectors_ref[i]), 3)}
                for i in range(len(c.sectors_lap))
            ],
            "insights": analysis.insights(c),
            "ghost": {
                "lap": {"t": _r(trace.t), "pos": _r(trace.pos, 2)},
                "ref": {"t": _r(ref_trace.t), "pos": _r(ref_trace.pos, 2)},
            },
        }

    def track_summary(self, track_id: int, sectors: int = 6) -> dict | None:
        track = self.db.track(track_id)
        if track is None:
            return None
        laps = self.db.laps(track_id=track_id)
        out = {"track": track, "laps": [], "best_lap": None, "theoretical_best": None,
               "sector_bounds": [], "sector_best": [], "stats": None}
        if not laps:
            return out
        best = min(laps, key=lambda x: x["duration"])
        line = self.reference_line(best)
        bounds = sector_bounds(best, line, sectors)
        matrix = np.array([self._sector_times(lap, best, bounds) for lap in laps])
        durations = np.array([x["duration"] for x in laps])
        clean = durations[durations <= best["duration"] * 1.07]
        out.update(
            laps=[{**_lap_meta(lap), "sectors": _r(row)} for lap, row in zip(laps, matrix)],
            best_lap=_lap_meta(best),
            theoretical_best=round(analysis.theoretical_best(matrix), 3),
            sector_bounds=_r(bounds, 1),
            sector_best=[{"time": round(float(matrix[:, k].min()), 3), "lap_id": laps[int(matrix[:, k].argmin())]["id"]}
                         for k in range(matrix.shape[1])],
            stats={
                "laps": len(laps),
                "clean_laps": int(len(clean)),
                "mean_clean": round(float(clean.mean()), 3),
                "stdev_clean": round(float(clean.std()), 3) if len(clean) > 1 else 0.0,
                "length": round(line.length, 1),
            },
        )
        return out

    def session_path(self, session_id: int, hz: float = 10.0) -> dict:
        d = self.db.samples(session_id, cols=("run", "t", "x", "y", "z"))
        if len(d["t"]) == 0:
            return {"t": [], "run": [], "pos": []}
        keep = np.concatenate([[True], np.diff(np.floor(d["t"] * hz)) > 0])
        return {"t": _r(d["t"][keep]), "run": d["run"][keep].astype(int).tolist(),
                "pos": _r(_positions(d)[keep], 2)}
