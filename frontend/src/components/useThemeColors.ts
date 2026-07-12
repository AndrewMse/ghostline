import { useEffect, useState } from 'react'

const NAMES = ['ink', 'ink-2', 'muted', 'hairline', 'axis', 'brand', 'gain', 'loss', 'ghost', 'neutral', 'surface'] as const
export type ThemeColors = Record<(typeof NAMES)[number], string>

function read(): ThemeColors {
  const style = getComputedStyle(document.documentElement)
  return Object.fromEntries(NAMES.map((n) => [n, style.getPropertyValue(`--${n}`).trim()])) as ThemeColors
}

/** CSS colour tokens resolved to values, for canvas/WebGL drawing. Follows light/dark changes. */
export function useThemeColors(): ThemeColors {
  const [colors, setColors] = useState(read)
  useEffect(() => {
    const mq = matchMedia('(prefers-color-scheme: dark)')
    const update = () => setColors(read())
    mq.addEventListener('change', update)
    return () => mq.removeEventListener('change', update)
  }, [])
  return colors
}
