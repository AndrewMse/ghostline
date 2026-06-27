"""Turns a live event stream into stored sessions, laps and a live view.

The session clock
    Liftoff's timestamp restarts at zero on every reset and Velocidrone's only
    counts while flying, so samples are stored on a session clock that always
    moves forward. Each reset (clock going backwards, a pause, a teleport, or
    a race start) begins a new *run*; a lap never spans two runs.

Zero-config timing
    If the track has no start/finish gate yet and the sim is not timing laps,
    the recorder periodically tries to find one from the flight path
    (`timing.find_gate`), then re-times what has been flown so far.
"""

from __future__ import annotations

import functools
import logging
import math
import threading
import time

from .db import Database, sample_row
from .models import Event, GateCrossing, RaceEnd, RaceStart, Reset, Sample, TrackInfo
from .service import Coach
from .timing import CompletedLap, LapTimer

log = logging.getLogger(__name__)

MAX_FRAME_GAP_S = 2.0  # longer than this without frames = paused / menu
TELEPORT_M = 15.0  # further than this in one frame = reset to start
IDLE_CLOSE_S = 45.0
GATE_SEARCH_EVERY_S = 15.0
GATE_SEARCH_AFTER_S = 30.0
MIN_SESSION_S = 5.0


def _locked(method):
    """The event pump and API worker threads both drive the recorder."""
    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)
    return wrapper


class Recorder:
    def __init__(self, db: Database, coach: Coach, sim: str):
        self.db = db
        self.coach = coach
        self.sim = sim
        self.track_name: str | None = None
        self.session_id: int | None = None
        self.track_id: int | None = None
        self.timer = LapTimer()
        self.lap_seq = 0  # bumps whenever stored laps change, so clients know to refetch
        self._lock = threading.RLock()
        self._reset_session_state()

    def _reset_session_state(self) -> None:
        self.run = 0
        self.t = 0.0
        self.pos: tuple[float, float, float] | None = None
        self.speed = 0.0
        self.native_seen = False
        self.last_lap: dict | None = None
        self._src_t: float | None = None
        self._new_run = False
        self._await_go = False
        self._t_go: float | None = None
        self._buf: list[tuple] = []
        self._last_flush = time.monotonic()
        self._last_frame_wall = time.monotonic()
        self._next_gate_search = GATE_SEARCH_AFTER_S
        self._ref = None  # (lap dict, ReferenceLine)
        self._s_live = 0.0
        self._live_lap_start: float | None = None
        self.live_delta: float | None = None

    # event intake

    @_locked
    def handle(self, event: Event) -> None:
        if isinstance(event, Sample):
            self._on_sample(event)
        elif isinstance(event, GateCrossing):
            self._on_crossing(event)
        elif isinstance(event, RaceStart):
            self._new_run = True
            self._await_go = True
        elif isinstance(event, Reset):
            self._new_run = True
        elif isinstance(event, TrackInfo):
            self.set_track(event.name)
        elif isinstance(event, RaceEnd):
            pass

    def _on_sample(self, s: Sample) -> None:
        now = time.monotonic()
        if self.session_id is None:
            self._open_session()
            t = 0.0
        else:
            dt = s.t - self._src_t
            if dt == 0.0:
                return  # repeated frame (paused)
            clock_ok = 0.0 < dt <= MAX_FRAME_GAP_S
            teleport = self.pos is not None and math.dist(s.pos, self.pos) > TELEPORT_M
            t = self.t + (dt if clock_ok else 1.0)
            if self._new_run or not clock_ok or teleport:
                self.run += 1
                self.timer.reset(self.run)
        self._new_run = False
        if self._await_go:
            self._t_go = t
            self._await_go = False

        if s.vel is not None:
            self.speed = math.hypot(*s.vel)
        elif self.pos is not None and t > self.t:
            self.speed = math.dist(s.pos, self.pos) / (t - self.t)
        self._src_t, self.t, self.pos = s.t, t, s.pos
        self._last_frame_wall = now
        self._buf.append(sample_row(self.session_id, self.run, t, s))
        if len(self._buf) >= 240 or now - self._last_flush > 1.0:
            self.flush()

        lap = self.timer.sample(t, s.pos)
        if lap:
            self._lap_done(lap)
        self._update_live_delta()
        if (self.timer.gate is None and not self.native_seen and self.t >= self._next_gate_search):
            self._next_gate_search = self.t + GATE_SEARCH_EVERY_S
            self._search_gate()

    def _on_crossing(self, c: GateCrossing) -> None:
        if self.session_id is None:
            return
        t = self._t_go + c.race_time if self._t_go is not None else self.t
        self.native_seen = True
        self.db.insert_crossing(self.session_id, self.run, t, c)
        lap = self.timer.crossing(t, c)
        if lap:
            self._lap_done(lap)

    # sessions

    def _open_session(self) -> None:
        # A race start usually arrives before the first frame of telemetry.
        await_go = self._await_go
        self._reset_session_state()
        self._await_go = await_go
        name = self.track_name or f"Unnamed {self.sim} track"
        self.track_id = self.db.track_id(name, self.sim)
        self.session_id = self.db.create_session(self.track_id, self.sim)
        self.timer = LapTimer(self.db.track_gate(self.track_id))
        self._load_reference()
        log.info("session %s opened on %r", self.session_id, name)

    @_locked
    def close_session(self) -> None:
        if self.session_id is None:
            return
        self.flush()
        sid = self.session_id
        if self.t < MIN_SESSION_S and not self.db.laps(session_id=sid):
            self.db.delete_session(sid)
        else:
            self.db.end_session(sid, self.t)
        log.info("session %s closed", sid)
        self.session_id = None
        self.lap_seq += 1

    @_locked
    def set_track(self, name: str) -> None:
        """Name what is being flown. Moves the open session too, and re-times it."""
        self.track_name = name
        if self.session_id is None:
            return
        track_id = self.db.track_id(name, self.sim)
        if track_id == self.track_id:
            return
        self.db.set_session_track(self.session_id, track_id)
        self.track_id = track_id
        self._next_gate_search = self.t + GATE_SEARCH_EVERY_S
        self.retime()

    @_locked
    def retime(self) -> None:
        """Re-time the open session, e.g. after its track's gate changed."""
        if self.session_id is None:
            return
        self.flush()
        timer = LapTimer()
        self.coach.resegment_session(self.session_id, timer)
        if timer.run != self.run:  # the current run has no stored samples yet
            timer.reset(self.run)
        self.timer = timer
        self.lap_seq += 1
        self._load_reference()

    @_locked
    def tick(self) -> None:
        """Call about once a second."""
        if self.session_id is None:
            return
        if self._buf:
            self.flush()
        if time.monotonic() - self._last_frame_wall > IDLE_CLOSE_S:
            self.close_session()

    @_locked
    def flush(self) -> None:
        if self._buf:
            self.db.insert_samples(self._buf)
            self._buf = []
        self._last_flush = time.monotonic()

    # laps

    def _search_gate(self) -> None:
        self.flush()
        gate = self.coach.detect_gate(self.session_id)
        if gate is None:
            return
        log.info("start/finish gate found for track %s", self.track_id)
        self.db.set_track_gate(self.track_id, gate)
        self.retime()

    def _lap_done(self, lap: CompletedLap) -> None:
        self.flush()
        lap_id = self.db.insert_lap(self.session_id, lap)
        best = self._ref[0]["duration"] if self._ref else None
        self.last_lap = {
            "id": lap_id,
            "duration": lap.duration,
            "delta": lap.duration - best if best is not None else None,
            "timing": lap.timing,
        }
        self.lap_seq += 1
        if best is None or lap.duration < best:
            self._load_reference()

    def _load_reference(self) -> None:
        best = self.db.best_lap(self.track_id) if self.track_id is not None else None
        self._ref = (best, self.coach.reference_line(best)) if best else None
        self._live_lap_start = None

    def _update_live_delta(self) -> None:
        start = self.timer.lap_start
        if start != self._live_lap_start:
            self._live_lap_start = start
            self._s_live = 0.0
        if start is None or self._ref is None or self.pos is None:
            self.live_delta = None
            return
        line = self._ref[1]
        self._s_live, _ = line.project_one(self.pos, self._s_live)
        self.live_delta = (self.t - start) - float(line.time_at(self._s_live))

    # live view

    @_locked
    def snapshot(self) -> dict:
        start = self.timer.lap_start
        best = self._ref[0] if self._ref else None
        lap_now = None
        if self.session_id is not None and start is not None:
            elapsed = self.t - start
            lap_now = {
                "elapsed": elapsed,
                "delta": self.live_delta,
                "predicted": best["duration"] + self.live_delta if best and self.live_delta is not None else None,
                "distance": self._s_live if self._ref else None,
            }
        if self.timer.mode == "native":
            timing = "native"
        elif self.timer.gate is not None:
            timing = "virtual"
        else:
            timing = "searching"
        return {
            "session_id": self.session_id,
            "track": {"id": self.track_id, "name": self.track_name or f"Unnamed {self.sim} track"},
            "t": self.t,
            "run": self.run,
            "pos": self.pos,
            "speed": self.speed,
            "timing": timing,
            "gate": self.timer.gate.to_dict() if self.timer.gate else None,
            "lap": lap_now,
            "last_lap": self.last_lap,
            "best": {"id": best["id"], "duration": best["duration"]} if best else None,
            "lap_seq": self.lap_seq,
        }
