import { useContext, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { Activity, Bell, Brain, CheckCircle2, Cpu, Database, GitBranch, Inbox, Info, Landmark, Layers, LineChart, Newspaper, Octagon, Pause, Play, Power, Radio, RotateCcw, ShieldAlert, ShieldCheck, Target, Wallet } from 'lucide-react'
import { api, fmtMoney, type AlertRow, type DecisionRow, type Overview, type Point, type SettingDoc } from '../api'
import { TokenPrompt, getToken, setToken } from '../auth'
import { EquityChart } from '../charts'
import { StatusCtx, useApi } from '../hooks'
import { Badge, Banner, Button, Card, Empty, KV, N, Stat, StatusDot, ThresholdMeter, type Tone } from '../ui'

type Risk = Record<string, number>

const STATE: Record<string, { label: string; sub: string; tone: Tone }> = {
  ACTIVE: { label: 'המסחר האוטומטי פעיל', sub: 'מצב דמו · החלטות על כל נר 15 דקות שנסגר', tone: 'profit' },
  PAUSED: { label: 'המערכת מושהית', sub: 'אין פתיחת עסקאות חדשות · עסקאות פתוחות ממשיכות להיות מנוהלות', tone: 'warn' },
  EMERGENCY_STOP: { label: 'עצירת חירום', sub: 'כל הפוזיציות נסגרו · חזרה רק באישור ידני', tone: 'loss' },
}
const ACTION_TONE: Record<string, Tone> = { BUY: 'profit', SELL: 'loss', CLOSE: 'warn', HOLD: 'neutral', NO_TRADE: 'neutral' }
const SEV_TONE: Record<string, Tone> = { info: 'info', warning: 'warn', critical: 'loss' }
const BOX: Record<string, string> = { profit: 'bg-profit/[0.08] ring-profit/20', loss: 'bg-loss/[0.08] ring-loss/20', warn: 'bg-warn/[0.08] ring-warn/20' }

const fmtTime = (iso: string) => new Date(iso).toLocaleString('he-IL', { dateStyle: 'short', timeStyle: 'short' })
const Pnl = ({ v, d = 2 }: { v: number; d?: number }) => <N className={v > 0 ? 'text-profit' : v < 0 ? 'text-loss' : undefined}>{v > 0 ? '+' : ''}{fmtMoney(v, d)} ₪</N>

export default function Dashboard() {
  const { status } = useContext(StatusCtx)
  const risk = useApi<SettingDoc<Risk>>('/api/settings/risk')
  const ov = useApi<Overview>('/api/trading/overview', 5_000)
  const eq = useApi<{ items: Point[] }>('/api/trading/equity', 30_000)
  const lv = useApi<{ ts: number; equity: number | null }>('/api/trading/live', 1_000)
  const decisions = useApi<{ items: DecisionRow[] }>('/api/decisions?limit=8', 15_000)
  const alerts = useApi<{ items: AlertRow[] }>('/api/alerts?limit=8', 15_000)
  const [ask, setAsk] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const r = risk.data?.value
  const o = ov.data
  const liveEq = lv.data?.equity ?? null
  const livePoint = useMemo<Point | null>(() => (lv.data && lv.data.equity != null ? { time: Math.floor(lv.data.ts), value: lv.data.equity } : null), [lv.data])
  const delta = o && liveEq != null ? liveEq - o.equity : 0   // live equity vs. the 5s overview snapshot
  const capital = o?.initial_capital ?? status?.initial_capital ?? 10_000
  const dbOk = status?.database === 'connected'
  const st = STATE[o?.state ?? 'PAUSED'] ?? STATE.PAUSED

  const act = async (action: string, token?: string) => {
    const t = token ?? getToken()
    if (!t) { setAsk(action); return }
    setBusy(true); setErr(null)
    try {
      await api('/api/system/' + action, { method: 'POST', body: {}, token: t })
      setToken(t)
      await ov.reload()
    } catch (e) {
      const x = e as Error & { status?: number }
      if (x.status === 401) { setToken(null); setAsk(action) }
      setErr(x.message)
    } finally { setBusy(false) }
  }

  const health: { name: string; desc: string; icon: typeof Activity; state: string; tone: Tone }[] = [
    { name: 'שרת API', desc: 'FastAPI', icon: Cpu, state: status ? 'פעיל' : 'לא זמין', tone: status ? 'profit' : 'loss' },
    { name: 'מסד נתונים', desc: 'PostgreSQL · Neon', icon: Database, state: dbOk ? 'מחובר' : 'לא מחובר', tone: dbOk ? 'profit' : 'loss' },
    { name: 'ברוקר', desc: 'PaperBroker (מדומה)', icon: Landmark, state: o?.service_running ? 'פעיל' : 'לא פעיל', tone: o?.service_running ? 'profit' : 'warn' },
    status?.market_data === 'fxcm_demo'
      ? { name: 'נתוני שוק', desc: 'FXCM ForexConnect · חשבון דמו', icon: Radio, state: 'חי', tone: 'profit' }
      : { name: 'נתוני שוק', desc: 'גשר FXCM לא פעיל', icon: Radio, state: 'סינתטי', tone: 'warn' },
    { name: 'חדשות', desc: 'GDELT · RSS · בנקים מרכזיים (איסוף בלבד)', icon: Newspaper, state: status?.news === 'connected' ? 'מחובר' : 'לא מחובר', tone: status?.news === 'connected' ? 'profit' : 'loss' },
    { name: 'מנוע AI', desc: 'Google Gemini', icon: Brain, state: 'לא מוגדר', tone: 'loss' },
    { name: 'שירות מסחר ברקע', desc: o?.last_error ? o.last_error : 'החלטות · סיכון · ביצוע', icon: Activity,
      state: o?.last_error ? 'תקלה' : o?.service_running ? 'פעיל' : 'לא פעיל', tone: o?.last_error ? 'loss' : o?.service_running ? 'profit' : 'warn' },
  ]
  const curve = eq.data?.items ?? []

  return (
    <div className="space-y-6">
      {ask && <TokenPrompt reason="פעולות בקרת מסחר דורשות טוקן מנהל" onCancel={() => setAsk(null)} onDone={t => { const a = ask; setAsk(null); act(a, t) }} />}
      <Banner tone="info" icon={Info} title="מסחר דמו בלבד · מנוע טכני בלבד">
        אין חיבור לברוקר חי וכסף אמיתי לא בשימוש. ניתוח ה-AI של חדשות ונגידים עדיין לא מחובר, ולכן ההחלטות מבוססות על הניתוח הטכני בלבד ועוברות את מנוע הסיכון.
      </Banner>

      <div className="grid gap-6 xl:grid-cols-3">
        <Card className="xl:col-span-2" title="שווי חשבון" subtitle="Paper · שקל חדש" icon={Wallet}>
          <div className="flex flex-wrap items-end gap-x-12 gap-y-5">
            <div>
              <div className="text-xs font-medium text-muted">שווי נוכחי (Equity)</div>
              <div className="mt-1 text-4xl font-semibold tracking-tight"><N>{o ? `${fmtMoney(liveEq ?? o.equity, 2)} ₪` : '—'}</N>{liveEq != null && <span className="ms-3 inline-flex items-center gap-1 align-middle text-xs font-medium text-profit"><span className="h-1.5 w-1.5 animate-pulse rounded-full bg-profit" />LIVE</span>}</div>
              <div className="mt-1.5 text-xs text-muted">הון התחלתי <N className="text-fg">{fmtMoney(capital)} ₪</N></div>
            </div>
            <div className="grid flex-1 grid-cols-2 gap-x-8 gap-y-3 sm:grid-cols-4">
              {([['היום', 'day'], ['השבוע', 'week'], ['החודש', 'month'], ['מתחילת הפעילות', 'total']] as const).map(([label, k]) => (
                <div key={k}><div className="text-xs text-muted">רו״ה {label}</div><div className="mt-0.5 font-semibold">{o ? <Pnl v={o.pnl[k] + delta} /> : <N>—</N>}</div></div>
              ))}
            </div>
          </div>
          <div className="mt-4 flex flex-wrap gap-2 text-xs">
            <span className="rounded-lg bg-fg/[0.04] px-2.5 py-1 text-muted">ממומש <N className="ms-1 text-fg">{o ? <Pnl v={o.realized} /> : '—'}</N></span>
            <span className="rounded-lg bg-fg/[0.04] px-2.5 py-1 text-muted">לא ממומש <N className="ms-1 text-fg">{o ? <Pnl v={o.unrealized + delta} /> : '—'}</N></span>
            <span className="rounded-lg bg-fg/[0.04] px-2.5 py-1 text-muted">מרווח בשימוש <N className="ms-1 text-fg">{o ? `${fmtMoney(o.margin_used, 0)} ₪` : '—'}</N></span>
          </div>
          <div className="mt-5 rounded-xl border border-line bg-surface2/50">
            {curve.length >= 2 ? <EquityChart data={curve} base={capital} height={240} live={livePoint} />
              : <Empty compact icon={LineChart} title="אין עדיין היסטוריית הון" text="נקודת הון נשמרת כל דקה בזמן שהשירות רץ. הגרף יופיע אחרי כמה דקות." />}
          </div>
        </Card>

        <Card title="בקרת מסחר" icon={Power}>
          <div className={`flex items-center gap-3 rounded-xl p-4 ring-1 ring-inset ${BOX[st.tone] ?? BOX.warn}`}>
            <StatusDot tone={st.tone} pulse />
            <div>
              <div className="font-semibold">{st.label}</div>
              <div className="text-xs text-muted">{st.sub}</div>
            </div>
          </div>
          <div className="mt-4 space-y-2.5">
            {o?.state === 'EMERGENCY_STOP'
              ? <Button variant="secondary" icon={RotateCcw} className="w-full" disabled={busy} onClick={() => act('reset')}>שחרר עצירת חירום (יעבור למושהה)</Button>
              : <>
                <Button variant="success" icon={Play} className="w-full" disabled={busy || o?.state !== 'PAUSED' || !o?.service_running} onClick={() => act('start')}>הפעל מסחר אוטומטי</Button>
                <Button variant="secondary" icon={Pause} className="w-full" disabled={busy || o?.state !== 'ACTIVE'} onClick={() => act('pause')}>השהה פתיחת עסקאות חדשות</Button>
                <Button variant="danger" icon={Octagon} className="w-full" disabled={busy || !o} onClick={() => { if (window.confirm('עצירת חירום סוגרת את כל הפוזיציות וחוסמת מסחר עד שחרור ידני. להמשיך?')) act('emergency-stop') }}>עצירת חירום</Button>
              </>}
          </div>
          {err && <p className="mt-3 text-sm text-loss">{err}</p>}
          <p className="mt-4 text-xs leading-relaxed text-muted">
            ההפעלה דורשת טוקן מנהל וכל שינוי מצב נרשם ביומן הביקורת. עצירת חירום: סגירת כל הפוזיציות וחסימת עסקאות חדשות. היא גם מופעלת אוטומטית כש-Drawdown חוצה את הסף.
          </p>
        </Card>
      </div>

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Stat label="עסקאות פתוחות" value={o?.open_trades ?? 0} icon={Layers} sub={o?.open_trades ? 'ראה לשונית עסקאות' : 'אין פוזיציות'} />
        <Stat label="עסקאות שהסתיימו" value={o?.closed_trades ?? 0} icon={CheckCircle2} sub={o?.closed_trades ? undefined : 'אין היסטוריה'} />
        <Stat label="אחוז עסקאות מוצלחות" value={o?.win_rate != null ? `${o.win_rate.toFixed(0)}%` : '—'} icon={Target} sub={o?.closed_trades ? `מתוך ${o.closed_trades} עסקאות` : 'נדרשות עסקאות סגורות'} />
        <Stat label="סיכון בפוזיציות פתוחות" value={`${(o?.open_risk_pct ?? 0).toFixed(2)}%`} icon={ShieldAlert} sub={r ? `מתוך ${r.max_aggregate_risk_pct}% מותר` : ' '} />
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card title="ניהול סיכונים" icon={ShieldCheck}
          subtitle={risk.data ? (risk.data.is_default ? 'ברירות מחדל' : `תצורה גרסה ${risk.data.version}`) : 'טוען…'}
          actions={<Link to="/settings" className="text-xs font-medium text-accent hover:underline">עריכת מגבלות</Link>}>
          <div className="flex items-baseline justify-between">
            <span className="text-sm font-medium">Drawdown נוכחי מהשיא</span>
            <span className="text-sm text-muted"><N>{o ? `${o.drawdown_pct.toFixed(2)}%` : '—'}</N>{o && <> · שיא <N>{fmtMoney(o.peak_equity, 0)} ₪</N></>}</span>
          </div>
          {r && <ThresholdMeter value={o?.drawdown_pct ?? null} max={20} marks={[{ at: r.dd_reduce_pct, tone: 'warn' }, { at: r.dd_block_pct, tone: 'loss' }, { at: r.dd_emergency_pct, tone: 'loss' }]} />}
          {r && (
            <div className="mt-1 flex flex-wrap gap-x-5 gap-y-1 text-xs text-muted">
              <span><b className="text-warn">{r.dd_reduce_pct}%</b> הפחתת סיכון</span>
              <span><b className="text-loss">{r.dd_block_pct}%</b> חסימת עסקאות</span>
              <span><b className="text-loss">{r.dd_emergency_pct}%</b> עצירת חירום</span>
            </div>
          )}
          {r && (
            <div className="mt-4 grid divide-y divide-line border-t border-line sm:grid-cols-2 sm:gap-x-8 sm:divide-y-0">
              <div className="divide-y divide-line">
                <KV k="סיכון לעסקה" v={<N>{r.risk_per_trade_pct}%</N>} sub={<N>{fmtMoney(((o?.equity ?? capital) * r.risk_per_trade_pct) / 100)} ₪</N>} />
                <KV k="סיכון מצטבר" v={<N>{r.max_aggregate_risk_pct}%</N>} />
                <KV k="פוזיציות במקביל" v={<N>{r.max_open_positions}</N>} />
              </div>
              <div className="divide-y divide-line">
                <KV k="הפסד יומי לעצירה" v={<N>{r.daily_loss_pct}%</N>} />
                <KV k="הפסד שבועי לעצירה" v={<N>{r.weekly_loss_pct}%</N>} />
                <KV k="החזקה מרבית" v={<><N>{r.max_hold_hours}</N> שעות</>} />
              </div>
            </div>
          )}
          {risk.error && <p className="text-sm text-loss">{risk.error}</p>}
        </Card>

        <Card title="תקינות מערכת" icon={Activity} flush>
          <ul className="divide-y divide-line">
            {health.map(h => (
              <li key={h.name} className="flex items-center gap-3 px-5 py-3">
                <span className="grid h-8 w-8 place-items-center rounded-lg bg-fg/[0.04] text-muted"><h.icon size={16} /></span>
                <div className="min-w-0 flex-1"><div className="text-sm font-medium">{h.name}</div><div className="truncate text-xs text-muted">{h.desc}</div></div>
                <Badge tone={h.tone} dot>{h.state}</Badge>
              </li>
            ))}
          </ul>
        </Card>
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card title="החלטות אחרונות" icon={GitBranch} flush={!!decisions.data?.items.length}>
          {decisions.data?.items.length ? (
            <ul className="divide-y divide-line">
              {decisions.data.items.map(d => (
                <li key={d.ts + d.symbol} className="flex items-start gap-3 px-5 py-3 text-sm">
                  <Badge tone={ACTION_TONE[d.action] ?? 'neutral'}>{d.action}</Badge>
                  <div className="min-w-0 flex-1">
                    <div className="font-medium"><N>{d.symbol}</N> <span className="text-xs font-normal text-muted">ציון <N>{d.score.toFixed(2)}</N></span></div>
                    <div className="truncate text-xs text-muted" dir="auto">{d.reasons[0] ?? d.blockers[0] ?? '—'}</div>
                  </div>
                  <N className="whitespace-nowrap text-xs text-muted">{fmtTime(d.ts)}</N>
                </li>
              ))}
            </ul>
          ) : <Empty compact icon={Inbox} title="אין החלטות מסחר" text="מנוע ההחלטות רושם כאן כל BUY / SELL / HOLD / NO_TRADE עם הנימוק, אחרי הפעלת המסחר האוטומטי." />}
        </Card>
        <Card title="התראות ואירועים" icon={Bell} flush={!!alerts.data?.items.length}>
          {alerts.data?.items.length ? (
            <ul className="divide-y divide-line">
              {alerts.data.items.map(a => (
                <li key={a.ts + a.message} className="flex items-start gap-3 px-5 py-3 text-sm">
                  <Badge tone={SEV_TONE[a.severity] ?? 'neutral'} dot>{a.severity}</Badge>
                  <div className="min-w-0 flex-1" dir="auto">{a.message}</div>
                  <N className="whitespace-nowrap text-xs text-muted">{fmtTime(a.ts)}</N>
                </li>
              ))}
            </ul>
          ) : <Empty compact icon={Bell} title="אין התראות" text="פתיחה וסגירת עסקאות, עצירות חירום ותקלות יופיעו כאן." />}
        </Card>
      </div>
    </div>
  )
}
