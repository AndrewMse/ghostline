import { Link, useNavigate } from 'react-router-dom'
import { useTracks } from '../api'
import { lapTime, simName } from '../format'

export function Tracks() {
  const { data, isLoading, error } = useTracks()
  const navigate = useNavigate()

  if (isLoading) return null
  if (error) return <p className="error">Couldn't load tracks: {error.message}</p>

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Tracks</h1>
          <p>Every track you've flown, with your best lap on each.</p>
        </div>
      </div>
      {!data?.length ? (
        <div className="panel empty">
          <h2>No laps yet</h2>
          <p>
            Fly with <Link to="/">Live</Link> open and your sessions land here. To look around first, run{' '}
            <code>ghostline seed-demo</code> for three sessions of a synthetic pilot.
          </p>
        </div>
      ) : (
        <div className="panel table-wrap">
          <table className="timing">
            <thead>
              <tr>
                <th>Track</th>
                <th className="left">Sim</th>
                <th>Sessions</th>
                <th>Laps</th>
                <th>Best lap</th>
              </tr>
            </thead>
            <tbody>
              {data.map((t) => (
                <tr key={t.id} className="pick" onClick={() => navigate(`/tracks/${t.id}`)}>
                  <td>
                    <Link to={`/tracks/${t.id}`} style={{ fontWeight: 600, textDecoration: 'none' }}>
                      {t.name}
                    </Link>
                  </td>
                  <td className="left">{simName(t.sim)}</td>
                  <td>{t.sessions}</td>
                  <td>{t.laps}</td>
                  <td className="lap-time">{lapTime(t.best)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  )
}
