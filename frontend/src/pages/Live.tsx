import { useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { useLap, useSession, useSetLiveTrack, type Vec3 } from '../api'
import { useLiveState } from '../useLive'
import { TrackMap } from '../components/TrackMap'
import { delta, kmh, lapTime, simName } from '../format'
import { positionAt } from '../geometry'

const TRAIL_POINTS = 60 // ~4 s at the 15 Hz live rate

export function Live() {
  const { state, online } = useLiveState()
  const live = state?.live
  const source = state?.source

  if (!online) {
    return (
      <div className="empty">
        <h2>Can't reach the Ghostline server</h2>
        <p>
          Start it with <code>ghostline serve --source velocidrone</code> (or <code>liftoff</code>, or{' '}
          <code>demo</code> to try it without a sim). This page reconnects on its own.
        </p>
      </div>
    )
  }
  if (!source || !live) return <NotRecording />
  if (!source.connected && live.session_id == null) return <Waiting sim={source.sim} detail={source.detail} />
  return <Dashboard />
}

function Dashboard() {
  const { state } = useLiveState()
  const live = state!.live!
  const best = useLap(live.best?.id)
  const session = useSession(live.session_id, live.lap_seq)
  const trail = useTrail(live.pos, live.run)

  const refLength = useMemo(() => {
    const pos = best.data?.pos
    if (!pos) return null
    let len = 0
    for (let i = 1; i < pos.length; i++) len += Math.hypot(...([0, 1, 2].map((k) => pos[i][k] - pos[i - 1][k]) as Vec3))
    return len
  }, [best.data])

  const lap = live.lap
  const d = lap?.delta ?? null
  const ghostPos =
    best.data && lap ? positionAt(best.data.t, best.data.pos, Math.min(lap.elapsed, best.data.t[best.data.t.length - 1])) : null

  const laps = session.data?.laps ?? []

  return (
    <div className="stack">
      <TrackBar />
      <div className="live-grid">
        <section className="panel" aria-label="Current lap">
          <div className="hud">
            <div className={`hud-delta${d == null ? ' idle' : ''}`} aria-live="off">
              {d == null ? '0.00' : delta(d)}
            </div>
            <p className="hud-caption">{caption(live.best?.duration ?? null, d, live.timing, lap != null)}</p>
            <div className="delta-bar" aria-hidden="true">
              {d != null && d < 0 && <span className="ahead" style={{ width: `${Math.min(-d, 1) * 50}%` }} />}
              {d != null && d > 0 && <span className="behind" style={{ width: `${Math.min(d, 1) * 50}%` }} />}
            </div>
            <dl className="strip">
              <div>
                <dt>This lap</dt>
                <dd className="num">{lap ? lap.elapsed.toFixed(1) : '–'}</dd>
              </div>
              <div>
                <dt>On pace for</dt>
                <dd className="num">{lapTime(lap?.predicted)}</dd>
              </div>
              <div>
                <dt>Last lap</dt>
                <dd className="num">
                  {lapTime(live.last_lap?.duration)}
                  {live.last_lap?.delta != null && <small>{delta(live.last_lap.delta)}</small>}
                </dd>
              </div>
              <div>
                <dt>Best</dt>
                <dd className="num">{lapTime(live.best?.duration)}</dd>
              </div>
              <div>
                <dt>Speed</dt>
                <dd className="num">
                  {kmh(live.speed)}
                  <small>km/h</small>
                </dd>
              </div>
            </dl>
            {refLength && lap?.distance != null && (
              <div className="progress" role="progressbar" aria-label="Lap progress" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round((lap.distance / refLength) * 100)}>
                <span style={{ width: `${Math.min(lap.distance / refLength, 1) * 100}%` }} />
              </div>
            )}
          </div>
          <div className="panel-body" style={{ paddingTop: 0 }}>
            <TrackMap
              label="Top-down map: your position and the ghost of your best lap"
              height={380}
              layers={[
                ...(best.data ? [{ key: 'best', points: best.data.pos, stroke: 'var(--ghost)', width: 2 }] : []),
                { key: 'trail', points: trail, stroke: 'var(--ink)', width: 3 },
              ]}
              gate={live.gate}
              markers={[
                ...(ghostPos ? [{ key: 'ghost', pos: ghostPos, fill: 'var(--ghost)' }] : []),
                ...(live.pos ? [{ key: 'you', pos: live.pos, fill: 'var(--ink)', r: 7 }] : []),
              ]}
            />
            <div className="legend" style={{ marginTop: 8 }}>
              <span>
                <i className="key-line" style={{ color: 'var(--ink)' }} /> You
              </span>
              <span>
                <i className="key-line" style={{ color: 'var(--ghost)' }} /> Ghost of your best lap
              </span>
            </div>
          </div>
        </section>

        <section className="panel" aria-label="Laps this session">
          <div className="panel-head">
            <h2>This session</h2>
            {live.track.id != null && (
              <Link className="note" to={`/tracks/${live.track.id}`}>
                Track history
              </Link>
            )}
          </div>
          <div className="panel-body" style={{ padding: '10px 0 6px' }}>
            {laps.length === 0 ? (
              <p className="note" style={{ padding: '0 16px 10px' }}>
                Completed laps show up here.
              </p>
            ) : (
              <ol className="lap-list" reversed>
                {[...laps].reverse().map((l) => (
                  <li key={l.id}>
                    <span className="muted">{l.number}</span>
                    <Link
                      to={live.best ? `/compare?lap=${l.id}&ref=${live.best.id}` : '#'}
                      className={`t${l.id === live.best?.id ? ' fastest' : ''}`}
                      aria-label={l.id === live.best?.id ? `${lapTime(l.duration)}, your best lap` : undefined}
                      style={{ textDecoration: 'none' }}
                    >
                      {lapTime(l.duration)}
                    </Link>
                    <span className="ink-2 num">{live.best && l.id !== live.best.id ? delta(l.duration - live.best.duration) : ''}</span>
                  </li>
                ))}
              </ol>
            )}
          </div>
        </section>
      </div>
    </div>
  )
}

function caption(best: number | null, d: number | null, timing: string, inLap: boolean): string {
  if (timing === 'searching') return 'Finding the start/finish line. Fly a few clean laps.'
  if (!inLap) return 'Cross the start/finish line to start a lap.'
  if (best == null) return 'Finish a lap to set a ghost to race.'
  if (d == null) return `Racing your best, ${lapTime(best)}`
  if (Math.abs(d) < 0.005) return `Level with your best, ${lapTime(best)}`
  return `${d < 0 ? 'Ahead of' : 'Behind'} your best, ${lapTime(best)}`
}

function TrackBar() {
  const { state } = useLiveState()
  const live = state!.live!
  const [editing, setEditing] = useState(false)
  const [name, setName] = useState(live.track.name)
  const setTrack = useSetLiveTrack()

  const timing = {
    native: `Laps timed by ${simName(state!.source!.sim)}'s gates`,
    virtual: 'Laps timed at the start/finish line',
    searching: 'Looking for the start/finish line',
  }[live.timing]

  return (
    <div className="page-head" style={{ marginBottom: 0 }}>
      <div>
        {editing ? (
          <form
            className="row"
            onSubmit={(e) => {
              e.preventDefault()
              setTrack.mutate(name.trim(), { onSuccess: () => setEditing(false) })
            }}
          >
            <label className="visually-hidden" htmlFor="track-name">
              Track name
            </label>
            <input
              id="track-name"
              className="input"
              value={name}
              autoFocus
              maxLength={120}
              onChange={(e) => setName(e.target.value)}
              style={{ width: 320 }}
            />
            <button className="btn primary" disabled={!name.trim() || setTrack.isPending}>
              Save track
            </button>
            <button type="button" className="btn quiet" onClick={() => setEditing(false)}>
              Cancel
            </button>
          </form>
        ) : (
          <div className="row">
            <h1>{live.track.name}</h1>
            <button
              className="btn quiet"
              onClick={() => {
                setName(live.track.name)
                setEditing(true)
              }}
            >
              Change track
            </button>
          </div>
        )}
        <p>{timing}</p>
      </div>
    </div>
  )
}

/** The last few seconds of the live position; cleared when the drone is reset. */
function useTrail(pos: Vec3 | null, run: number): Vec3[] {
  const ref = useRef<{ run: number; pts: Vec3[] }>({ run, pts: [] })
  const [trail, setTrail] = useState<Vec3[]>([])
  useEffect(() => {
    if (!pos) return
    const r = ref.current
    if (r.run !== run) {
      r.run = run
      r.pts = []
    }
    r.pts = [...r.pts.slice(-(TRAIL_POINTS - 1)), pos]
    setTrail(r.pts)
  }, [pos, run])
  return trail
}

function NotRecording() {
  return (
    <div className="panel setup" style={{ maxWidth: 760 }}>
      <div className="panel-body">
        <h1 style={{ marginBottom: 10 }}>Not recording</h1>
        <p className="ink-2">
          The server is running without a sim. Restart it with the sim you fly, then fly a few laps. Your{' '}
          <Link to="/tracks">tracks</Link> are still here.
        </p>
        <SetupSteps />
      </div>
    </div>
  )
}

function Waiting({ sim, detail }: { sim: string; detail: string }) {
  return (
    <div className="panel setup" style={{ maxWidth: 760 }}>
      <div className="panel-body">
        <h1 style={{ marginBottom: 10 }}>Waiting for {simName(sim)}</h1>
        <p className="ink-2">{detail}</p>
        <SetupSteps only={sim} />
      </div>
    </div>
  )
}

function SetupSteps({ only }: { only?: string }) {
  return (
    <div className="stack" style={{ marginTop: 18 }}>
      {(!only || only === 'velocidrone') && (
        <div>
          <h3>Velocidrone</h3>
          <ol>
            <li>
              In Options, Main Settings, turn on <b>Websocket Communication</b> and <b>Websocket IMU</b>. The IMU
              feed needs the Betaflight flight controller model.
            </li>
            <li>
              Run <code>ghostline serve --source velocidrone</code> on the same PC. If the sim runs on another PC, add{' '}
              <code>--vd-host</code> with that PC's LAN address.
            </li>
            <li>
              In multiplayer, add <code>--vd-pilot</code> with your pilot name so the right laps are yours.
            </li>
          </ol>
        </div>
      )}
      {(!only || only === 'liftoff') && (
        <div>
          <h3>Liftoff</h3>
          <ol>
            <li>
              Run <code>ghostline liftoff-config --write</code> to create Liftoff's telemetry settings file.
            </li>
            <li>
              Run <code>ghostline serve --source liftoff</code>, then reset your drone in Liftoff so it picks up the
              settings.
            </li>
          </ol>
        </div>
      )}
      {!only && (
        <p className="note">
          No sim at hand? <code>ghostline serve --source demo</code> flies a synthetic pilot around a demo track.
        </p>
      )}
    </div>
  )
}
