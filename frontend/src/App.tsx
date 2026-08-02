import { NavLink, Route, Routes } from 'react-router-dom'
import { simName } from './format'
import { Compare } from './pages/Compare'
import { Live } from './pages/Live'
import { TrackPage } from './pages/Track'
import { Tracks } from './pages/Tracks'
import { LiveContext, useLive, useLiveState } from './useLive'

export function App() {
  const live = useLive()
  return (
    <LiveContext.Provider value={live}>
      <header className="topbar">
        <div className="topbar-inner">
          <NavLink to="/" className="wordmark" aria-label="Ghostline home">
            <img src="/favicon.svg" width={26} height={26} alt="" />
            <span>Ghostline</span>
          </NavLink>
          <nav className="nav" aria-label="Main">
            <NavLink to="/" end>
              Live
            </NavLink>
            <NavLink to="/tracks">Tracks</NavLink>
          </nav>
          <SourceStatus />
        </div>
      </header>
      <main>
        <Routes>
          <Route path="/" element={<Live />} />
          <Route path="/tracks" element={<Tracks />} />
          <Route path="/tracks/:id" element={<TrackPage />} />
          <Route path="/compare" element={<Compare />} />
          <Route path="*" element={<p className="empty">There's nothing at this address.</p>} />
        </Routes>
      </main>
    </LiveContext.Provider>
  )
}

function SourceStatus() {
  const { state, online } = useLiveState()
  if (!online) {
    return (
      <div className="source" role="status">
        <i className="dot" /> Server offline
      </div>
    )
  }
  const src = state?.source
  if (!src) {
    return (
      <div className="source" role="status">
        <i className="dot" /> Not recording
      </div>
    )
  }
  return (
    <div className="source" role="status" title={src.detail}>
      <i className={`dot ${src.connected ? 'on' : 'wait'}`} />
      {simName(src.sim)}
      <span className="source-detail">{src.connected ? 'connected' : 'waiting for the sim'}</span>
    </div>
  )
}
