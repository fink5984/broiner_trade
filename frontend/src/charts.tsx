import { useEffect, useRef } from 'react'
import { AreaSeries, CandlestickSeries, ColorType, LineSeries, LineStyle, createChart, type ChartOptions, type DeepPartial, type ISeriesApi, type UTCTimestamp } from 'lightweight-charts'
import type { Candle, Point } from './api'
import { rgb, useTheme } from './theme'

function baseOptions(): DeepPartial<ChartOptions> {
  const grid = rgb('border', 0.55)
  return {
    autoSize: true,
    layout: { background: { type: ColorType.Solid, color: 'transparent' }, textColor: rgb('muted'), fontFamily: 'JetBrains Mono, monospace', fontSize: 11 },
    grid: { vertLines: { color: grid }, horzLines: { color: grid } },
    rightPriceScale: { borderColor: rgb('border') },
    timeScale: { borderColor: rgb('border'), timeVisible: true, secondsVisible: false },
    crosshair: {
      vertLine: { color: rgb('muted', 0.45), labelBackgroundColor: rgb('surface2') },
      horzLine: { color: rgb('muted', 0.45), labelBackgroundColor: rgb('surface2') },
    },
  }
}

export interface Overlay { data: Point[]; tone: string }
export interface Level { price: number; kind: string }

/** `live`: latest BID price + epoch seconds. It updates the forming candle (or opens the next one)
 *  without rebuilding the chart. Buckets are aligned to the last closed candle, so broker session
 *  offsets (e.g. D1 opening at 21:00 UTC) are respected. */
export function PriceChart({ candles, lines, levels, height = 420, live, tfSeconds }: {
  candles: Candle[]; lines: Overlay[]; levels?: Level[]; height?: number; live?: { price: number; epoch: number } | null; tfSeconds?: number
}) {
  const ref = useRef<HTMLDivElement>(null)
  const seriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null)
  const lastRef = useRef<Candle | null>(null)
  const { dark } = useTheme()

  useEffect(() => {
    const s = seriesRef.current, last = lastRef.current
    if (!s || !last || !live || !tfSeconds) return
    const steps = Math.floor((live.epoch - last.time) / tfSeconds)
    if (steps < 0) return
    const t = last.time + steps * tfSeconds
    const p = live.price
    const c: Candle = t === last.time
      ? { ...last, high: Math.max(last.high, p), low: Math.min(last.low, p), close: p }
      : { time: t, open: last.close, high: Math.max(last.close, p), low: Math.min(last.close, p), close: p }
    s.update({ ...c, time: c.time as UTCTimestamp })
    lastRef.current = c
  }, [live, tfSeconds])

  useEffect(() => {
    if (!ref.current) return
    const chart = createChart(ref.current, baseOptions())
    const up = rgb('profit'), down = rgb('loss')
    const s = chart.addSeries(CandlestickSeries, { upColor: up, downColor: down, wickUpColor: up, wickDownColor: down, borderVisible: false })
    s.setData(candles.map(c => ({ ...c, time: c.time as UTCTimestamp })))
    seriesRef.current = s
    lastRef.current = candles.length ? candles[candles.length - 1] : null
    for (const l of lines) {
      chart.addSeries(LineSeries, { color: rgb(l.tone), lineWidth: 2, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false })
        .setData(l.data.map(p => ({ ...p, time: p.time as UTCTimestamp })))
    }
    for (const lv of levels ?? []) {
      const support = lv.kind === 'support'
      s.createPriceLine({ price: lv.price, color: rgb(support ? 'profit' : 'loss', 0.65), lineStyle: LineStyle.Dashed, lineWidth: 1, axisLabelVisible: false, title: support ? 'S' : 'R' })
    }
    chart.timeScale().fitContent()
    return () => { seriesRef.current = null; chart.remove() }
  }, [candles, lines, levels, dark])
  return <div ref={ref} dir="ltr" style={{ height }} />
}

export function EquityChart({ data, base, height = 280, live }: { data: Point[]; base: number; height?: number; live?: Point | null }) {
  const ref = useRef<HTMLDivElement>(null)
  const { dark } = useTheme()
  const seriesRef = useRef<ISeriesApi<'Area'> | null>(null)
  const lastTime = useRef(0)
  useEffect(() => {
    if (!ref.current) return
    const chart = createChart(ref.current, { ...baseOptions(), grid: { vertLines: { visible: false }, horzLines: { color: rgb('border', 0.55) } } })
    const s = chart.addSeries(AreaSeries, { lineColor: rgb('accent'), topColor: rgb('accent', 0.28), bottomColor: rgb('accent', 0), lineWidth: 2, priceLineVisible: false })
    s.setData(data.map(p => ({ ...p, time: p.time as UTCTimestamp })))
    lastTime.current = data.length ? data[data.length - 1].time : 0
    s.createPriceLine({ price: base, color: rgb('muted', 0.7), lineStyle: LineStyle.Dashed, lineWidth: 1, axisLabelVisible: true, title: '' })
    chart.timeScale().fitContent()
    seriesRef.current = s
    return () => { seriesRef.current = null; chart.remove() }
  }, [data, base, dark])
  // Live tick: append/refresh the newest point without rebuilding the chart (time must never go backwards).
  useEffect(() => {
    if (!live || !seriesRef.current || live.time < lastTime.current) return
    seriesRef.current.update({ time: live.time as UTCTimestamp, value: live.value })
    lastTime.current = live.time
  }, [live])
  return <div ref={ref} dir="ltr" style={{ height }} />
}
