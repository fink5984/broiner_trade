import { createContext, useCallback, useEffect, useState } from 'react'
import { api, type Status } from './api'

export function useApi<T>(path: string | null, pollMs = 0) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const load = useCallback(async () => {
    if (!path) return
    try {
      setData(await api<T>(path))
      setError(null)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setLoading(false)
    }
  }, [path])
  useEffect(() => {
    setLoading(true)
    load()
    if (!pollMs) return
    const t = setInterval(load, pollMs)
    return () => clearInterval(t)
  }, [load, pollMs])
  return { data, error, loading, reload: load }
}

export interface LiveQuote { bid: number; ask: number; mid: number; spread: number; ts: string; epoch: number; age_s: number }

/** Subscribes to the server's SSE quote stream (pushed every second). EventSource reconnects automatically. */
export function useLiveQuotes() {
  const [quotes, setQuotes] = useState<Record<string, LiveQuote>>({})
  const [connected, setConnected] = useState(false)
  const [lastMsg, setLastMsg] = useState(0)
  useEffect(() => {
    const es = new EventSource('/api/stream/quotes')
    es.onopen = () => setConnected(true)
    es.onerror = () => setConnected(false)
    es.onmessage = e => {
      try {
        const j = JSON.parse(e.data) as { quotes: Record<string, LiveQuote> }
        setQuotes(j.quotes); setLastMsg(Date.now()); setConnected(true)
      } catch { /* ignore malformed frame */ }
    }
    return () => es.close()
  }, [])
  return { quotes, connected, lastMsg }
}

/** Re-render every `ms` (for "updated N seconds ago" labels). */
export function useTick(ms = 1000) {
  const [, set] = useState(0)
  useEffect(() => { const t = setInterval(() => set(x => x + 1), ms); return () => clearInterval(t) }, [ms])
}

export const StatusCtx = createContext<{ status: Status | null; error: string | null }>({ status: null, error: null })
