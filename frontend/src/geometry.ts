import type { Vec3 } from './api'

/** Index of the last element <= x in a sorted array (clamped). */
export function bisect(arr: number[], x: number): number {
  let lo = 0
  let hi = arr.length - 1
  if (hi < 0 || x <= arr[0]) return 0
  if (x >= arr[hi]) return hi
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1
    if (arr[mid] <= x) lo = mid
    else hi = mid
  }
  return lo
}

/** Position at time `t` along a timed path, linearly interpolated. */
export function positionAt(ts: number[], pos: Vec3[], t: number): Vec3 {
  const i = bisect(ts, t)
  if (i >= ts.length - 1) return pos[pos.length - 1]
  const a = (t - ts[i]) / (ts[i + 1] - ts[i] || 1)
  const p = pos[i]
  const q = pos[i + 1]
  return [p[0] + a * (q[0] - p[0]), p[1] + a * (q[1] - p[1]), p[2] + a * (q[2] - p[2])]
}

/**
 * Sims use Unity's axes: x right, y up, z forward (left-handed).
 * Top-down maps draw x to the right and forward (z) up the screen.
 */
export type Bounds = { minX: number; maxX: number; minZ: number; maxZ: number }

export function bounds(paths: Vec3[][]): Bounds {
  let minX = Infinity
  let maxX = -Infinity
  let minZ = Infinity
  let maxZ = -Infinity
  for (const path of paths)
    for (const [x, , z] of path) {
      if (x < minX) minX = x
      if (x > maxX) maxX = x
      if (z < minZ) minZ = z
      if (z > maxZ) maxZ = z
    }
  return { minX, maxX, minZ, maxZ }
}

export function mapProjection(b: Bounds, width: number, height: number, pad = 16) {
  const w = Math.max(b.maxX - b.minX, 1)
  const h = Math.max(b.maxZ - b.minZ, 1)
  const k = Math.min((width - 2 * pad) / w, (height - 2 * pad) / h)
  const ox = (width - k * w) / 2
  const oy = (height - k * h) / 2
  return {
    k,
    x: (p: Vec3) => ox + (p[0] - b.minX) * k,
    y: (p: Vec3) => height - oy - (p[2] - b.minZ) * k,
  }
}

export function pathD(points: Vec3[], x: (p: Vec3) => number, y: (p: Vec3) => number): string {
  let d = ''
  for (let i = 0; i < points.length; i++) d += `${i ? 'L' : 'M'}${x(points[i]).toFixed(1)},${y(points[i]).toFixed(1)}`
  return d
}
