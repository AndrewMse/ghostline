import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

export type Vec3 = [number, number, number]

export type Gate = { center: Vec3; normal: Vec3; radius: number }

export type Track = {
  id: number
  name: string
  sim: string
  gate: Gate | null
  sessions: number
  laps: number
  best: number | null
}

export type LapMeta = {
  id: number
  session_id: number
  track_id: number
  number: number
  duration: number
  timing: 'native' | 'virtual'
  started_at: string
}

export type TrackSummary = {
  track: Omit<Track, 'sessions' | 'laps' | 'best'>
  laps: (LapMeta & { sectors: number[] })[]
  best_lap: LapMeta | null
  theoretical_best: number | null
  sector_bounds: number[]
  sector_best: { time: number; lap_id: number }[]
  stats: { laps: number; clean_laps: number; mean_clean: number; stdev_clean: number; length: number } | null
}

export type Session = {
  id: number
  track_id: number
  track: string
  sim: string
  started_at: string
  ended_at: string | null
  duration: number
  laps?: number
  best?: number | null
}

export type SessionLap = LapMeta & { run: number; t_start: number; t_end: number; splits: number[] }

export type SessionDetail = Session & { laps: SessionLap[] }

export type SessionPath = { t: number[]; run: number[]; pos: Vec3[] }

export type LapDetail = SessionLap & {
  t: number[]
  pos: Vec3[]
  speed: number[]
  sticks: Record<'throttle' | 'yaw' | 'pitch' | 'roll', number[]> | null
}

export type Insight = {
  kind: 'loss' | 'gain'
  s_start: number
  s_end: number
  s_core: number
  time: number
  min_speed_lap: number
  min_speed_ref: number
  lateral: number
  vertical: number
  text: string
}

export type Comparison = {
  lap: LapMeta
  ref: LapMeta
  length: number
  s: number[]
  delta: number[]
  speed_lap: number[]
  speed_ref: number[]
  lateral: number[]
  vertical: number[]
  t_lap: number[]
  t_ref: number[]
  pos_lap: Vec3[]
  pos_ref: Vec3[]
  sectors: { index: number; start: number; end: number; lap: number; ref: number; delta: number }[]
  insights: Insight[]
  ghost: { lap: { t: number[]; pos: Vec3[] }; ref: { t: number[]; pos: Vec3[] } }
}

export type LiveState = {
  source: { sim: string; connected: boolean; detail: string } | null
  live: {
    session_id: number | null
    track: { id: number | null; name: string }
    t: number
    run: number
    pos: Vec3 | null
    speed: number
    timing: 'native' | 'virtual' | 'searching'
    gate: Gate | null
    lap: { elapsed: number; delta: number | null; predicted: number | null; distance: number | null } | null
    last_lap: { id: number; duration: number; delta: number | null; timing: string } | null
    best: { id: number; duration: number } | null
    lap_seq: number
  } | null
}

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: init?.body ? { 'Content-Type': 'application/json' } : undefined,
  })
  if (!res.ok) {
    let message = res.statusText
    try {
      const body = await res.json()
      if (typeof body.detail === 'string') message = body.detail
    } catch {
      // not JSON; keep the status text
    }
    throw new ApiError(res.status, message)
  }
  return res.status === 204 ? (undefined as T) : res.json()
}

const json = (method: string, body: unknown): RequestInit => ({ method, body: JSON.stringify(body) })

export const useTracks = () => useQuery({ queryKey: ['tracks'], queryFn: () => request<Track[]>('/api/tracks') })

export const useTrack = (id: number) =>
  useQuery({ queryKey: ['track', id], queryFn: () => request<TrackSummary>(`/api/tracks/${id}`) })

export const useSessions = (trackId?: number) =>
  useQuery({
    queryKey: ['sessions', trackId ?? 'all'],
    queryFn: () => request<Session[]>(trackId == null ? '/api/sessions' : `/api/sessions?track_id=${trackId}`),
  })

export const useSession = (id: number | null | undefined, version = 0) =>
  useQuery({
    queryKey: ['session', id, version],
    queryFn: () => request<SessionDetail>(`/api/sessions/${id}`),
    enabled: id != null,
    placeholderData: (prev) => prev,
  })

export const useSessionPath = (id: number | null | undefined) =>
  useQuery({
    queryKey: ['session-path', id],
    queryFn: () => request<SessionPath>(`/api/sessions/${id}/path?hz=10`),
    enabled: id != null,
  })

export const useLap = (id: number | null | undefined) =>
  useQuery({
    queryKey: ['lap', id],
    queryFn: () => request<LapDetail>(`/api/laps/${id}`),
    enabled: id != null,
    staleTime: Infinity,
  })

export const useComparison = (lap: number, ref: number) =>
  useQuery({
    queryKey: ['compare', lap, ref],
    queryFn: () => request<Comparison>(`/api/compare?lap=${lap}&ref=${ref}`),
    placeholderData: (prev) => prev,
  })

function useInvalidateAll() {
  const qc = useQueryClient()
  return () => qc.invalidateQueries()
}

export function useRenameTrack(id: number) {
  const done = useInvalidateAll()
  return useMutation({
    mutationFn: (name: string) => request<Track>(`/api/tracks/${id}`, json('PATCH', { name })),
    onSuccess: done,
  })
}

export function useSetGate(trackId: number) {
  const done = useInvalidateAll()
  return useMutation({
    mutationFn: (at: { session_id: number; t: number }) => request(`/api/tracks/${trackId}/gate`, json('PUT', at)),
    onSuccess: done,
  })
}

export function useDetectGate(trackId: number) {
  const done = useInvalidateAll()
  return useMutation({
    mutationFn: () => request(`/api/tracks/${trackId}/gate/detect`, json('POST', {})),
    onSuccess: done,
  })
}

export function useDeleteSession() {
  const done = useInvalidateAll()
  return useMutation({
    mutationFn: (id: number) => request(`/api/sessions/${id}`, { method: 'DELETE' }),
    onSuccess: done,
  })
}

export function useSetLiveTrack() {
  const done = useInvalidateAll()
  return useMutation({
    mutationFn: (name: string) => request('/api/live/track', json('POST', { name })),
    onSuccess: done,
  })
}
