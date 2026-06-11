"""SQLite storage.

Raw samples are kept (not just laps) so laps can be re-timed later — when the
start/finish gate is moved, or the timing logic improves.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np

from .models import GateCrossing, Sample
from .timing import CompletedLap, VirtualGate

SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS tracks (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    sim         TEXT NOT NULL,
    gate        TEXT,                -- JSON VirtualGate, NULL until set or detected
    created_at  TEXT NOT NULL,
    UNIQUE (name, sim)
);

CREATE TABLE IF NOT EXISTS sessions (
    id          INTEGER PRIMARY KEY,
    track_id    INTEGER NOT NULL REFERENCES tracks(id),
    sim         TEXT NOT NULL,
    started_at  TEXT NOT NULL,
    ended_at    TEXT,
    duration    REAL NOT NULL DEFAULT 0
);

-- One row per telemetry frame. t is the session clock (seconds, monotonic);
-- run increments whenever the drone is reset.
CREATE TABLE IF NOT EXISTS samples (
    session_id  INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    run         INTEGER NOT NULL,
    t           REAL NOT NULL,
    x REAL NOT NULL, y REAL NOT NULL, z REAL NOT NULL,
    vx REAL, vy REAL, vz REAL,
    qx REAL, qy REAL, qz REAL, qw REAL,
    gyro_pitch REAL, gyro_roll REAL, gyro_yaw REAL,
    throttle REAL, yaw REAL, pitch REAL, roll REAL
);
CREATE INDEX IF NOT EXISTS samples_by_time ON samples (session_id, t);

CREATE TABLE IF NOT EXISTS crossings (
    session_id  INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    run         INTEGER NOT NULL,
    t           REAL NOT NULL,
    lap         INTEGER NOT NULL,
    gate        INTEGER NOT NULL,
    finished    INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS laps (
    id          INTEGER PRIMARY KEY,
    session_id  INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    run         INTEGER NOT NULL,
    number      INTEGER NOT NULL,     -- 1-based within the session
    t_start     REAL NOT NULL,
    t_end       REAL NOT NULL,
    duration    REAL NOT NULL,
    timing      TEXT NOT NULL,        -- native | virtual
    splits      TEXT NOT NULL DEFAULT '[]'
);
CREATE INDEX IF NOT EXISTS laps_by_session ON laps (session_id);
"""

SAMPLE_COLS = ("run", "t", "x", "y", "z", "vx", "vy", "vz", "qx", "qy", "qz", "qw",
               "gyro_pitch", "gyro_roll", "gyro_yaw", "throttle", "yaw", "pitch", "roll")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sample_row(session_id: int, run: int, t: float, s: Sample) -> tuple:
    vel = s.vel or (None, None, None)
    att = s.att or (None, None, None, None)
    gyro = s.gyro or (None, None, None)
    sticks = s.sticks or (None, None, None, None)
    return (session_id, run, t, *s.pos, *vel, *att, *gyro, *sticks)


class Database:
    def __init__(self, path: str | Path = "ghostline.db"):
        self.path = str(path)
        self._conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        with self._lock:
            self._conn.executescript(SCHEMA)

    def close(self) -> None:
        self._conn.close()

    def _q(self, sql: str, args: Sequence = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, args).fetchall()

    def _x(self, sql: str, args: Sequence = ()) -> int:
        with self._lock:
            return self._conn.execute(sql, args).lastrowid

    # tracks

    def track_id(self, name: str, sim: str) -> int:
        rows = self._q("SELECT id FROM tracks WHERE name = ? AND sim = ?", (name, sim))
        if rows:
            return rows[0]["id"]
        return self._x("INSERT INTO tracks (name, sim, created_at) VALUES (?, ?, ?)", (name, sim, _now()))

    def tracks(self) -> list[dict]:
        rows = self._q("""
            SELECT t.id, t.name, t.sim, t.gate,
                   COUNT(DISTINCT s.id) AS sessions, COUNT(l.id) AS laps, MIN(l.duration) AS best
            FROM tracks t
            LEFT JOIN sessions s ON s.track_id = t.id
            LEFT JOIN laps l ON l.session_id = s.id
            GROUP BY t.id ORDER BY MAX(s.started_at) DESC NULLS LAST, t.id DESC
        """)
        return [self._track(r) for r in rows]

    def track(self, track_id: int) -> dict | None:
        rows = self._q("SELECT id, name, sim, gate FROM tracks WHERE id = ?", (track_id,))
        return self._track(rows[0]) if rows else None

    @staticmethod
    def _track(r: sqlite3.Row) -> dict:
        d = dict(r)
        d["gate"] = json.loads(d["gate"]) if d["gate"] else None
        return d

    def track_gate(self, track_id: int) -> VirtualGate | None:
        t = self.track(track_id)
        return VirtualGate.from_dict(t["gate"]) if t and t["gate"] else None

    def set_track_gate(self, track_id: int, gate: VirtualGate | None) -> None:
        self._x("UPDATE tracks SET gate = ? WHERE id = ?",
                (json.dumps(gate.to_dict()) if gate else None, track_id))

    def rename_track(self, track_id: int, name: str) -> None:
        self._x("UPDATE tracks SET name = ? WHERE id = ?", (name, track_id))

    # sessions

    def create_session(self, track_id: int, sim: str) -> int:
        return self._x("INSERT INTO sessions (track_id, sim, started_at) VALUES (?, ?, ?)",
                       (track_id, sim, _now()))

    def end_session(self, session_id: int, duration: float) -> None:
        self._x("UPDATE sessions SET ended_at = ?, duration = ? WHERE id = ?", (_now(), duration, session_id))

    def sessions(self, track_id: int | None = None) -> list[dict]:
        where = "WHERE s.track_id = ?" if track_id is not None else ""
        rows = self._q(f"""
            SELECT s.id, s.track_id, t.name AS track, s.sim, s.started_at, s.ended_at, s.duration,
                   COUNT(l.id) AS laps, MIN(l.duration) AS best
            FROM sessions s JOIN tracks t ON t.id = s.track_id
            LEFT JOIN laps l ON l.session_id = s.id
            {where}
            GROUP BY s.id ORDER BY s.started_at DESC, s.id DESC
        """, (track_id,) if track_id is not None else ())
        return [dict(r) for r in rows]

    def session(self, session_id: int) -> dict | None:
        rows = self._q("""
            SELECT s.id, s.track_id, t.name AS track, s.sim, s.started_at, s.ended_at, s.duration
            FROM sessions s JOIN tracks t ON t.id = s.track_id WHERE s.id = ?
        """, (session_id,))
        return dict(rows[0]) if rows else None

    def set_session_track(self, session_id: int, track_id: int) -> None:
        self._x("UPDATE sessions SET track_id = ? WHERE id = ?", (track_id, session_id))

    def delete_session(self, session_id: int) -> None:
        self._x("DELETE FROM sessions WHERE id = ?", (session_id,))

    # samples & crossings

    def insert_samples(self, rows: Iterable[tuple]) -> None:
        with self._lock:
            self._conn.execute("BEGIN")
            self._conn.executemany(
                f"INSERT INTO samples (session_id, {', '.join(SAMPLE_COLS)}) "
                f"VALUES ({', '.join('?' * (len(SAMPLE_COLS) + 1))})", rows)
            self._conn.execute("COMMIT")

    def samples(self, session_id: int, t0: float | None = None, t1: float | None = None,
                cols: Sequence[str] = SAMPLE_COLS) -> dict[str, np.ndarray]:
        for c in cols:
            if c not in SAMPLE_COLS:
                raise ValueError(c)
        sql = f"SELECT {', '.join(cols)} FROM samples WHERE session_id = ?"
        args: list = [session_id]
        if t0 is not None:
            sql += " AND t >= ?"
            args.append(t0)
        if t1 is not None:
            sql += " AND t <= ?"
            args.append(t1)
        with self._lock:
            rows = self._conn.execute(sql + " ORDER BY t", args).fetchall()
        arr = np.array([tuple(r) for r in rows], dtype=float).reshape(len(rows), len(cols))
        return {c: arr[:, i] for i, c in enumerate(cols)}

    def insert_crossing(self, session_id: int, run: int, t: float, c: GateCrossing) -> None:
        self._x("INSERT INTO crossings (session_id, run, t, lap, gate, finished) VALUES (?, ?, ?, ?, ?, ?)",
                (session_id, run, t, c.lap, c.gate, int(c.finished)))

    def crossings(self, session_id: int) -> list[tuple[float, int, GateCrossing]]:
        rows = self._q("SELECT t, run, lap, gate, finished FROM crossings WHERE session_id = ? ORDER BY t",
                       (session_id,))
        return [(r["t"], r["run"], GateCrossing(r["lap"], r["gate"], 0.0, bool(r["finished"]))) for r in rows]

    # laps

    def insert_lap(self, session_id: int, lap: CompletedLap) -> int:
        n = self._q("SELECT COUNT(*) AS n FROM laps WHERE session_id = ?", (session_id,))[0]["n"]
        return self._x(
            "INSERT INTO laps (session_id, run, number, t_start, t_end, duration, timing, splits) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (session_id, lap.run, n + 1, lap.t_start, lap.t_end, lap.duration, lap.timing, json.dumps(lap.splits)))

    def replace_laps(self, session_id: int, laps: Sequence[CompletedLap]) -> None:
        with self._lock:
            self._conn.execute("BEGIN")
            self._conn.execute("DELETE FROM laps WHERE session_id = ?", (session_id,))
            self._conn.executemany(
                "INSERT INTO laps (session_id, run, number, t_start, t_end, duration, timing, splits) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [(session_id, lap.run, i + 1, lap.t_start, lap.t_end, lap.duration, lap.timing,
                  json.dumps(lap.splits)) for i, lap in enumerate(laps)])
            self._conn.execute("COMMIT")

    def laps(self, session_id: int | None = None, track_id: int | None = None) -> list[dict]:
        sql = """
            SELECT l.id, l.session_id, s.track_id, l.run, l.number, l.t_start, l.t_end, l.duration,
                   l.timing, l.splits, s.started_at
            FROM laps l JOIN sessions s ON s.id = l.session_id
        """
        if session_id is not None:
            rows = self._q(sql + " WHERE l.session_id = ? ORDER BY l.number", (session_id,))
        elif track_id is not None:
            rows = self._q(sql + " WHERE s.track_id = ? ORDER BY s.started_at, l.session_id, l.number",
                           (track_id,))
        else:
            rows = self._q(sql + " ORDER BY l.id")
        return [self._lap(r) for r in rows]

    def lap(self, lap_id: int) -> dict | None:
        rows = self._q("""
            SELECT l.id, l.session_id, s.track_id, l.run, l.number, l.t_start, l.t_end, l.duration,
                   l.timing, l.splits, s.started_at
            FROM laps l JOIN sessions s ON s.id = l.session_id WHERE l.id = ?
        """, (lap_id,))
        return self._lap(rows[0]) if rows else None

    def best_lap(self, track_id: int) -> dict | None:
        rows = self._q("""
            SELECT l.id FROM laps l JOIN sessions s ON s.id = l.session_id
            WHERE s.track_id = ? ORDER BY l.duration LIMIT 1
        """, (track_id,))
        return self.lap(rows[0]["id"]) if rows else None

    @staticmethod
    def _lap(r: sqlite3.Row) -> dict:
        d = dict(r)
        d["splits"] = json.loads(d["splits"])
        return d
