import { Line, OrbitControls } from '@react-three/drei'
import { Canvas } from '@react-three/fiber'
import { useMemo } from 'react'
import { Color } from 'three'
import type { Vec3 } from '../api'
import { useThemeColors } from './useThemeColors'
import { useWidth } from './useWidth'

type P3 = [number, number, number]

/** Unity (x right, y up, z forward; left-handed) to three.js (right-handed). */
const toThree = (p: Vec3): P3 => [p[0], p[1], -p[2]]

const SLOPE_FULL_COLOUR = 0.005 // s/m: losing 5 ms per metre is full red

type Props = {
  /** Your path, one point per metre of the reference, so it lines up with `slope`. */
  lapPath: Vec3[]
  ghostPath: Vec3[]
  /** How fast the delta grows at each point: s/m, positive = losing time. */
  slope: number[]
  you: Vec3 | null
  ghost: Vec3 | null
  highlight?: [number, number] | null
  height: number
}

export function Flight3D({ lapPath, ghostPath, slope, you, ghost, highlight, height }: Props) {
  const c = useThemeColors()
  const [box, width] = useWidth<HTMLDivElement>()

  const geo = useMemo(() => {
    const pts = lapPath.map(toThree)
    const ghostPts = ghostPath.map(toThree)
    let minY = Infinity
    let [x0, x1, z0, z1] = [Infinity, -Infinity, Infinity, -Infinity]
    for (const [x, y, z] of [...pts, ...ghostPts]) {
      minY = Math.min(minY, y)
      x0 = Math.min(x0, x)
      x1 = Math.max(x1, x)
      z0 = Math.min(z0, z)
      z1 = Math.max(z1, z)
    }
    const center: P3 = [(x0 + x1) / 2, minY, (z0 + z1) / 2]
    const size = Math.max(x1 - x0, z1 - z0, 20)
    const alongZ = z1 - z0 > x1 - x0

    // A shadow on the ground makes height readable.
    const shadow = pts.map(([x, , z]): P3 => [x, minY - 0.4, z])

    // A square race gate at the start of the ghost's lap, facing its direction of travel.
    let gate: P3[] | null = null
    if (ghostPts.length > 3) {
      const a = ghostPts[0]
      const b = ghostPts[3]
      const n = Math.hypot(b[0] - a[0], b[2] - a[2]) || 1
      const side = [-(b[2] - a[2]) / n, (b[0] - a[0]) / n]
      const w = 1.6
      const corner = (sx: number, sy: number): P3 => [a[0] + side[0] * w * sx, a[1] + w * sy, a[2] + side[1] * w * sx]
      gate = [corner(-1, -1), corner(1, -1), corner(1, 1), corner(-1, 1), corner(-1, -1)]
    }
    return { pts, ghostPts, shadow, gate, center, size, alongZ, minY }
  }, [lapPath, ghostPath])

  // Diverging colour: blue where you gained, neutral where even, red where you lost.
  // A fixed scale keeps colours comparable from one comparison to the next.
  const colors = useMemo(() => {
    const neutral = new Color(c.neutral)
    const gain = new Color(c.gain)
    const loss = new Color(c.loss)
    return slope.map((s) => {
      const t = Math.max(-1, Math.min(1, s / SLOPE_FULL_COLOUR))
      return neutral.clone().lerp(t < 0 ? gain : loss, Math.abs(t))
    })
  }, [slope, c])

  const { center, size } = geo
  // Look across the track's long side so it fills a wide viewport; back off on narrow ones.
  const aspect = width / height
  const k = Math.min(Math.max(1.9 / aspect, 1), 2.4)
  const eye: P3 = geo.alongZ
    ? [center[0] + size * 0.85 * k, center[1] + size * 0.75 * k, center[2] + size * 0.2 * k]
    : [center[0] + size * 0.2 * k, center[1] + size * 0.75 * k, center[2] + size * 0.85 * k]
  const hl = highlight ? geo.pts.slice(highlight[0], highlight[1] + 1) : null
  const grid = Math.ceil((size * 1.4) / 10)

  return (
    <div ref={box} style={{ width: '100%', height }}>
      {width > 0 && (
        <Canvas camera={{ position: eye, fov: 40, near: 0.5, far: size * 20 }} dpr={[1, 2]} aria-label="3D view of both laps">
          <ambientLight intensity={0.9} />
          <directionalLight position={[size, size * 2, size]} intensity={0.6} />
          <gridHelper args={[grid * 10, grid, c.axis, c.hairline]} position={[center[0], geo.minY - 0.5, center[2]]} />
          <Line points={geo.shadow} color={c.axis} lineWidth={1} transparent opacity={0.7} />
          <Line points={geo.ghostPts} color={c.ghost} lineWidth={2} transparent opacity={0.9} />
          <Line points={geo.pts} vertexColors={colors} lineWidth={4.5} />
          {hl && hl.length > 1 && <Line points={hl} color={c.ink} lineWidth={10} transparent opacity={0.18} />}
          {geo.gate && <Line points={geo.gate} color={c.brand} lineWidth={3.5} />}
          {ghost && (
            <mesh position={toThree(ghost)}>
              <sphereGeometry args={[1.1, 20, 20]} />
              <meshStandardMaterial color={c.ghost} transparent opacity={0.75} />
            </mesh>
          )}
          {you && (
            <mesh position={toThree(you)}>
              <sphereGeometry args={[1.1, 20, 20]} />
              <meshStandardMaterial color={c.ink} />
            </mesh>
          )}
          <OrbitControls target={center} enableDamping makeDefault maxPolarAngle={Math.PI / 2.05} />
        </Canvas>
      )}
    </div>
  )
}
