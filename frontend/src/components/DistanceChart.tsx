import { scaleLinear } from 'd3-scale'
import { area, line } from 'd3-shape'
import { useMemo, useRef, useState, type ReactNode } from 'react'
import { bisect } from '../geometry'
import { useWidth } from './useWidth'

export type Series = {
  key: string
  label: string
  values: number[]
  color: string
  format: (v: number) => string
}

type Props = {
  title: ReactNode
  aside?: ReactNode
  x: number[]
  series: Series[]
  yFormat: (v: number) => string
  /** Fill above zero as loss and below as gain (for the time delta). */
  diverging?: boolean
  zeroLine?: boolean
  symmetric?: boolean
  height?: number
  hover: number | null
  onHover: (i: number | null) => void
  sectors?: number[]
  highlight?: [number, number] | null
}

const M = { top: 8, right: 12, bottom: 22, left: 44 }

/** A line chart over distance along the lap, sharing its hover with the rest of the page. */
export function DistanceChart({
  title,
  aside,
  x,
  series,
  yFormat,
  diverging,
  zeroLine,
  symmetric,
  height = 150,
  hover,
  onHover,
  sectors,
  highlight,
}: Props) {
  const [ref, width] = useWidth<HTMLDivElement>()
  const [pointerX, setPointerX] = useState<number | null>(null)
  const overlay = useRef<SVGRectElement>(null)
  const innerW = Math.max(width - M.left - M.right, 10)
  const innerH = height - M.top - M.bottom

  const { xs, ys, paths, ticks } = useMemo(() => {
    const xs = scaleLinear().domain([x[0] ?? 0, x[x.length - 1] ?? 1]).range([0, innerW])
    let lo = Infinity
    let hi = -Infinity
    for (const s of series)
      for (const v of s.values) {
        if (v < lo) lo = v
        if (v > hi) hi = v
      }
    if (zeroLine || diverging) {
      lo = Math.min(lo, 0)
      hi = Math.max(hi, 0)
    }
    if (symmetric) {
      const m = Math.max(Math.abs(lo), Math.abs(hi))
      lo = -m
      hi = m
    }
    const ys = scaleLinear().domain([lo, hi]).range([innerH, 0]).nice(4)
    const mk = (vals: number[]) =>
      line<number>()
        .x((_, i) => xs(x[i]))
        .y((v) => ys(v))(vals) ?? ''
    const paths = series.map((s) => mk(s.values))
    let fills: { pos: string; neg: string } | null = null
    if (diverging && series[0]) {
      const v = series[0].values
      const a = (clip: (n: number) => number) =>
        area<number>()
          .x((_, i) => xs(x[i]))
          .y0(ys(0))
          .y1((n) => ys(clip(n)))(v) ?? ''
      fills = { pos: a((n) => Math.max(n, 0)), neg: a((n) => Math.min(n, 0)) }
    }
    return { xs, ys, paths: { lines: paths, fills }, ticks: ys.ticks(4) }
  }, [x, series, innerW, innerH, diverging, zeroLine, symmetric])

  const xTicks = xs.ticks(Math.max(Math.floor(innerW / 90), 2))

  const indexAt = (clientX: number) => {
    const rect = overlay.current?.getBoundingClientRect()
    if (!rect) return null
    const px = clientX - rect.left
    setPointerX(px)
    return bisectNearest(x, xs.invert(px))
  }

  const onKey = (e: React.KeyboardEvent) => {
    const step = Math.max(Math.round(x.length / 100), 1)
    if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {
      e.preventDefault()
      const cur = hover ?? 0
      const next = Math.min(Math.max(cur + (e.key === 'ArrowRight' ? step : -step), 0), x.length - 1)
      setPointerX(xs(x[next]))
      onHover(next)
    } else if (e.key === 'Escape') onHover(null)
  }

  const hx = hover != null && x[hover] != null ? xs(x[hover]) : null
  const tooltipLeft = hx != null ? (hx > innerW - 170 ? hx + M.left - 172 : hx + M.left + 12) : 0

  return (
    <div className="chart" ref={ref}>
      <div className="chart-title">
        <b>{title}</b>
        {aside}
      </div>
      {width > 0 && (
        <svg width={width} height={height} role="img" aria-label={typeof title === 'string' ? title : undefined}>
          <g transform={`translate(${M.left},${M.top})`}>
            {highlight && (
              <rect
                x={xs(highlight[0])}
                width={Math.max(xs(highlight[1]) - xs(highlight[0]), 1)}
                y={0}
                height={innerH}
                fill="var(--surface-2)"
              />
            )}
            {ticks.map((t) => (
              <g key={t} transform={`translate(0,${ys(t)})`}>
                <line className={t === 0 && (zeroLine || diverging) ? 'baseline' : 'gridline'} x2={innerW} />
                <text className="axis-label" x={-8} dy="0.32em" textAnchor="end">
                  {yFormat(t)}
                </text>
              </g>
            ))}
            {sectors?.slice(1, -1).map((s) => (
              <line key={s} className="gridline" x1={xs(s)} x2={xs(s)} y1={0} y2={innerH} />
            ))}
            {paths.fills && (
              <>
                <path d={paths.fills.pos} fill="var(--loss-wash)" />
                <path d={paths.fills.neg} fill="var(--gain-wash)" />
              </>
            )}
            {series.map((s, i) => (
              <path
                key={s.key}
                d={paths.lines[i]}
                fill="none"
                stroke={s.color}
                strokeWidth={2}
                strokeLinejoin="round"
                strokeLinecap="round"
              />
            ))}
            <g transform={`translate(0,${innerH})`}>
              <line className="baseline" x2={innerW} />
              {xTicks.map((t) => (
                <text key={t} className="axis-label" x={xs(t)} y={16} textAnchor="middle">
                  {t} m
                </text>
              ))}
            </g>
            {hx != null && (
              <g pointerEvents="none">
                <line x1={hx} x2={hx} y1={0} y2={innerH} stroke="var(--ink-2)" strokeWidth={1} />
                {series.map((s) => (
                  <circle
                    key={s.key}
                    cx={hx}
                    cy={ys(s.values[hover!])}
                    r={4}
                    fill={s.color}
                    stroke="var(--surface)"
                    strokeWidth={2}
                  />
                ))}
              </g>
            )}
            <rect
              ref={overlay}
              width={innerW}
              height={innerH}
              fill="transparent"
              tabIndex={0}
              aria-label="Move along the lap with the arrow keys"
              onPointerMove={(e) => onHover(indexAt(e.clientX))}
              onPointerDown={(e) => onHover(indexAt(e.clientX))}
              onPointerLeave={() => {
                setPointerX(null)
                onHover(null)
              }}
              onKeyDown={onKey}
              onBlur={() => onHover(null)}
            />
          </g>
        </svg>
      )}
      {hover != null && hx != null && pointerX != null && (
        <div className="tooltip" style={{ left: tooltipLeft, top: M.top + 22 }}>
          <div className="tt-head">{Math.round(x[hover])} m into the lap</div>
          {series.map((s) => (
            <div className="tt-row" key={s.key}>
              <i className="key-line" style={{ color: s.color }} />
              <b>{s.format(s.values[hover])}</b>
              <span>{s.label}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function bisectNearest(arr: number[], v: number): number {
  const i = bisect(arr, v)
  if (i < arr.length - 1 && Math.abs(arr[i + 1] - v) < Math.abs(arr[i] - v)) return i + 1
  return i
}
