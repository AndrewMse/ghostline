import { createContext, useContext, useEffect, useState } from 'react'
import type { LiveState } from './api'

/** The recorder's live state, pushed ~15 times a second. Reconnects on its own. */
export function useLive(): { state: LiveState | null; online: boolean } {
  const [state, setState] = useState<LiveState | null>(null)
  const [online, setOnline] = useState(false)

  useEffect(() => {
    let ws: WebSocket | null = null
    let retry: ReturnType<typeof setTimeout> | undefined
    let closed = false

    const connect = () => {
      const proto = location.protocol === 'https:' ? 'wss' : 'ws'
      ws = new WebSocket(`${proto}://${location.host}/api/live`)
      ws.onopen = () => setOnline(true)
      ws.onmessage = (e) => setState(JSON.parse(e.data))
      ws.onclose = () => {
        setOnline(false)
        if (!closed) retry = setTimeout(connect, 1500)
      }
    }
    connect()
    return () => {
      closed = true
      clearTimeout(retry)
      ws?.close()
    }
  }, [])

  return { state, online }
}

export const LiveContext = createContext<{ state: LiveState | null; online: boolean }>({ state: null, online: false })

/** The live state shared by the whole app (one WebSocket, opened in App). */
export const useLiveState = () => useContext(LiveContext)
