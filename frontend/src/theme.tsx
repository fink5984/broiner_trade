import { createContext, useContext, useState, type ReactNode } from 'react'

const Ctx = createContext<{ dark: boolean; toggle: () => void }>({ dark: true, toggle: () => {} })

function apply(dark: boolean) {
  document.documentElement.classList.toggle('dark', dark)
  try { localStorage.setItem('theme', dark ? 'dark' : 'light') } catch { /* storage unavailable */ }
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  // Class is applied synchronously so charts created in child effects read the right tokens.
  const [dark, setDark] = useState(() => {
    let d = true
    try { d = localStorage.getItem('theme') !== 'light' } catch { /* default dark */ }
    apply(d)
    return d
  })
  const toggle = () => setDark(v => { apply(!v); return !v })
  return <Ctx.Provider value={{ dark, toggle }}>{children}</Ctx.Provider>
}

export const useTheme = () => useContext(Ctx)

/** Resolve a design token (e.g. 'accent') to a CSS color string for canvas-based charts. */
export function rgb(name: string, alpha = 1): string {
  const v = getComputedStyle(document.documentElement).getPropertyValue('--c-' + name).trim().split(/\s+/).join(', ')
  return alpha === 1 ? `rgb(${v})` : `rgba(${v}, ${alpha})`
}
