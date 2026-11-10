import { useMemo, useState } from 'react'
import { AlertTriangle, BarChart2, Coins, FlaskConical, GitCompare, Layers, LineChart, ListOrdered, Play, Sigma, SlidersHorizontal, Sparkles, Target, TrendingDown, Trophy, Wand2 } from 'lucide-react'
import { SYMBOL_NAMES, api, fmtMoney, fmtSymbol, priceDigits, type Point } from '../api'
import { EquityChart } from '../charts'
import { Badge, Banner, Button, Card, Empty, Field, Input, N, SectionTitle, Select, Skeleton, Stat, Tabs, cx, pnlTone } from '../ui'

interface Trade { side: string; entry_time: string; entry: number; units: number; sl: number; tp: number; exit: number; exit_time: string; reason: string; costs: number; net: number }
interface Result { metrics: Record<string, number | null>; equity: Point[]; trades: Trade[]; rejected_by_risk: number; demo: boolean; source: string; candles_used: number; period: [string, string] }
type Form = Record<'candles' | 'initial_capital' | 'spread' | 'slippage' | 'commission_per_unit' | 'atr_sl_mult' | 'rr' | 'ema_fast' | 'ema_slow' | 'rsi_period' | 'risk_per_trade_pct', number> & { symbol: string }

const DEFAULTS: Form = { symbol: 'USDILS', candles: 900, initial_capital: 10000, spread: 0.01, slippage: 0.002, commission_per_unit: 0,
  atr_sl_mult: 1.5, rr: 2, ema_fast: 20, ema_slow: 50, rsi_period: 14, risk_per_trade_pct: 0.25 }
const REASON: Record<string, string> = { STOP_LOSS: 'Stop Loss', TAKE_PROFIT: 'Take Profit', MAX_HOLD: 'זמן החזקה', SIGNAL_REVERSAL: 'היפוך אות', END_OF_DATA: 'סוף נתונים' }

const SECTIONS: { title: string; icon: typeof Layers; fields: { k: keyof Form; label: string; hint?: string; unit?: string; step?: number }[] }[] = [
  { title: 'נתונים והון', icon: Layers, fields: [
    { k: 'candles', label: 'מספר נרות', hint: 'נרות של 15 דקות (300–3000).', step: 100 },
    { k: 'initial_capital', label: 'הון התחלתי', unit: '₪', step: 500 },
    { k: 'risk_per_trade_pct', label: 'סיכון לעסקה', unit: '%', hint: 'נאכף ע״י מנוע הסיכון (תקרה 1%).', step: 0.05 },
  ] },
  { title: 'עלויות מסחר', icon: Coins, fields: [
    { k: 'spread', label: 'Spread', hint: 'ביחידות מחיר.', step: 0.001 },
    { k: 'slippage', label: 'Slippage', hint: 'החלקה בכל ביצוע.', step: 0.001 },
    { k: 'commission_per_unit', label: 'עמלה ליחידה', step: 0.0001 },
  ] },
  { title: 'ניהול עסקה', icon: Target, fields: [
    { k: 'atr_sl_mult', label: 'Stop Loss', unit: '× ATR', step: 0.1 },
    { k: 'rr', label: 'יחס רווח/סיכון', hint: 'Take Profit = Stop × יחס.', step: 0.1 },
  ] },
  { title: 'אינדיקטורים', icon: SlidersHorizontal, fields: [
    { k: 'ema_fast', label: 'EMA מהיר', step: 1 },
    { k: 'ema_slow', label: 'EMA איטי', step: 1 },
    { k: 'rsi_period', label: 'תקופת RSI', step: 1 },
  ] },
]

function Histogram({ values }: { values: number[] }) {
  const bins = useMemo(() => {
    if (!values.length) return []
    const min = Math.min(...values), max = Math.max(...values), n = 12, w = (max - min) / n || 1
    const b = Array.from({ length: n }, (_, i) => ({ from: min + i * w, count: 0 }))
    values.forEach(v => { b[Math.min(n - 1, Math.floor((v - min) / w))].count++ })
    return b
  }, [values])
  const top = Math.max(1, ...bins.map(b => b.count))
  return (
    <div dir="ltr">
      <div className="flex h-40 items-end gap-1">
        {bins.map((b, i) => (
          <div key={i} className="group relative flex-1" style={{ height: '100%' }}>
            <div className={cx('absolute bottom-0 w-full rounded-t-md transition-opacity group-hover:opacity-80', b.from + (bins[1]?.from - bins[0]?.from || 0) / 2 >= 0 ? 'bg-profit/80' : 'bg-loss/80')}
              style={{ height: `${(b.count / top) * 100}%`, minHeight: b.count ? 3 : 0 }} />
            <div className="pointer-events-none absolute -top-6 left-1/2 hidden -translate-x-1/2 rounded bg-fg px-1.5 py-0.5 text-[10px] text-bg group-hover:block num">{b.count}</div>
          </div>
        ))}
      </div>
      {bins.length > 0 && <div className="num mt-2 flex justify-between text-[11px] text-muted"><span>{bins[0].from.toFixed(0)} ₪</span><span>0</span><span>{(bins[bins.length - 1].from + (bins[1].from - bins[0].from)).toFixed(0)} ₪</span></div>}
    </div>
  )
}

function Lab() {
  const [f, setF] = useState<Form>(DEFAULTS)
  const [res, setRes] = useState<Result | null>(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const run = async () => {
    setBusy(true); setErr('')
    try { setRes(await api<Result>('/api/backtest', { body: f })) } catch (e) { setErr((e as Error).message) } finally { setBusy(false) }
  }
  const m = res?.metrics
  const n = (v: number | null | undefined, d = 2) => v == null ? '—' : v.toFixed(d)
  const reasons = useMemo(() => {
    const c: Record<string, number> = {}
    res?.trades.forEach(t => { c[t.reason] = (c[t.reason] ?? 0) + 1 })
    return Object.entries(c).sort((a, b) => b[1] - a[1])
  }, [res])
  const dg = priceDigits(f.symbol)

  return (
    <div className="grid gap-6 xl:grid-cols-[360px_1fr]">
      <Card title="הגדרות בדיקה" icon={FlaskConical} className="xl:sticky xl:top-24 xl:self-start"
        footer={<Button variant="primary" icon={Play} className="w-full" size="lg" onClick={run} disabled={busy}>{busy ? 'מריץ בדיקה…' : 'הרץ Backtest'}</Button>}>
        <div className="space-y-6">
          <Field label="נכס">
            <Select value={f.symbol} onChange={e => setF({ ...f, symbol: e.target.value })}>
              {Object.keys(SYMBOL_NAMES).map(s => <option key={s} value={s}>{fmtSymbol(s)} · {SYMBOL_NAMES[s]}</option>)}
            </Select>
          </Field>
          {SECTIONS.map(sec => (
            <div key={sec.title}>
              <SectionTitle><span className="flex items-center gap-1.5"><sec.icon size={13} />{sec.title}</span></SectionTitle>
              <div className="grid grid-cols-2 gap-3">
                {sec.fields.map(fl => (
                  <Field key={fl.k} label={fl.label} unit={fl.unit} hint={fl.hint} className={sec.fields.length === 3 && fl === sec.fields[0] ? 'col-span-2' : ''}>
                    <Input dir="ltr" type="number" step={fl.step ?? 'any'} value={f[fl.k] as number} onChange={e => setF({ ...f, [fl.k]: Number(e.target.value) })} />
                  </Field>
                ))}
              </div>
            </div>
          ))}
          {err && <div className="rounded-xl bg-loss/10 px-3 py-2 text-sm text-loss">{err}</div>}
        </div>
      </Card>

      <div className="min-w-0 space-y-6">
        {res && !res.demo ? (
          <Banner tone="profit" icon={AlertTriangle} title="נתוני היסטוריה אמיתיים · FXCM Demo">
            <N>{res.candles_used}</N> נרות של 15 דקות, <N>{res.period[0].slice(0, 10)}</N> עד <N>{res.period[1].slice(0, 10)}</N>. תקופה קצרה כזו אינה מספיקה להסקת מסקנות על רווחיות — ביצועי עבר אינם מבטיחים ביצועים עתידיים.
          </Banner>
        ) : (
          <Banner tone="warn" icon={AlertTriangle} title="נתוני בדיקה סינתטיים">
            לנכס זה אין מספיק נרות אמיתיים במסד (נדרשים לפחות 300), לכן הבדיקה רצה על נרות סינתטיים. התוצאות מדגימות את המנוע בלבד ואינן מעידות על רווחיות.
          </Banner>
        )}

        {busy && !res && <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">{Array.from({ length: 8 }, (_, i) => <Skeleton key={i} className="h-24" />)}</div>}
        {!busy && !res && (
          <Card><Empty icon={BarChart2} title="עוד לא הורצה בדיקה" text="בחר נכס ופרמטרים ולחץ ״הרץ Backtest״. ההרצה לוקחת כמה שניות." /></Card>
        )}

        {res && m && (
          <div className={cx('space-y-6 transition-opacity', busy && 'opacity-50')}>
            <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
              <Stat label="תשואה נטו" value={(m.net_return_pct! >= 0 ? '+' : '') + n(m.net_return_pct) + '%'} tone={pnlTone(m.net_return_pct)} icon={TrendingDown}
                sub={<>הון סופי <N>{fmtMoney(m.final_equity ?? 0)} ₪</N></>} />
              <Stat label="מספר עסקאות" value={String(m.trades)} icon={ListOrdered} sub={`נדחו ע״י סיכון: ${res.rejected_by_risk}`} />
              <Stat label="Win Rate" value={n(m.win_rate, 1) + '%'} icon={Trophy} />
              <Stat label="Profit Factor" value={n(m.profit_factor)} icon={Sigma} />
              <Stat label="Expectancy לעסקה" value={n(m.expectancy) + ' ₪'} tone={pnlTone(m.expectancy)} icon={Target} />
              <Stat label="ממוצע רווח / הפסד" value={n(m.avg_win, 1) + ' / ' + n(m.avg_loss, 1)} icon={GitCompare} />
              <Stat label="Max Drawdown" value={n(m.max_drawdown_pct) + '%'} tone={(m.max_drawdown_pct ?? 0) > 5 ? 'loss' : 'warn'} icon={TrendingDown} />
              <Stat label="Sharpe / Sortino" value={n(m.sharpe) + ' / ' + n(m.sortino)} icon={LineChart} sub="דורש ≥ 20 ימי מסחר" />
            </div>

            <Card title="עקומת הון" icon={LineChart} subtitle={<>עלויות כוללות <N>{n(m.total_costs)} ₪</N></>}>
              <EquityChart data={res.equity} base={f.initial_capital} />
            </Card>

            <div className="grid gap-6 lg:grid-cols-2">
              <Card title="התפלגות רווח / הפסד" icon={BarChart2} subtitle="לפי עסקה, נטו">
                {res.trades.length ? <Histogram values={res.trades.map(t => t.net)} /> : <Empty compact title="אין עסקאות" />}
              </Card>
              <Card title="סיבות יציאה" icon={Layers}>
                <div className="space-y-3">
                  {reasons.map(([k, c]) => (
                    <div key={k}>
                      <div className="mb-1 flex justify-between text-sm"><span>{REASON[k] ?? k}</span><N className="text-muted">{c}</N></div>
                      <div className="h-2 rounded-full bg-fg/[0.06]"><div className="h-2 rounded-full bg-accent" style={{ width: `${(c / res.trades.length) * 100}%` }} /></div>
                    </div>
                  ))}
                  {!reasons.length && <Empty compact title="אין עסקאות" />}
                </div>
              </Card>
            </div>

            <Card title="עסקאות הבדיקה" icon={ListOrdered} subtitle={`${res.trades.length} עסקאות · מוצגות 100 האחרונות`} flush>
              <div className="max-h-[480px] overflow-auto">
                <table className="tbl">
                  <thead><tr>{['#', 'כיוון', 'כניסה', 'מחיר כניסה', 'יחידות', 'Stop', 'Target', 'יציאה', 'סיבה', 'עלויות', 'נטו ₪'].map(h => <th key={h}>{h}</th>)}</tr></thead>
                  <tbody>
                    {res.trades.slice(-100).reverse().map((t, i) => (
                      <tr key={i}>
                        <td className="text-muted"><N>{res.trades.length - i}</N></td>
                        <td><Badge tone={t.side === 'BUY' ? 'profit' : 'loss'}>{t.side === 'BUY' ? 'קנייה' : 'מכירה'}</Badge></td>
                        <td><N className="text-xs">{t.entry_time.slice(5, 16).replace('T', ' ')}</N></td>
                        <td><N>{t.entry.toFixed(dg)}</N></td>
                        <td><N>{fmtMoney(t.units)}</N></td>
                        <td><N className="text-loss/80">{t.sl.toFixed(dg)}</N></td>
                        <td><N className="text-profit/80">{t.tp.toFixed(dg)}</N></td>
                        <td><N>{t.exit.toFixed(dg)}</N></td>
                        <td className="text-xs text-muted">{REASON[t.reason] ?? t.reason}</td>
                        <td><N className="text-muted">{t.costs.toFixed(2)}</N></td>
                        <td><N className={cx('font-semibold', t.net >= 0 ? 'text-profit' : 'text-loss')}>{t.net >= 0 ? '+' : ''}{t.net.toFixed(2)}</N></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
          </div>
        )}
      </div>
    </div>
  )
}

type TabKey = 'lab' | 'strategies' | 'optimize'

export default function Strategies() {
  const [tab, setTab] = useState<TabKey>('lab')
  return (
    <div className="space-y-6">
      <Tabs value={tab} onChange={setTab} tabs={[
        { value: 'lab', label: 'מעבדת Backtest', icon: FlaskConical },
        { value: 'strategies', label: 'אסטרטגיות וגרסאות', icon: GitCompare, count: 0 },
        { value: 'optimize', label: 'אופטימיזציה ו-Walk-Forward', icon: Wand2 },
      ]} />
      {tab === 'lab' && <Lab />}
      {tab === 'strategies' && (
        <Card><Empty icon={Sparkles} title="אין אסטרטגיות שמורות"
          text="יצירה, שכפול, עריכה, גרסאות בלתי ניתנות לשינוי, השוואה והפעלה בדמו — טבלאות ה-DB קיימות (strategies, strategy_versions), ממשק הניהול ייבנה בשלב הבא." /></Card>
      )}
      {tab === 'optimize' && (
        <Card><Empty icon={Wand2} title="אופטימיזציה טרם חוברה לממשק"
          text="מנוע ה-Walk-Forward (אימון / אימות / מבחן) וחיפוש הפרמטרים קיימים ב-backend ונבדקו. הדירוג מעדיף יציבות ותוחלת חיובית בכל התקופות, לא תשואה מרבית. אסטרטגיה מנצחת לעולם לא מופעלת אוטומטית." /></Card>
      )}
    </div>
  )
}
