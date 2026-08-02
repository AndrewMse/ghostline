import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import {
  useDeleteSession,
  useDetectGate,
  useLap,
  useRenameTrack,
  useSessionPath,
  useSessions,
  useSetGate,
  useTrack,
  type TrackSummary,
} from '../api'
import { LapTimesChart } from '../components/LapTimesChart'
import { useLiveState } from '../useLive'
import { TrackMap } from '../components/TrackMap'
import { delta, lapTime, simName, when } from '../format'

export function TrackPage() {
  const id = Number(useParams().id)
  const { data, isLoading, error } = useTrack(id)
  const [selected, setSelected] = useState<number[]>([])
  const navigate = useNavigate()

  if (isLoading) return null
  if (error || !data) return <p className="error">Couldn't load this track: {error?.message ?? 'not found'}</p>

  const best = data.best_lap
  const toggle = (lapId: number) =>
    setSelected((s) => (s.includes(lapId) ? s.filter((x) => x !== lapId) : [...s.slice(-1), lapId]))

  // Compare against the faster of the two picks, or against the best lap.
  const byId = new Map(data.laps.map((l) => [l.id, l]))
  const picks = selected.map((s) => byId.get(s)).filter((l) => l != null)
  let lapId: number | null = null
  let refId: number | null = null
  if (picks.length === 2) {
    const [a, b] = [...picks].sort((x, y) => y.duration - x.duration)
    lapId = a.id
    refId = b.id
  } else if (picks.length === 1 && best && picks[0].id !== best.id) {
    lapId = picks[0].id
    refId = best.id
  }

  return (
    <div className="stack">
      <Head summary={data} />

      {data.stats && best ? (
        <>
          <dl className="panel strip">
            <div>
              <dt>Best lap</dt>
              <dd className="num fastest">{lapTime(best.duration)}</dd>
            </div>
            <div>
              <dt>Best possible</dt>
              <dd className="num">
                {lapTime(data.theoretical_best)}
                <small>{delta((data.theoretical_best ?? 0) - best.duration, 3)}</small>
              </dd>
            </div>
            <div>
              <dt>Typical clean lap</dt>
              <dd className="num">
                {lapTime(data.stats.mean_clean)}
                <small>&plusmn;{data.stats.stdev_clean.toFixed(2)}</small>
              </dd>
            </div>
            <div>
              <dt>Laps</dt>
              <dd className="num">
                {data.stats.laps}
                <small>{data.stats.clean_laps} within 7% of best</small>
              </dd>
            </div>
            <div>
              <dt>Lap length</dt>
              <dd className="num">
                {Math.round(data.stats.length)}
                <small>m</small>
              </dd>
            </div>
          </dl>

          <section className="panel">
            <div className="panel-head">
              <h2>Lap times</h2>
              <p>Best possible adds up your fastest time in each sector.</p>
            </div>
            <div className="panel-body">
              <LapTimesChart laps={data.laps} bestId={best.id} selected={selected} onSelect={toggle} />
            </div>
          </section>

          <section className="panel">
            <div className="panel-head">
              <h2>Timing sheet</h2>
              <div className="row">
                <span className="note">
                  {picks.length === 0
                    ? 'Pick a lap to see where it lost time to your best, or pick two.'
                    : lapId == null
                      ? 'That is your best lap. Pick another to compare with it.'
                      : `Lap ${byId.get(lapId)!.number} against ${refId === best.id ? 'your best' : `lap ${byId.get(refId!)!.number}`}`}
                </span>
                <button
                  className="btn primary"
                  disabled={lapId == null}
                  onClick={() => navigate(`/compare?lap=${lapId}&ref=${refId}`)}
                >
                  Compare laps
                </button>
              </div>
            </div>
            <div className="panel-body table-wrap" style={{ maxHeight: 520, overflowY: 'auto', paddingTop: 8 }}>
              <TimingSheet summary={data} selected={selected} onToggle={toggle} />
            </div>
          </section>
        </>
      ) : (
        <div className="panel empty">
          <h2>No timed laps yet</h2>
          <p>
            {data.track.gate
              ? 'Fly a full lap through the start/finish line and it shows up here.'
              : "Ghostline hasn't found this track's start/finish line yet. Fly a few clean laps, or place it on the map below."}
          </p>
        </div>
      )}

      <div className="compare-grid">
        <StartFinish summary={data} />
        <Sessions trackId={id} />
      </div>
    </div>
  )
}

function Head({ summary }: { summary: TrackSummary }) {
  const [editing, setEditing] = useState(false)
  const [name, setName] = useState(summary.track.name)
  const rename = useRenameTrack(summary.track.id)
  return (
    <div className="page-head" style={{ marginBottom: 0 }}>
      <div>
        <Link className="crumb" to="/tracks">
          All tracks
        </Link>
        {editing ? (
          <form
            className="row"
            onSubmit={(e) => {
              e.preventDefault()
              rename.mutate(name.trim(), { onSuccess: () => setEditing(false) })
            }}
          >
            <label className="visually-hidden" htmlFor="rename">
              Track name
            </label>
            <input id="rename" className="input" value={name} autoFocus maxLength={120} onChange={(e) => setName(e.target.value)} style={{ width: 320 }} />
            <button className="btn primary" disabled={!name.trim()}>
              Rename
            </button>
            <button type="button" className="btn quiet" onClick={() => setEditing(false)}>
              Cancel
            </button>
          </form>
        ) : (
          <div className="row">
            <h1>{summary.track.name}</h1>
            <button className="btn quiet" onClick={() => setEditing(true)}>
              Rename
            </button>
          </div>
        )}
        <p>Flown in {simName(summary.track.sim)}</p>
      </div>
    </div>
  )
}

function TimingSheet({ summary, selected, onToggle }: { summary: TrackSummary; selected: number[]; onToggle: (id: number) => void }) {
  const best = summary.best_lap!
  const sectorBest = summary.sector_best.map((s) => s.time)
  const laps = summary.laps
  return (
    <table className="timing">
      <caption className="visually-hidden">Every lap with its sector times. The fastest time in each column is marked with a diamond.</caption>
      <thead>
        <tr>
          <th>Session</th>
          <th>Lap</th>
          <th>Time</th>
          <th>Gap</th>
          {sectorBest.map((_, i) => (
            <th key={i} title={`${summary.sector_bounds[i]}–${summary.sector_bounds[i + 1]} m`}>
              Sector {i + 1}
            </th>
          ))}
          <th className="left">Timed by</th>
        </tr>
      </thead>
      <tbody>
        {laps.map((l) => {
          const sel = selected.includes(l.id)
          return (
            <tr
              key={l.id}
              className={`pick${sel ? ' selected' : ''}`}
              onClick={() => onToggle(l.id)}
              onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && (e.preventDefault(), onToggle(l.id))}
              tabIndex={0}
              aria-selected={sel}
            >
              <td className="ink-2">{when(l.started_at)}</td>
              <td>{l.number}</td>
              <td className={`lap-time${l.id === best.id ? ' fastest' : ''}`}>{lapTime(l.duration)}</td>
              <td className="ink-2">{l.id === best.id ? '' : delta(l.duration - best.duration, 3)}</td>
              {l.sectors.map((s, i) => (
                <td key={i} className={Math.abs(s - sectorBest[i]) < 5e-4 ? 'fastest' : undefined}>
                  {s.toFixed(3)}
                </td>
              ))}
              <td className="left">
                <span className="tag">{l.timing === 'native' ? 'sim gates' : 'timing line'}</span>
              </td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}

function StartFinish({ summary }: { summary: TrackSummary }) {
  const trackId = summary.track.id
  const sessions = useSessions(trackId)
  const latest = sessions.data?.[0]
  const path = useSessionPath(latest?.id)
  const bestLap = useLap(summary.best_lap?.id)
  const [placing, setPlacing] = useState(false)
  const setGate = useSetGate(trackId)
  const detect = useDetectGate(trackId)
  const { state } = useLiveState()
  const recording = state?.live?.track.id === trackId && state.live.session_id != null
  const err = (setGate.error ?? detect.error) as Error | null

  const layers = placing
    ? path.data
      ? [{ key: 'path', points: path.data.pos, stroke: 'var(--ink-2)', width: 1.5, opacity: 0.8 }]
      : []
    : bestLap.data
      ? [{ key: 'best', points: bestLap.data.pos, stroke: 'var(--ink)', width: 2 }]
      : path.data
        ? [{ key: 'path', points: path.data.pos, stroke: 'var(--ink-2)', width: 1.5, opacity: 0.8 }]
        : []

  return (
    <section className="panel">
      <div className="panel-head">
        <h2>Start/finish line</h2>
        <div className="row">
          <button className="btn" disabled={detect.isPending || !latest} onClick={() => detect.mutate()}>
            Find it for me
          </button>
          <button className="btn" aria-pressed={placing} disabled={!latest} onClick={() => setPlacing((p) => !p)}>
            {placing ? 'Cancel' : 'Place it on the map'}
          </button>
        </div>
      </div>
      <div className="panel-body">
        <p className="note" style={{ marginBottom: 10 }}>
          {placing
            ? 'Click the flight path where you cross the start/finish line. It faces the way you were flying.'
            : summary.track.sim === 'velocidrone'
              ? "In races Velocidrone times laps with its own gates. This line times free flight and practice."
              : 'Laps are timed where you cross this line. Moving it re-times every session on this track.'}
          {recording && !placing && ' Recording now; changes apply to this session too.'}
        </p>
        {layers.length > 0 ? (
          <TrackMap
            label="Top-down map of the start/finish line"
            height={320}
            layers={layers}
            gate={summary.track.gate}
            pickLayer={placing ? 'path' : undefined}
            onPick={(i) => {
              if (!latest || !path.data) return
              setGate.mutate({ session_id: latest.id, t: path.data.t[i] }, { onSuccess: () => setPlacing(false) })
            }}
          />
        ) : (
          <p className="note">No flight path recorded yet.</p>
        )}
        {err && <p className="error" style={{ marginTop: 8 }}>{err.message}</p>}
      </div>
    </section>
  )
}

function Sessions({ trackId }: { trackId: number }) {
  const { data } = useSessions(trackId)
  const del = useDeleteSession()
  const { state } = useLiveState()
  const liveSession = state?.live?.session_id
  return (
    <section className="panel">
      <div className="panel-head">
        <h2>Sessions</h2>
      </div>
      <div className="panel-body table-wrap" style={{ paddingTop: 8 }}>
        <table className="timing">
          <thead>
            <tr>
              <th>Started</th>
              <th>Laps</th>
              <th>Best</th>
              <th>
                <span className="visually-hidden">Actions</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {data?.map((s) => (
              <tr key={s.id}>
                <td>{when(s.started_at)}</td>
                <td>{s.laps}</td>
                <td className="lap-time">{lapTime(s.best)}</td>
                <td>
                  {s.id === liveSession ? (
                    <span className="tag">recording</span>
                  ) : (
                    <button
                      className="btn quiet"
                      onClick={() => {
                        if (confirm(`Delete the session from ${when(s.started_at)} and its ${s.laps} laps?`)) del.mutate(s.id)
                      }}
                    >
                      Delete
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}
