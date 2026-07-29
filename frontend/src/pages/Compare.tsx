import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useComparison, type Comparison, type Insight } from '../api'
import { DistanceChart, type Series } from '../components/DistanceChart'
import { Flight3D } from '../components/Flight3D'
import { delta, kmh, lapTime, metres, when } from '../format'
import { bisect, positionAt } from '../geometry'

export function Compare() {
  const [params] = useSearchParams()
  const lap = Number(params.get('lap'))
  const ref = Number(params.get('ref'))
  const { data, error, isLoading, isPlaceholderData } = useComparison(lap, ref)

  if (isLoading) return null
  if (error || !data) return <p className="error">Couldn't compare these laps: {error?.message ?? 'not found'}</p>
  return (
    <div style={{ opacity: isPlaceholderData ? 0.6 : 1 }}>
      <CompareView c={data} />
    </div>
  )
}

function CompareView({ c }: { c: Comparison }) {
  const [hover, setHover] = useState<number | null>(null)
  const [focus, setFocus] = useState<Insight | null>(null)
  const [showTable, setShowTable] = useState(false)
  const replay = useReplay(Math.max(c.lap.duration, c.ref.duration))
  const narrow = useMediaQuery('(max-width: 640px)')

  const total = c.lap.duration - c.ref.duration
  const slope = useMemo(() => smoothSlope(c.s, c.delta, 8), [c])
  const idx = (s: number) => Math.min(bisect(c.s, s), c.s.length - 1)
  const highlight: [number, number] | null = focus ? [focus.s_start, focus.s_end] : null

  // While replaying, the charts follow your drone.
  const replayIdx = replay.active ? Math.min(bisect(c.t_lap, replay.t), c.s.length - 1) : null
  const active = replayIdx ?? hover

  const you = replay.active
    ? positionAt(c.ghost.lap.t, c.ghost.lap.pos, replay.t)
    : active != null
      ? c.pos_lap[active]
      : null
  const ghost = replay.active
    ? positionAt(c.ghost.ref.t, c.ghost.ref.pos, replay.t)
    : active != null
      ? c.pos_ref[active]
      : null

  const deltaSeries: Series[] = [
    { key: 'delta', label: 'behind (+) or ahead (−) of the ghost', values: c.delta, color: 'var(--ink)', format: (v) => `${delta(v)} s` },
  ]
  const speedSeries: Series[] = [
    { key: 'you', label: 'you', values: c.speed_lap.map((v) => v * 3.6), color: 'var(--ink)', format: (v) => `${Math.round(v)} km/h` },
    { key: 'ghost', label: 'ghost', values: c.speed_ref.map((v) => v * 3.6), color: 'var(--ghost)', format: (v) => `${Math.round(v)} km/h` },
  ]
  const lateralSeries: Series[] = [
    { key: 'lat', label: 'right (+) or left (−) of the ghost', values: c.lateral, color: 'var(--ink)', format: (v) => metres(v, 1) },
  ]
  const verticalSeries: Series[] = [
    { key: 'vert', label: 'above (+) or below (−) the ghost', values: c.vertical, color: 'var(--ink)', format: (v) => metres(v, 1) },
  ]
  const common = {
    x: c.s,
    hover: active,
    onHover: (i: number | null) => !replay.active && setHover(i),
    sectors: [c.sectors[0]?.start ?? 0, ...c.sectors.map((s) => s.end)],
    highlight,
  }

  return (
    <div className="stack">
      <div className="page-head" style={{ marginBottom: 0 }}>
        <div>
          <Link className="crumb" to={`/tracks/${c.lap.track_id}`}>
            Back to the track
          </Link>
          <h1>
            {Math.abs(total) < 0.0005
              ? `Lap ${c.lap.number} matched the ghost`
              : `Where lap ${c.lap.number} ${total > 0 ? 'lost' : 'gained'} ${Math.abs(total).toFixed(3)} s`}
          </h1>
          <p>
            Lap {c.lap.number} from {when(c.lap.started_at)}, {lapTime(c.lap.duration)}, against the ghost of lap{' '}
            {c.ref.number} from {when(c.ref.started_at)}, {lapTime(c.ref.duration)}.
          </p>
        </div>
      </div>

      <div className="compare-grid">
        <section className="panel" aria-label="3D replay">
          <div className="viewport">
            <Flight3D
              lapPath={c.pos_lap}
              ghostPath={c.ghost.ref.pos}
              slope={slope}
              you={you}
              ghost={ghost}
              highlight={highlight ? [idx(highlight[0]), idx(highlight[1])] : null}
              height={narrow ? 340 : 460}
            />
          </div>
          <div className="replay">
            <button className="btn" onClick={replay.toggle} aria-label={replay.playing ? 'Pause replay' : 'Play replay'}>
              {replay.playing ? 'Pause' : replay.t > 0 && replay.t < replay.end ? 'Resume' : 'Replay'}
            </button>
            <input
              type="range"
              min={0}
              max={replay.end}
              step={0.01}
              value={replay.t}
              aria-label="Replay time"
              onChange={(e) => replay.seek(Number(e.target.value))}
            />
            <span className="num" style={{ minWidth: 56, textAlign: 'right' }}>
              {replay.t.toFixed(2)} s
            </span>
            <select className="input" value={replay.speed} aria-label="Replay speed" onChange={(e) => replay.setSpeed(Number(e.target.value))}>
              <option value={0.25}>0.25×</option>
              <option value={0.5}>0.5×</option>
              <option value={1}>1×</option>
              <option value={2}>2×</option>
            </select>
            {replay.active && (
              <button className="btn quiet" onClick={replay.stop}>
                Stop
              </button>
            )}
          </div>
          <div className="replay legend" style={{ justifyContent: 'space-between' }}>
            <span>
              <i className="key-ramp" /> Your line, blue where you gained, red where you lost
            </span>
            <span>
              <i className="key-line" style={{ color: 'var(--ghost)' }} /> Ghost
            </span>
            <span>
              <i className="key-line" style={{ color: 'var(--brand)' }} /> Start/finish
            </span>
          </div>
        </section>

        <div className="stack">
          <section className="panel" aria-label="Coaching notes">
            <div className="panel-head">
              <h2>Where the time went</h2>
            </div>
            <div className="panel-body" style={{ padding: '8px 0 4px' }}>
              {c.insights.length === 0 ? (
                <p className="note" style={{ padding: '4px 16px 12px' }}>
                  No single stretch stands out: the difference is spread thinly over the lap.
                </p>
              ) : (
                <ul className="insights">
                  {c.insights.map((ins) => (
                    <li key={`${ins.kind}${ins.s_start}`}>
                      <button
                        aria-pressed={focus === ins}
                        onClick={() => {
                          setFocus(focus === ins ? null : ins)
                          replay.stop()
                          setHover(focus === ins ? null : idx(ins.s_core))
                        }}
                      >
                        <span className="insight-time">
                          {delta(ins.time)}
                          <small>{ins.kind === 'loss' ? 'lost' : 'gained'}</small>
                        </span>
                        <span>{ins.text}</span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </section>

          <section className="panel" aria-label="Sectors">
            <div className="panel-head">
              <h2>Sectors</h2>
            </div>
            <div className="panel-body table-wrap" style={{ paddingTop: 6 }}>
              <SectorTable c={c} />
            </div>
          </section>
        </div>
      </div>

      <section className="panel">
        <div className="panel-head">
          <h2>Along the lap</h2>
          <button className="btn quiet" onClick={() => setShowTable((v) => !v)} aria-expanded={showTable}>
            {showTable ? 'Hide the numbers' : 'Show as a table'}
          </button>
        </div>
        <div className="panel-body stack" style={{ gap: 22 }}>
          <DistanceChart
            {...common}
            title="Time to the ghost"
            aside={<span className="ink-2">above the line you're behind, below it you're ahead</span>}
            series={deltaSeries}
            yFormat={(v) => `${delta(v, 1)} s`}
            diverging
          />
          <DistanceChart
            {...common}
            title="Speed, km/h"
            aside={
              <span className="legend">
                <span>
                  <i className="key-line" style={{ color: 'var(--ink)' }} /> You
                </span>
                <span>
                  <i className="key-line" style={{ color: 'var(--ghost)' }} /> Ghost
                </span>
              </span>
            }
            series={speedSeries}
            yFormat={(v) => `${Math.round(v)}`}
            height={170}
          />
          <DistanceChart
            {...common}
            title="Sideways from the ghost's line"
            aside={<span className="ink-2">metres, + is right</span>}
            series={lateralSeries}
            yFormat={(v) => `${Math.round(v)}`}
            zeroLine
            symmetric
            height={120}
          />
          <DistanceChart
            {...common}
            title="Height against the ghost"
            aside={<span className="ink-2">metres, + is higher</span>}
            series={verticalSeries}
            yFormat={(v) => `${Math.round(v)}`}
            zeroLine
            symmetric
            height={120}
          />
          {showTable && <AlongTable c={c} />}
        </div>
      </section>
    </div>
  )
}

function SectorTable({ c }: { c: Comparison }) {
  const maxAbs = Math.max(...c.sectors.map((s) => Math.abs(s.delta)), 0.05)
  return (
    <table className="timing">
      <thead>
        <tr>
          <th>Sector</th>
          <th>You</th>
          <th>Ghost</th>
          <th>Difference</th>
        </tr>
      </thead>
      <tbody>
        {c.sectors.map((s) => {
          const w = Math.max((Math.abs(s.delta) / maxAbs) * 28, 1)
          return (
            <tr key={s.index}>
              <td>
                {s.index}{' '}
                <span className="muted" style={{ fontSize: 'var(--fs-xs)' }}>
                  {Math.round(s.start)}–{Math.round(s.end)} m
                </span>
              </td>
              <td>{s.lap.toFixed(3)}</td>
              <td className="ink-2">{s.ref.toFixed(3)}</td>
              <td>
                {/* A small diverging bar beside the number: left/blue gained, right/red lost. */}
                <span aria-hidden="true" style={{ display: 'inline-block', position: 'relative', width: 58, height: 8, marginRight: 8 }}>
                  <span style={{ position: 'absolute', left: 29, top: -2, bottom: -2, width: 1, background: 'var(--axis)' }} />
                  <span
                    className="mini-bar"
                    style={{
                      position: 'absolute',
                      width: w,
                      left: s.delta > 0 ? 30 : 29 - w,
                      background: s.delta > 0 ? 'var(--loss)' : 'var(--gain)',
                    }}
                  />
                </span>
                {delta(s.delta, 3)}
              </td>
            </tr>
          )
        })}
        <tr>
          <td>
            <b>Lap</b>
          </td>
          <td>
            <b>{c.lap.duration.toFixed(3)}</b>
          </td>
          <td className="ink-2">{c.ref.duration.toFixed(3)}</td>
          <td>
            <b>{delta(c.lap.duration - c.ref.duration, 3)}</b>
          </td>
        </tr>
      </tbody>
    </table>
  )
}

function AlongTable({ c }: { c: Comparison }) {
  const every = Math.max(Math.round(10 / (c.s[1] - c.s[0] || 1)), 1)
  const rows = c.s.map((_, i) => i).filter((i) => i % every === 0 || i === c.s.length - 1)
  return (
    <div className="table-wrap" style={{ maxHeight: 360, overflowY: 'auto' }}>
      <table className="timing">
        <caption className="visually-hidden">Every 10 metres along the lap</caption>
        <thead>
          <tr>
            <th>Distance</th>
            <th>Time to ghost</th>
            <th>Your speed</th>
            <th>Ghost speed</th>
            <th>Sideways</th>
            <th>Height</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((i) => (
            <tr key={i}>
              <td>{Math.round(c.s[i])} m</td>
              <td>{delta(c.delta[i])} s</td>
              <td>{kmh(c.speed_lap[i])} km/h</td>
              <td>{kmh(c.speed_ref[i])} km/h</td>
              <td>{metres(c.lateral[i], 1)}</td>
              <td>{metres(c.vertical[i], 1)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/** Rate of time loss per metre, smoothed over `window` metres: what the 3D line is coloured by. */
function smoothSlope(s: number[], d: number[], window: number): number[] {
  const n = s.length
  const step = n > 1 ? s[1] - s[0] : 1
  const k = Math.max(Math.round(window / step / 2), 1)
  const out = new Array<number>(n)
  for (let i = 0; i < n; i++) {
    const a = Math.max(i - k, 0)
    const b = Math.min(i + k, n - 1)
    out[i] = (d[b] - d[a]) / Math.max(s[b] - s[a], 1e-6)
  }
  return out
}

function useMediaQuery(query: string): boolean {
  const [match, setMatch] = useState(() => matchMedia(query).matches)
  useEffect(() => {
    const mq = matchMedia(query)
    const update = () => setMatch(mq.matches)
    mq.addEventListener('change', update)
    return () => mq.removeEventListener('change', update)
  }, [query])
  return match
}

function useReplay(end: number) {
  const [t, setT] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [active, setActive] = useState(false)
  const [speed, setSpeed] = useState(1)
  const last = useRef<number | null>(null)

  useEffect(() => {
    if (!playing) return
    let raf = 0
    const tick = (now: number) => {
      const dt = last.current == null ? 0 : (now - last.current) / 1000
      last.current = now
      setT((cur) => {
        const next = cur + dt * speed
        if (next >= end) {
          setPlaying(false)
          return end
        }
        return next
      })
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => {
      cancelAnimationFrame(raf)
      last.current = null
    }
  }, [playing, speed, end])

  return {
    t,
    end,
    playing,
    active,
    speed,
    setSpeed,
    toggle: () => {
      setActive(true)
      if (!playing && t >= end) setT(0)
      setPlaying((p) => !p)
    },
    seek: (v: number) => {
      setActive(true)
      setT(v)
    },
    stop: () => {
      setPlaying(false)
      setActive(false)
      setT(0)
    },
  }
}
