"""A synthetic pilot flying a synthetic track.

Used by the tests and by demo mode, so the project can be tried without a sim.
The track is a figure-8 with an over/under at the crossover, which is also
the worst case for projecting laps onto a reference line.

Each lap gets its own "form": grip varies by section (so corner speeds
change), and the racing line wanders a metre or two either side. Some laps get
a proper mistake: a wide, slow moment somewhere on the lap.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterator

import numpy as np

from .models import Sample

TOP_SPEED = 32.0  # m/s
A_LAT = 26.0  # m/s², lateral grip
A_ACC = 14.0
A_BRAKE = 22.0
DT = 1 / 60


class FigureEight:
    name = "Demo: Figure-8 Over-Under"

    def __init__(self, step: float = 0.25):
        u = np.linspace(0, 2 * math.pi, 4000, endpoint=False)
        pts = self._at(u)
        seg = np.linalg.norm(np.diff(np.vstack([pts, pts[:1]]), axis=0), axis=1)
        s_u = np.concatenate([[0.0], np.cumsum(seg)])
        self.length = float(s_u[-1])
        self.s = np.arange(0.0, self.length, step)
        u_closed = np.concatenate([u, [2 * math.pi]])
        self.pts = self._at(np.interp(self.s, s_u, u_closed))
        n = len(self.s)
        fwd = np.roll(self.pts, -1, axis=0) - np.roll(self.pts, 1, axis=0)
        self.tangent = fwd / np.linalg.norm(fwd, axis=1)[:, None]
        right = np.cross([0.0, 1.0, 0.0], self.tangent)
        self.right = right / np.linalg.norm(right, axis=1)[:, None]
        # Curvature of the horizontal path (the vertical changes here are gentle).
        dtan = (np.roll(self.tangent, -1, axis=0) - np.roll(self.tangent, 1, axis=0)) / (2 * step)
        self.curvature = np.linalg.norm(dtan, axis=1)
        self.step = step
        self.n = n

    @staticmethod
    def _at(u: np.ndarray) -> np.ndarray:
        # Unity axes: x right, y up, z forward. Starts heading +z at the crossover,
        # which it passes 7 m higher on the way out than on the way back.
        # About 430 m with a slalom in the first lobe; 5.8 m tightest radius.
        x = 36.0 * np.sin(2 * u) + 2.0 * np.sin(10 * u) * np.clip(np.sin(u), 0, 1)
        z = 70.0 * np.sin(u) + 3.0 * np.sin(3 * u)
        y = 6.0 + 3.5 * np.cos(u) + 1.2 * np.sin(3 * u)
        return np.column_stack([x, y, z])

    def wrap(self, s: np.ndarray | float):
        return np.mod(s, self.length)

    def sample(self, arr: np.ndarray, s: np.ndarray | float):
        return np.interp(self.wrap(s), self.s, arr, period=self.length)


@dataclass
class LapForm:
    speed: np.ndarray  # target speed along the lap grid
    lateral: np.ndarray  # metres right of the centreline
    vertical: np.ndarray


def _smooth_bumps(track: FigureEight, rng: np.random.Generator, count: int, amp: float,
                  width: tuple[float, float]) -> np.ndarray:
    out = np.zeros(track.n)
    for _ in range(count):
        c = rng.uniform(0.1, 0.9) * track.length
        w = rng.uniform(*width)
        out += rng.normal(0, amp) * np.exp(-(((track.s - c) / w) ** 2))
    return out


def lap_form(track: FigureEight, rng: np.random.Generator, skill: float = 1.0,
             mistake: bool = False) -> LapForm:
    sections = 8
    grip_nodes = rng.normal(skill, 0.045, sections + 1)
    grip_nodes[-1] = grip_nodes[0]
    grip = np.interp(track.s, np.linspace(0, track.length, sections + 1), grip_nodes)
    lateral = _smooth_bumps(track, rng, 6, 1.0, (15, 40))
    vertical = _smooth_bumps(track, rng, 4, 0.6, (15, 40))

    v = np.minimum(TOP_SPEED * np.clip(grip, 0.8, 1.1),
                   np.sqrt(A_LAT * np.clip(grip, 0.5, 1.5) / np.maximum(track.curvature, 1e-4)))
    if mistake:
        c = rng.uniform(0.15, 0.85) * track.length
        dip = np.exp(-(((track.s - c) / 12.0) ** 2))
        v = v * (1 - 0.45 * dip)
        lateral = lateral + rng.choice([-1, 1]) * 4.0 * dip
    # Forward/backward passes so the pilot can actually brake and accelerate that hard.
    for _ in range(2):
        for i in range(1, track.n):
            v[i] = min(v[i], math.sqrt(v[i - 1] ** 2 + 2 * A_ACC * track.step))
        v[0] = min(v[0], math.sqrt(v[-1] ** 2 + 2 * A_ACC * track.step))
        for i in range(track.n - 2, -1, -1):
            v[i] = min(v[i], math.sqrt(v[i + 1] ** 2 + 2 * A_BRAKE * track.step))
    return LapForm(v, lateral, vertical)


def _quat_from_motion(fwd: np.ndarray, accel: np.ndarray) -> tuple[float, float, float, float]:
    """A plausible attitude: yaw along travel, pitched forward with speed, rolled into turns."""
    yaw = math.atan2(fwd[0], fwd[2])
    pitch = math.radians(20.0) + 0.02 * float(np.dot(accel, fwd))
    right = np.array([math.cos(yaw), 0.0, -math.sin(yaw)])
    roll = -math.atan2(float(np.dot(accel, right)), 9.81)
    cy, sy = math.cos(yaw / 2), math.sin(yaw / 2)
    cp, sp = math.cos(pitch / 2), math.sin(pitch / 2)
    cr, sr = math.cos(roll / 2), math.sin(roll / 2)
    # Unity applies Z (roll), then X (pitch), then Y (yaw).
    w = cy * cp * cr + sy * sp * sr
    x = cy * sp * cr + sy * cp * sr
    y = sy * cp * cr - cy * sp * sr
    z = cy * cp * sr - sy * sp * cr
    return (x, y, z, w)


def fly(track: FigureEight, laps: int, seed: int = 0, skill: float = 1.0,
        mistake_rate: float = 0.2, t0: float = 0.0) -> Iterator[Sample]:
    """Fly `laps` laps from a standing start 10 m behind the start/finish line."""
    rng = np.random.default_rng(seed)
    forms = [lap_form(track, rng, skill, mistake=rng.random() < mistake_rate) for _ in range(laps + 1)]
    s = -10.0
    v = 0.0
    t = t0
    prev_pos = None
    prev_vel = np.zeros(3)
    end = laps * track.length + 5.0
    while s < end:
        form = forms[max(int(math.floor(s / track.length)), 0)]
        target = track.sample(form.speed, s)
        v = min(target, v + A_ACC * DT) if target > v else max(target, v - A_BRAKE * DT)
        s += v * DT
        t += DT
        base = np.array([track.sample(track.pts[:, k], s) for k in range(3)])
        right = np.array([track.sample(track.right[:, k], s) for k in range(3)])
        # Ease the line in from the centre on the standing start.
        ease = min(max((s + 10.0) / 30.0, 0.0), 1.0)
        pos = base + ease * (track.sample(form.lateral, s) * right
                             + np.array([0.0, track.sample(form.vertical, s), 0.0]))
        if s < 0:
            pos[1] = base[1] * max((s + 10.0) / 10.0, 0.15)
        vel = (pos - prev_pos) / DT if prev_pos is not None else np.zeros(3)
        accel = (vel - prev_vel) / DT
        spd = float(np.linalg.norm(vel))
        fwd = vel / spd if spd > 0.1 else np.array([0.0, 0.0, 1.0])
        att = _quat_from_motion(fwd, accel)
        yaw_rate = 0.0
        if prev_pos is not None and np.linalg.norm(prev_vel) > 0.1:
            h0 = math.atan2(prev_vel[0], prev_vel[2])
            h1 = math.atan2(fwd[0], fwd[2])
            yaw_rate = math.degrees((h1 - h0 + math.pi) % (2 * math.pi) - math.pi) / DT
        throttle = float(np.clip(0.45 + 0.03 * float(np.dot(accel, fwd)), 0.0, 1.0))
        yield Sample(
            t=t,
            pos=tuple(float(x) for x in pos),
            vel=tuple(float(x) for x in vel),
            att=att,
            gyro=(0.0, 0.0, yaw_rate),
            sticks=(throttle, float(np.clip(yaw_rate / 400, -1, 1)), 0.2, 0.0),
        )
        prev_pos, prev_vel = pos, vel


def fly_arrays(track: FigureEight, laps: int, seed: int = 0, **kw) -> tuple[np.ndarray, np.ndarray]:
    samples = list(fly(track, laps, seed, **kw))
    return np.array([x.t for x in samples]), np.array([x.pos for x in samples])
