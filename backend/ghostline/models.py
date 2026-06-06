"""Sim-agnostic telemetry model.

Every source (Liftoff UDP, Velocidrone WebSocket, the synthetic pilot) is
translated into these events, so everything downstream — lap detection,
storage, analysis — never needs to know which sim produced the data.

Coordinates stay in Unity world space because both sims are Unity games:
x right, y up, z forward (left-handed), metres. The frontend flips z when it
hands positions to three.js.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Union

Vec3 = tuple[float, float, float]
Quat = tuple[float, float, float, float]  # x, y, z, w


@dataclass(slots=True)
class Sample:
    """One telemetry frame. `t` is the source clock in seconds."""

    t: float
    pos: Vec3
    vel: Vec3 | None = None
    att: Quat | None = None
    gyro: Vec3 | None = None  # deg/s: pitch, roll, yaw
    # Normalised sticks: throttle 0..1, yaw/pitch/roll -1..1. Velocidrone does not send these.
    sticks: tuple[float, float, float, float] | None = None


@dataclass(slots=True)
class GateCrossing:
    """A native gate crossing reported by the sim (Velocidrone races only).

    `race_time` is seconds since GO. `gate` is 1-based and resets every lap.
    """

    lap: int
    gate: int
    race_time: float
    finished: bool = False


@dataclass(slots=True)
class RaceStart:
    """GO. Lets the recorder map race time onto the telemetry clock."""


@dataclass(slots=True)
class RaceEnd:
    aborted: bool = False


@dataclass(slots=True)
class TrackInfo:
    name: str


@dataclass(slots=True)
class Reset:
    """The drone was reset to the start; laps never span a reset."""


Event = Union[Sample, GateCrossing, RaceStart, RaceEnd, TrackInfo, Reset]
