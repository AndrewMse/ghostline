const MINUS = '−'

/** 16.132 → "16.132", 75.4 → "1:15.400" */
export function lapTime(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds)) return '–'
  if (seconds < 60) return seconds.toFixed(3)
  const m = Math.floor(seconds / 60)
  return `${m}:${(seconds - m * 60).toFixed(3).padStart(6, '0')}`
}

/** Signed delta with a true minus sign: "+0.23", "−0.05". */
export function delta(seconds: number | null | undefined, digits = 2): string {
  if (seconds == null || !Number.isFinite(seconds)) return '–'
  const v = Number(seconds.toFixed(digits))
  if (v === 0) return (0).toFixed(digits)
  return `${v > 0 ? '+' : MINUS}${Math.abs(v).toFixed(digits)}`
}

export const kmh = (ms: number) => `${Math.round(ms * 3.6)}`

export function metres(m: number, digits = 0): string {
  return `${m < 0 ? MINUS : ''}${Math.abs(m).toFixed(digits)} m`
}

export function when(iso: string): string {
  const d = new Date(iso)
  return d.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
}

export const SIM_NAMES: Record<string, string> = {
  velocidrone: 'Velocidrone',
  liftoff: 'Liftoff',
  demo: 'Demo pilot',
}

export const simName = (sim: string) => SIM_NAMES[sim] ?? sim
