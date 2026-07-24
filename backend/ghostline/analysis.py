"""Lap comparison by distance along a reference line.

Comparing two laps sample-by-sample in time is meaningless: after the first
corner the pilots are in different places. Motorsport telemetry compares at
the same *place* instead, and so does this module:

1. The reference lap is resampled into a polyline with even spacing.
2. Every sample of the other lap is projected onto that polyline, giving its
   distance along the reference, `s`, plus how far off the line it was.
3. Each lap then has a time-at-distance curve, and
   `delta(s) = t_lap(s) - t_ref(s)` says how far ahead or behind it is at every
   metre of the track.

Projection is a windowed forward search, so tracks that cross over themselves
(figure-8s, dive gaps under an earlier section) do not make it jump to the
wrong part of the lap.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

UP = np.array([0.0, 1.0, 0.0])


@dataclass
class LapTrace:
    """A lap's samples, with `t` in seconds from the lap start.

    The first and last rows are interpolated to sit exactly on the lap
    boundaries, so the trace starts and ends on the timing gate.
    """

    t: np.ndarray  # (N,)
    pos: np.ndarray  # (N, 3)

    @property
    def duration(self) -> float:
        return float(self.t[-1])

    def speed(self) -> np.ndarray:
        if len(self.t) < 2:
            return np.zeros(len(self.t))
        return np.linalg.norm(np.gradient(self.pos, self.t, axis=0), axis=1)


def extract_lap(t: np.ndarray, pos: np.ndarray, t_start: float, t_end: float) -> LapTrace:
    inner = (t > t_start) & (t < t_end)
    ts = np.concatenate([[t_start], t[inner], [t_end]])
    ps = np.vstack([
        [np.interp(t_start, t, pos[:, k]) for k in range(3)],
        pos[inner],
        [np.interp(t_end, t, pos[:, k]) for k in range(3)],
    ])
    # Drop duplicate timestamps (a sample sitting exactly on the boundary).
    keep = np.concatenate([[True], np.diff(ts) > 1e-9])
    return LapTrace(ts[keep] - t_start, ps[keep])


class ReferenceLine:
    def __init__(self, trace: LapTrace, step: float = 0.5):
        seg = np.linalg.norm(np.diff(trace.pos, axis=0), axis=1)
        s_raw = np.concatenate([[0.0], np.cumsum(seg)])
        keep = np.concatenate([[True], seg > 1e-6])
        s_raw, pos, t = s_raw[keep], trace.pos[keep], trace.t[keep]
        self.length = float(s_raw[-1])
        n = max(int(np.ceil(self.length / step)), 1)
        self.s = np.linspace(0.0, self.length, n + 1)
        self.step = self.length / n if n else step
        self.pts = np.column_stack([np.interp(self.s, s_raw, pos[:, k]) for k in range(3)])
        self.t = np.interp(self.s, s_raw, t)
        speed = trace.speed()[keep]
        self.speed = np.interp(self.s, s_raw, speed)
        self._a = self.pts[:-1]
        self._ab = self.pts[1:] - self.pts[:-1]
        self._len2 = np.maximum(np.einsum("ij,ij->i", self._ab, self._ab), 1e-12)

    def time_at(self, s):
        return np.interp(s, self.s, self.t)

    def point_at(self, s):
        return np.column_stack([np.interp(s, self.s, self.pts[:, k]) for k in range(3)])

    def _closest(self, q: np.ndarray, lo: int, hi: int) -> tuple[float, float, int, float]:
        a = self._a[lo:hi]
        ab = self._ab[lo:hi]
        u = np.clip(np.einsum("ij,ij->i", q - a, ab) / self._len2[lo:hi], 0.0, 1.0)
        d = np.linalg.norm(a + u[:, None] * ab - q, axis=1)
        j = int(np.argmin(d))
        return float(self.s[lo + j] + u[j] * self.step), float(d[j]), lo + j, float(u[j])

    def project_one(self, q, s_prev: float, window: float = 20.0, back: float = 5.0,
                    recover_dist: float = 12.0) -> tuple[float, float]:
        """Distance along the line for point `q`, searching near `s_prev`. Returns (s, distance off line)."""
        q = np.asarray(q, dtype=float)
        nseg = len(self._a)
        lo = max(int((s_prev - back) / self.step), 0)
        hi = min(int(np.ceil((s_prev + window) / self.step)) + 1, nseg)
        s, dist, _, _ = self._closest(q, lo, max(hi, lo + 1))
        if dist > recover_dist and hi < nseg:
            # Lost the line (crash, big cut): search everything ahead.
            s2, dist2, _, _ = self._closest(q, lo, nseg)
            if dist2 < dist:
                s, dist = s2, dist2
        return s, dist

    def project(self, points: np.ndarray) -> np.ndarray:
        s_out = np.empty(len(points))
        s_prev = 0.0
        for i, q in enumerate(points):
            s_prev, _ = self.project_one(q, s_prev, back=0.0 if i == 0 else 5.0)
            s_out[i] = s_prev
        return s_out

    def offsets(self, points: np.ndarray, s: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Signed horizontal (+ = right of the line) and vertical (+ = above) offsets."""
        on_line = self.point_at(s)
        idx = np.clip((s / self.step).astype(int), 0, len(self._ab) - 1)
        tangent = self._ab[idx] / np.sqrt(self._len2[idx])[:, None]
        right = np.cross(UP, tangent)
        norm = np.linalg.norm(right, axis=1)
        right = right / np.where(norm > 1e-9, norm, 1.0)[:, None]
        diff = points - on_line
        return np.einsum("ij,ij->i", diff, right), diff[:, 1]


def project_lap(trace: LapTrace, ref: ReferenceLine) -> np.ndarray:
    """Distance along the reference for every sample, made non-decreasing."""
    s = ref.project(trace.pos)
    s[0], s[-1] = 0.0, ref.length  # both laps start and finish on the same gate
    return np.clip(np.maximum.accumulate(s), 0.0, ref.length)


def time_at_distance(trace: LapTrace, ref: ReferenceLine,
                     s: np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Strictly increasing s along the reference, with the lap's time and speed at each."""
    if s is None:
        s = project_lap(trace, ref)
    s_u, first = np.unique(s, return_index=True)
    return s_u, trace.t[first], trace.speed()[first]


@dataclass
class Comparison:
    s: np.ndarray
    delta: np.ndarray
    speed_lap: np.ndarray
    speed_ref: np.ndarray
    lateral: np.ndarray
    vertical: np.ndarray
    sector_bounds: np.ndarray  # distances, starting at 0 and ending at length
    sectors_lap: np.ndarray
    sectors_ref: np.ndarray
    length: float


def compare(lap: LapTrace, ref: LapTrace, *, grid_step: float = 1.0, sectors: int = 6,
            sector_bounds: np.ndarray | None = None, ref_line: ReferenceLine | None = None) -> Comparison:
    line = ref_line or ReferenceLine(ref)
    s_proj = project_lap(lap, line)
    s_lap, t_lap, v_lap = time_at_distance(lap, line, s_proj)

    n = max(int(round(line.length / grid_step)), 2)
    grid = np.linspace(0.0, line.length, n + 1)
    t_l = np.interp(grid, s_lap, t_lap)
    t_r = line.time_at(grid)
    lat, vert = line.offsets(lap.pos, s_proj)
    _, first = np.unique(s_proj, return_index=True)

    if sector_bounds is None:
        sector_bounds = np.linspace(0.0, line.length, sectors + 1)
    tb_l = np.interp(sector_bounds, s_lap, t_lap)
    tb_r = line.time_at(sector_bounds)
    return Comparison(
        s=grid,
        delta=t_l - t_r,
        speed_lap=np.interp(grid, s_lap, v_lap),
        speed_ref=np.interp(grid, line.s, line.speed),
        lateral=np.interp(grid, s_lap, lat[first]),
        vertical=np.interp(grid, s_lap, vert[first]),
        sector_bounds=np.asarray(sector_bounds, dtype=float),
        sectors_lap=np.diff(tb_l),
        sectors_ref=np.diff(tb_r),
        length=line.length,
    )


def insights(c: Comparison, top_losses: int = 3, top_gains: int = 2, smooth_m: float = 10.0,
             min_time: float = 0.05) -> list[dict]:
    """Where the lap lost (or gained) the most time against the reference, and why.

    A region is a stretch of track where the delta keeps growing (or keeps
    shrinking). Short pauses in between are bridged, so one mistake reads as
    one insight rather than several overlapping ones.
    """
    step = c.s[1] - c.s[0]
    k = max(int(round(smooth_m / step)), 1)
    slope = np.convolve(np.gradient(c.delta, c.s), np.ones(k) / k, mode="same")
    found: list[dict] = []
    for sign, top in ((1.0, top_losses), (-1.0, top_gains)):
        regions = _regions(sign * slope > 0.002, bridge=k)
        scored = [(float(c.delta[b] - c.delta[a]), a, b) for a, b in regions]
        scored = [x for x in scored if sign * x[0] >= min_time]
        scored.sort(key=lambda x: -abs(x[0]))
        found += [_describe(c, a, b, dt, int(a + np.argmax(sign * slope[a:b + 1])))
                  for dt, a, b in scored[:top]]
    return found


def _regions(mask: np.ndarray, bridge: int) -> list[tuple[int, int]]:
    """[start, end] index pairs of runs of True, joining runs separated by < `bridge` samples."""
    idx = np.flatnonzero(mask)
    if len(idx) == 0:
        return []
    breaks = np.flatnonzero(np.diff(idx) > bridge)
    starts = np.concatenate([[idx[0]], idx[breaks + 1]])
    ends = np.concatenate([idx[breaks], [idx[-1]]])
    return [(int(a), int(b)) for a, b in zip(starts, ends) if b > a]


def _describe(c: Comparison, a: int, b: int, dt: float, core: int, core_m: float = 15.0) -> dict:
    """Explain a region using what happened around its worst (or best) point."""
    step = c.s[1] - c.s[0]
    w = max(int(round(core_m / step)), 1)
    sl = slice(max(core - w, a), min(core + w, b) + 1)
    min_lap, min_ref = float(c.speed_lap[sl].min()), float(c.speed_ref[sl].min())
    lat = float(c.lateral[sl][np.argmax(np.abs(c.lateral[sl]))])
    vert = float(c.vertical[sl][np.argmax(np.abs(c.vertical[sl]))])

    def sector_of(i: int) -> int:
        return min(int(np.searchsorted(c.sector_bounds, c.s[i], side="right")), len(c.sectors_lap))

    reasons = []
    dv = min_lap - min_ref
    if abs(dv) >= 1.0:
        reasons.append(f"minimum speed {abs(dv) * 3.6:.0f} km/h {'higher' if dv > 0 else 'lower'}")
    if abs(lat) >= 1.0:
        reasons.append(f"line {abs(lat):.1f} m {'right' if lat > 0 else 'left'} of the ghost")
    if abs(vert) >= 1.0:
        reasons.append(f"{abs(vert):.1f} m {'higher' if vert > 0 else 'lower'}")
    s1, s2 = sector_of(a), sector_of(b)
    sectors = f"sector {s1}" if s1 == s2 else f"sectors {s1}-{s2}"
    text = f"{'Lost' if dt > 0 else 'Gained'} {abs(dt):.2f}s from {c.s[a]:.0f} m to {c.s[b]:.0f} m ({sectors})."
    if reasons:
        text += f" {'Worst' if dt > 0 else 'Best'} at {c.s[core]:.0f} m: " + ", ".join(reasons) + "."
    return {
        "kind": "loss" if dt > 0 else "gain",
        "s_start": float(c.s[a]),
        "s_end": float(c.s[b]),
        "s_core": float(c.s[core]),
        "time": dt,
        "min_speed_lap": min_lap,
        "min_speed_ref": min_ref,
        "lateral": lat,
        "vertical": vert,
        "text": text,
    }


def theoretical_best(sector_times: np.ndarray) -> float:
    """Sum of each sector's best, given a (laps, sectors) matrix."""
    return float(np.nanmin(sector_times, axis=0).sum())
