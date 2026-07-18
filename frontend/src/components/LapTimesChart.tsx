import { scaleLinear } from 'd3-scale'
import { useState } from 'react'
import type { TrackSummary } from '../api'
import { delta, lapTime, when } from '../format'
import { useWidth } from './useWidth'

type Lap = TrackSummary['laps'][number]
const M = { top: 14, right: 16, bottom: 24, left: 52 }

/**
 * Every lap in order, one dot each, sessions separated by hairlines.
 * Very slow laps (crashes, cut-short runs) are pinned to the top edge rather
 * than squashing the scale.
 */
export function LapTimesChart({ laps, bestId, selected, onSelect }: {
  laps: Lap[]
  bestId: number | null
  selected: number[]
  onSelect: (id: number) => void
}) {
  const [ref, width] = useWidth<HTMLDivElement>()
  const [hover, setHover] = useState<number | null>(null)
  const height = 200
  const innerW = Math.max(width - M.left - M.right, 10)
  const innerH = height - M.top - M.bottom
  if (!laps.length) return null

  const best = Math.min(...laps.map((l) => l.duration))
  const cap = best * 1.12
  const top = Math.min(Math.max(...laps.map((l) => l.duration)), cap)
  const xs = scaleLinear().domain([0, Math.max(laps.length - 1, 1)]).range([8, innerW - 8])
  const ys = scaleLinear().domain([best * 0.995, top * 1.005]).range([innerH, 0]).nice(4)
  const breaks = laps.map((l, i) => (i > 0 && l.session_id !== laps[i - 1].session_id ? i : -1)).filter((i) => i > 0)
  const h = hover != null ? laps[hover] : null

  return (
    <div className="chart" ref={ref}>
      {width > 0 && (
        <svg width={width} height={height} role="img" aria-label="Lap times in the order they were flown">
          <g transform={`translate(${M.left},${M.top})`}>
            {ys.ticks(4).map((t) => (
              <g key={t} transform={`translate(0,${ys(t)})`}>
                <line className="gridline" x2={innerW} />
                <text className="axis-label" x={-8} dy="0.32em" textAnchor="end">
                  {t.toFixed(1)}
                </text>
              </g>
            ))}
            {breaks.map((i) => (
              <line key={i} className="baseline" x1={(xs(i) + xs(i - 1)) / 2} x2={(xs(i) + xs(i - 1)) / 2} y1={0} y2={innerH} />
            ))}
            <line className="baseline" y1={innerH} y2={innerH} x2={innerW} />
            <text className="axis-label" x={0} y={innerH + 17}>
              First lap
            </text>
            <text className="axis-label" x={innerW} y={innerH + 17} textAnchor="end">
              Latest
            </text>
            {laps.map((l, i) => {
              const isBest = l.id === bestId
              const sel = selected.includes(l.id)
              const clipped = l.duration > cap
              return (
                <g
                  key={l.id}
                  transform={`translate(${xs(i)},${clipped ? 0 : ys(l.duration)})`}
                  onPointerEnter={() => setHover(i)}
                  onPointerLeave={() => setHover(null)}
                  onClick={() => onSelect(l.id)}
                  style={{ cursor: 'pointer' }}
                >
                  <circle r={12} fill="transparent" />
                  {clipped ? (
                    <path d="M-4,4 L0,-2 L4,4 Z" fill="var(--muted)" />
                  ) : (
                    <circle
                      r={isBest || sel || hover === i ? 5.5 : 4}
                      fill={isBest ? 'var(--brand)' : sel ? 'var(--ink)' : 'var(--ink-2)'}
                      stroke="var(--surface)"
                      strokeWidth={2}
                    />
                  )}
                  {isBest && (
                    <text className="axis-label" y={-10} textAnchor="middle" style={{ fill: 'var(--brand)', fontWeight: 600 }}>
                      &#9670; {lapTime(l.duration)}
                    </text>
                  )}
                </g>
              )
            })}
          </g>
        </svg>
      )}
      {h && hover != null && (
        <div
          className="tooltip"
          style={{ left: Math.min(M.left + xs(hover) + 12, width - 180), top: 8 }}
        >
          <div className="tt-head">
            Lap {h.number}, {when(h.started_at)}
          </div>
          <div className="tt-row">
            <b>{lapTime(h.duration)}</b>
            <span>{h.id === bestId ? 'your best' : `${delta(h.duration - best, 3)} to best`}</span>
          </div>
        </div>
      )}
    </div>
  )
}
