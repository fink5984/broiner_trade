import { useEffect, useMemo, useRef, useState } from 'react'
import { AlertTriangle, Ban, Gauge, Landmark, Newspaper, Radio, Scale, Search, TrendingDown, TrendingUp } from 'lucide-react'
import { SYMBOL_NAMES, fmtSymbol, priceDigits, type Candle, type Point } from '../api'
import { PriceChart, type Level } from '../charts'
import { useApi, useLiveQuotes, useTick, type LiveQuote } from '../hooks'
import { Badge, Banner, Card, Empty, N, Segmented, SectionTitle, SignalBar, Skeleton, Sparkline, StatusDot, cx, type Tone } from '../ui'

interface Item {
  symbol: string; price: number; change_pct: number; spread: number | null; bid: number | null; ask: number | null
  quote_age_s: number | null; stale: boolean; demo: boolean; source: string
  technical: string; score: number; regime: string; trade_status: string; spark: number[]
}
const ageText = (s: number | null) => s == null ? '—' : s < 60 ? `${Math.round(s)} שנ׳` : s < 3600 ? `${Math.round(s / 60)} דק׳` : `${Math.round(s / 3600)} שע׳`
interface Tech {
  direction: string; score: number; trend_strength: number; regime: string; volatility: string; atr: number
  components: Record<string, number>; patterns: string[]; levels: (Level & { touches: number })[]; explanation: string[]
}
interface Detail { demo: boolean; candles: Candle[]; ema20: Point[]; ema50: Point[]; analysis: { technical: Tech }; decision: { action: string; reasons: string[]; blockers: string[] } }

const TFS = ['5m', '15m', '1h', '4h', '1d'] as const
const TF_SECONDS: Record<string, number> = { '5m': 300, '15m': 900, '1h': 3600, '4h': 14400, '1d': 86400 }

/** Overlay the 1-second SSE quote on the slower REST snapshot. Displayed price = BID (same basis as the
 *  BID candles in the chart). Change % keeps the server's 24h reference close. */
function withLive(i: Item, q: LiveQuote | undefined): Item {
  if (!q || i.demo) return i
  const ref = i.price / (1 + i.change_pct / 100)
  const age = Date.now() / 1000 - q.epoch
  return { ...i, price: q.bid, bid: q.bid, ask: q.ask, spread: q.spread, quote_age_s: age, stale: age > 120, change_pct: (q.bid / ref - 1) * 100 }
}
type TF = typeof TFS[number]
const TF_LABEL: Record<TF, string> = { '5m': '5 דק׳', '15m': '15 דק׳', '1h': 'שעה', '4h': '4 שעות', '1d': 'יום' }
const DIR: Record<string, [string, Tone]> = { BUY: ['קנייה', 'profit'], SELL: ['מכירה', 'loss'], NEUTRAL: ['ניטרלי', 'neutral'] }
const COMP: Record<string, string> = { ema: 'ממוצעים נעים (EMA)', rsi: 'RSI', macd: 'MACD', breakout: 'פריצה', patterns: 'תבניות נרות' }
const PATTERN: Record<string, string> = { doji: 'דוג׳י', hammer: 'פטיש', shooting_star: 'כוכב נופל', bullish_engulfing: 'בליעה עולה', bearish_engulfing: 'בליעה יורדת' }
const VOL: Record<string, string> = { high: 'גבוהה', low: 'נמוכה', normal: 'רגילה' }

export default function Markets() {
  const list = useApi<{ items: Item[] }>('/api/markets', 30_000)
  const live = useLiveQuotes()
  useTick(1000)
  const prev = useRef<Record<string, number>>({})
  const [flash, setFlash] = useState<Record<string, 'up' | 'down'>>({})
  useEffect(() => {
    const f: Record<string, 'up' | 'down'> = {}
    for (const [sym, q] of Object.entries(live.quotes)) {
      const p = prev.current[sym]
      if (p !== undefined && q.bid !== p) f[sym] = q.bid > p ? 'up' : 'down'
      prev.current[sym] = q.bid
    }
    if (Object.keys(f).length) { setFlash(f); const t = setTimeout(() => setFlash({}), 700); return () => clearTimeout(t) }
  }, [live.quotes])
  const [sel, setSel] = useState('USDILS')
  const [tf, setTf] = useState<TF>('15m')
  const [q, setQ] = useState('')
  const detail = useApi<Detail>(`/api/markets/${sel}?tf=${tf}`, 60_000)
  const anyDemo = list.data?.items.some(i => i.demo) ?? true
  const anyLive = list.data?.items.some(i => !i.demo) ?? false
  const d = detail.data
  const lines = useMemo(() => d ? [{ data: d.ema20, tone: 'accent' }, { data: d.ema50, tone: 'warn' }] : [], [d])
  const levels = useMemo(() => d?.analysis.technical.levels.slice(0, 4) ?? [], [d])
  const all = (list.data?.items ?? []).map(i => withLive(i, live.quotes[i.symbol]))
  const items = all.filter(i => !q || (i.symbol + SYMBOL_NAMES[i.symbol]).toLowerCase().includes(q.toLowerCase()))
  const cur = all.find(i => i.symbol === sel)
  const lq = live.quotes[sel]
  const liveBar = useMemo(() => (d && !d.demo && lq ? { price: lq.bid, epoch: lq.epoch } : null), [d, lq])
  const t = d?.analysis.technical
  const dg = priceDigits(sel)

  return (
    <div className="space-y-6">
      {anyLive ? (
        <Banner tone="profit" icon={Radio} title="נתוני שוק חיים מ-FXCM (חשבון דמו)">
          מחירי Bid/Ask נדחפים מהשרת כל שנייה (SSE){live.connected ? '' : ' — הזרם מתחבר מחדש…'}, והנר האחרון בגרף מתעדכן בזמן אמת.
          {anyDemo && ' נכסים שאינם מוצעים בחשבון מסומנים ״סינתטי״ ואינם נתוני שוק.'}
        </Banner>
      ) : (
        <Banner tone="warn" icon={AlertTriangle} title="מחירים סינתטיים">
          אין כרגע נתונים מספק המחירים (גשר FXCM לא פעיל), לכן הנרות סינתטיים ואינם נתוני שוק. הניתוח הטכני עצמו אמיתי ומחושב על הנרות המוצגים.
        </Banner>
      )}

      <div className="grid gap-6 xl:grid-cols-[340px_1fr]">
        <Card title="רשימת מעקב" subtitle={`${list.data?.items.length ?? 0} נכסים · מחירי Bid`} flush>
          <div className="border-b border-line p-3">
            <div className="relative">
              <Search size={15} className="pointer-events-none absolute start-3 top-1/2 -translate-y-1/2 text-muted" />
              <input className="input h-9 ps-9" placeholder="חיפוש נכס…" value={q} onChange={e => setQ(e.target.value)} />
            </div>
          </div>
          {list.loading && !list.data ? <div className="space-y-2 p-3">{[0, 1, 2, 3, 4].map(i => <Skeleton key={i} className="h-14" />)}</div> : (
            <ul className="divide-y divide-line">
              {items.map(i => {
                const up = i.change_pct >= 0
                const [dl, dt] = DIR[i.technical] ?? ['—', 'neutral']
                return (
                  <li key={i.symbol}>
                    <button onClick={() => setSel(i.symbol)} className={cx('relative flex w-full items-center gap-3 px-4 py-3 text-start transition',
                      sel === i.symbol ? 'bg-accent/[0.07]' : 'hover:bg-fg/[0.03]')}>
                      {sel === i.symbol && <span className="absolute inset-y-2 start-0 w-[3px] rounded-full bg-accent" />}
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2">
                          <N className="font-semibold">{fmtSymbol(i.symbol)}</N>
                          <Badge tone={dt} className="!px-1.5 !py-0 text-[10px]">{dl}</Badge>
                          {i.demo ? <Badge tone="warn" className="!px-1.5 !py-0 text-[10px]">סינתטי</Badge>
                            : i.stale ? <Badge tone="loss" className="!px-1.5 !py-0 text-[10px]">ישן</Badge>
                            : <StatusDot tone="profit" pulse />}
                        </div>
                        <div className="truncate text-xs text-muted">{SYMBOL_NAMES[i.symbol]}</div>
                      </div>
                      <Sparkline data={i.spark} tone={up ? 'profit' : 'loss'} className="h-8 w-16 shrink-0" />
                      <div className="w-[86px] shrink-0 text-end">
                        <N className={cx('block rounded text-sm font-medium transition-colors duration-500', flash[i.symbol] === 'up' ? 'bg-profit/15 text-profit' : flash[i.symbol] === 'down' ? 'bg-loss/15 text-loss' : '')}>{i.price.toFixed(priceDigits(i.symbol))}</N>
                        <N className={cx('block text-xs', up ? 'text-profit' : 'text-loss')}>{up ? '+' : ''}{i.change_pct.toFixed(2)}%</N>
                      </div>
                    </button>
                  </li>
                )
              })}
            </ul>
          )}
        </Card>

        <div className="min-w-0 space-y-6">
          <Card flush>
            <div className="flex flex-wrap items-center gap-x-6 gap-y-3 border-b border-line px-5 py-4">
              <div>
                <div className="flex items-center gap-2"><N className="text-xl font-bold">{fmtSymbol(sel)}</N><span className="text-sm text-muted">{SYMBOL_NAMES[sel]}</span></div>
                {cur && (
                  <div className="mt-0.5 flex items-baseline gap-3">
                    <N className={cx('rounded px-1 text-2xl font-semibold tracking-tight transition-colors duration-500', flash[sel] === 'up' ? 'bg-profit/15 text-profit' : flash[sel] === 'down' ? 'bg-loss/15 text-loss' : '')}>{cur.price.toFixed(dg)}</N>
                    {!cur.demo && <span className="text-xs font-medium text-muted">Bid</span>}
                    <N className={cx('flex items-center gap-1 text-sm font-medium', cur.change_pct >= 0 ? 'text-profit' : 'text-loss')}>
                      {cur.change_pct >= 0 ? <TrendingUp size={14} /> : <TrendingDown size={14} />}{cur.change_pct >= 0 ? '+' : ''}{cur.change_pct.toFixed(2)}%
                    </N>
                  </div>
                )}
                {cur && (cur.demo
                  ? <div className="mt-1"><Badge tone="warn" dot>נתונים סינתטיים</Badge></div>
                  : <div className="mt-1.5 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted">
                      <Badge tone={cur.stale ? 'loss' : 'profit'} dot>{cur.stale ? 'מחיר לא עדכני' : 'חי · FXCM Demo'}</Badge>
                      <span>Bid <N className="text-fg">{cur.bid?.toFixed(dg + 1)}</N></span>
                      <span>Ask <N className="text-fg">{cur.ask?.toFixed(dg + 1)}</N></span>
                      <span>Spread <N className="text-fg">{cur.spread?.toFixed(dg + 1)}</N></span>
                      <span>עודכן לפני <N className="text-fg">{ageText(cur.quote_age_s)}</N></span>
                    </div>)}
              </div>
              <div className="ms-auto flex flex-wrap items-center gap-3">
                <div className="hidden items-center gap-3 text-xs text-muted md:flex">
                  <span className="flex items-center gap-1.5"><span className="h-0.5 w-4 rounded bg-accent" />EMA 20</span>
                  <span className="flex items-center gap-1.5"><span className="h-0.5 w-4 rounded bg-warn" />EMA 50</span>
                  <span className="flex items-center gap-1.5"><span className="w-4 border-t border-dashed border-profit" />תמיכה / התנגדות</span>
                </div>
                <Segmented options={TFS.map(x => ({ value: x, label: TF_LABEL[x] }))} value={tf} onChange={setTf} />
              </div>
            </div>
            <div className="px-2 py-3">
              {d ? <PriceChart candles={d.candles} lines={lines} levels={levels} live={liveBar} tfSeconds={TF_SECONDS[tf]} /> : <Skeleton className="mx-3 h-[420px]" />}
            </div>
          </Card>

          <Card title="ניתוח טכני" icon={Gauge} subtitle={`דטרמיניסטי · ניתן לשחזור · ${TF_LABEL[tf]}`} actions={t && <Badge tone={DIR[t.direction]?.[1] ?? 'neutral'} dot>{DIR[t.direction]?.[0]}</Badge>}>
            {!t ? <Skeleton className="h-48" /> : (
              <div className="grid gap-8 md:grid-cols-2">
              <div>
                <div className="flex items-end justify-between">
                  <div><div className="text-xs text-muted">ציון משוקלל</div><N className="text-2xl font-semibold">{t.score >= 0 ? '+' : ''}{t.score.toFixed(2)}</N></div>
                  <div className="text-end text-xs text-muted">
                    <div>{t.regime === 'trending' ? 'מגמה' : 'דשדוש'} · חוזק <N className="text-fg">{Math.round(t.trend_strength * 100)}%</N></div>
                    <div>תנודתיות {VOL[t.volatility] ?? t.volatility} · ATR <N className="text-fg">{t.atr.toFixed(dg)}</N></div>
                  </div>
                </div>
                <div className="mt-2"><SignalBar value={t.score} /></div>
                <div className="mt-5 space-y-3">
                  <SectionTitle>רכיבים</SectionTitle>
                  {Object.entries(t.components).map(([k, v]) => (
                    <div key={k} className="grid grid-cols-[minmax(0,1fr)_minmax(80px,1fr)_44px] items-center gap-3 text-sm">
                      <span className="truncate">{COMP[k] ?? k}</span><SignalBar value={v} />
                      <N className={cx('text-end text-xs', v > 0 ? 'text-profit' : v < 0 ? 'text-loss' : 'text-muted')}>{v.toFixed(2)}</N>
                    </div>
                  ))}
                </div>
              </div>
              <div className="space-y-5">
                <div>
                  <SectionTitle>תבניות נרות</SectionTitle>
                  <div className="flex flex-wrap gap-1.5">
                    {t.patterns.length ? t.patterns.map(p => <Badge key={p} tone="info">{PATTERN[p] ?? p}</Badge>) : <span className="text-sm text-muted">לא זוהו תבניות בנר האחרון</span>}
                  </div>
                </div>
                <div>
                  <SectionTitle>תמיכה והתנגדות</SectionTitle>
                  {levels.length ? (
                    <div className="grid grid-cols-2 gap-2">
                      {levels.map(l => (
                        <div key={l.price} className="flex items-center justify-between gap-2 rounded-lg bg-fg/[0.04] px-3 py-2 text-xs">
                          <span className={l.kind === 'support' ? 'text-profit' : 'text-loss'}>{l.kind === 'support' ? 'תמיכה' : 'התנגדות'}</span>
                          <N className="font-medium">{l.price.toFixed(dg)}</N>
                        </div>
                      ))}
                    </div>
                  ) : <span className="text-sm text-muted">לא זוהו רמות</span>}
                </div>
                <div>
                  <SectionTitle>הסבר</SectionTitle>
                  <ul dir="ltr" className="num space-y-1 text-start text-[11px] text-muted">{t.explanation.map(x => <li key={x}>{x}</li>)}</ul>
                </div>
              </div>
              </div>
            )}
          </Card>

          <div className="grid gap-6 md:grid-cols-2">
            <Card title="ניתוח חדשות" icon={Newspaper} subtitle="AI · Gemini" actions={<Badge tone="loss" dot>לא מחובר</Badge>}>
              <Empty compact icon={Newspaper} title="אין ידיעות לנכס" text="נדרשים מחברי GDELT / RSS ומפתח Gemini. כל ידיעה תוצג עם מקור, זמן פרסום, השפעה צפויה ועוצמה." />
            </Card>

            <Card title="ניתוח נגידים ומאקרו" icon={Landmark} subtitle="ריבית · נאומים · נתונים" actions={<Badge tone="loss" dot>לא מחובר</Badge>}>
              <Empty compact icon={Landmark} title="אין אירועי מדיניות" text="נדרשים מחברים לבנק ישראל, Fed, BoE, ECB ו-FRED. הפתעות יחושבו רק מול תחזיות ממקור אמין." />
            </Card>
          </div>

          <Card title="החלטה סופית" icon={Scale} subtitle="מנוע החלטות · ניהול סיכונים"
            actions={d && <Badge tone="warn" className="!text-sm">{d.decision.action}</Badge>}>
            {!d ? <Skeleton className="h-20" /> : (
              <div className="grid gap-6 md:grid-cols-2">
                <div>
                  <SectionTitle>נתונים שבשימוש</SectionTitle>
                  <ul className="space-y-2 text-sm">
                    <li className="flex items-center gap-2"><span className="h-1.5 w-1.5 rounded-full bg-profit" />ניתוח טכני · {TF_LABEL[tf]} · <N>{d.candles.length}</N> נרות</li>
                    <li className="flex items-center gap-2 text-muted"><span className="h-1.5 w-1.5 rounded-full bg-loss" />ניתוח חדשות · לא זמין</li>
                    <li className="flex items-center gap-2 text-muted"><span className="h-1.5 w-1.5 rounded-full bg-loss" />ניתוח נגידים · לא זמין</li>
                  </ul>
                </div>
                <div>
                  <SectionTitle>מגבלות שמנעו מסחר</SectionTitle>
                  <ul className="space-y-2">
                    {d.decision.blockers.map(b => <li key={b} className="flex items-start gap-2 text-sm"><Ban size={15} className="mt-0.5 shrink-0 text-loss" />{b}</li>)}
                  </ul>
                </div>
              </div>
            )}
          </Card>
        </div>
      </div>
    </div>
  )
}
