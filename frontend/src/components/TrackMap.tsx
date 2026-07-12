import { useMemo } from 'react'
import type { Gate, Vec3 } from '../api'
import { bounds, mapProjection, pathD } from '../geometry'
import { useWidth } from './useWidth'

type Layer = { key: string; points: Vec3[]; stroke: string; width: number; opacity?: number }
type Marker = { key: string; pos: Vec3; fill: string; r?: number; label?: string }

type Props = {
  layers: Layer[]
  markers?: Marker[]
  gate?: Gate | null
  height?: number
  /** Make one layer clickable: returns the index of the point nearest the click. */
  pickLayer?: string
  onPick?: (index: number) => void
  label: string
}

/** Top-down view of flight paths: x to the right, forward (z) up the screen. */
export function TrackMap({ layers, markers = [], gate, height = 360, pickLayer, onPick, label }: Props) {
  const [ref, width] = useWidth<HTMLDivElement>()
  const proj = useMemo(() => {
    const pts = layers.map((l) => l.points).filter((p) => p.length)
    if (!pts.length || !width) return null
    return mapProjection(bounds(pts), width, height, 20)
  }, [layers, width, height])

  const pickable = layers.find((l) => l.key === pickLayer)

  const handleClick = (e: React.MouseEvent<SVGSVGElement>) => {
    if (!proj || !pickable || !onPick) return
    const rect = e.currentTarget.getBoundingClientRect()
    const cx = e.clientX - rect.left
    const cy = e.clientY - rect.top
    let best = -1
    let bestD = Infinity
    pickable.points.forEach((p, i) => {
      const d = (proj.x(p) - cx) ** 2 + (proj.y(p) - cy) ** 2
      if (d < bestD) {
        bestD = d
        best = i
      }
    })
    if (best >= 0 && bestD < 24 ** 2) onPick(best)
  }

  return (
    <div className="map" ref={ref}>
      {proj && (
        <svg
          width={width}
          height={height}
          viewBox={`0 0 ${width} ${height}`}
          role="img"
          aria-label={label}
          className={pickable ? 'pickable' : undefined}
          onClick={handleClick}
        >
          {layers.map((l) => (
            <path
              key={l.key}
              d={pathD(l.points, proj.x, proj.y)}
              fill="none"
              stroke={l.stroke}
              strokeWidth={l.width}
              strokeOpacity={l.opacity ?? 1}
              strokeLinejoin="round"
              strokeLinecap="round"
            />
          ))}
          {gate && <GateMark gate={gate} x={proj.x} y={proj.y} k={proj.k} />}
          {markers.map((m) => (
            <g key={m.key}>
              <circle
                cx={proj.x(m.pos)}
                cy={proj.y(m.pos)}
                r={m.r ?? 6}
                fill={m.fill}
                stroke="var(--surface)"
                strokeWidth={2}
              />
              {m.label && (
                <text x={proj.x(m.pos) + 10} y={proj.y(m.pos) + 4} className="axis-label" style={{ fill: 'var(--ink-2)' }}>
                  {m.label}
                </text>
              )}
            </g>
          ))}
        </svg>
      )}
    </div>
  )
}

function GateMark({ gate, x, y, k }: { gate: Gate; x: (p: Vec3) => number; y: (p: Vec3) => number; k: number }) {
  // The gate is a plane; from above it's a line across the direction of travel.
  const [nx, , nz] = gate.normal
  const len = Math.hypot(nx, nz) || 1
  const across: Vec3 = [-nz / len, 0, nx / len]
  const r = Math.max(gate.radius, 4 / k)
  const c = gate.center
  const a: Vec3 = [c[0] + across[0] * r, c[1], c[2] + across[2] * r]
  const b: Vec3 = [c[0] - across[0] * r, c[1], c[2] - across[2] * r]
  return (
    <g>
      <line x1={x(a)} y1={y(a)} x2={x(b)} y2={y(b)} stroke="var(--brand)" strokeWidth={4} strokeLinecap="round" />
      <text x={x(a) + 8} y={y(a)} className="axis-label" style={{ fill: 'var(--brand)', fontWeight: 600 }}>
        Start/finish
      </text>
    </g>
  )
}
