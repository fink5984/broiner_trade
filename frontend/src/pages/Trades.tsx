import { useState } from 'react'
import { CheckCircle2, Clock, Download, Filter, Layers, Receipt, XCircle } from 'lucide-react'
import { fmtMoney, priceDigits, type TradeRow } from '../api'
import { useApi } from '../hooks'
import { Badge, Button, Card, Empty, N, Select, Tabs } from '../ui'

type TabKey = 'open' | 'closed' | 'pending' | 'failed'

const COLS: Record<TabKey, string[]> = {
  open: ['מס׳', 'נכס', 'כיוון', 'אסטרטגיה', 'זמן כניסה', 'מחיר כניסה', 'גודל', 'Stop Loss', 'Take Profit', 'מחיר נוכחי', 'התקדמות ליעד', 'רו״ה לא ממומש', 'פעולות'],
  closed: ['מס׳', 'נכס', 'כיוון', 'אסטרטגיה', 'כניסה', 'מחיר כניסה', 'גודל', 'יציאה', 'מחיר יציאה', 'עמלות ו-Spread', 'רו״ה נטו', 'סיבת יציאה'],
  pending: ['מזהה הוראה', 'נכס', 'כיוון', 'סוג', 'מחיר', 'גודל', 'נוצרה', 'סטטוס'],
  failed: ['מזהה הוראה', 'נכס', 'כיוון', 'גודל', 'זמן', 'סטטוס', 'סיבה'],
}
const EMPTY: Record<TabKey, [string, string]> = {
  open: ['אין פוזיציות פתוחות', 'פוזיציות שייפתחו במסחר הדמו יוצגו כאן עם Stop Loss, Take Profit ורו״ה בזמן אמת, ואפשרות סגירה ידנית באישור.'],
  closed: ['אין עסקאות סגורות', 'לכל עסקה יישמרו גרסת האסטרטגיה והפרומפט, מצב שלושת המנועים בעת הכניסה, הוראות הברוקר וכל אירוע בחייה.'],
  pending: ['אין הוראות ממתינות', 'הוראות כניסה ממתינות מבוטלות אוטומטית בעת חריגה ממגבלת סיכון או עצירת חירום.'],
  failed: ['אין הוראות שנכשלו', 'הוראות שנדחו על ידי הברוקר או בוטלו יתועדו כאן עם הסיבה המלאה.'],
}

const fmtTime = (iso: string | null) => iso ? new Date(iso).toLocaleString('he-IL', { dateStyle: 'short', timeStyle: 'short' }) : '—'
const Pnl = ({ v }: { v: number | null }) => v == null ? <N>—</N> : <N className={v > 0 ? 'text-profit' : v < 0 ? 'text-loss' : undefined}>{v > 0 ? '+' : ''}{fmtMoney(v, 2)} ₪</N>
const Side = ({ s }: { s: string }) => <Badge tone={s === 'BUY' ? 'profit' : 'loss'}>{s}</Badge>

/** How far price travelled from entry toward Take Profit (green) or, when against us, toward Stop Loss (red). */
function Progress({ t }: { t: TradeRow }) {
  if (t.current_price == null || t.take_profit == null) return <N>—</N>
  const move = t.current_price - t.entry_price
  const toTp = t.take_profit - t.entry_price
  const toSl = t.stop_loss - t.entry_price
  if (!toTp || !toSl) return <N>—</N>
  const win = move / toTp >= 0                       // moving in the direction of the target
  const pct = Math.max(0, Math.min(100, (win ? move / toTp : move / toSl) * 100))
  const tone = win ? 'bg-profit' : 'bg-loss'
  return (
    <div className="flex min-w-[150px] items-center gap-2" dir="ltr" title={win ? `${pct.toFixed(0)}% מהדרך ל-Take Profit` : `${pct.toFixed(0)}% מהדרך ל-Stop Loss`}>
      <div className="h-2 flex-1 overflow-hidden rounded-full bg-fg/10">
        <div className={`h-full rounded-full transition-all duration-500 ${tone}`} style={{ width: `${pct}%` }} />
      </div>
      <N className={`w-12 text-end text-xs font-medium ${win ? 'text-profit' : 'text-loss'}`}>{win ? '' : '−'}{pct.toFixed(0)}%</N>
    </div>
  )
}

function OpenRow({ t }: { t: TradeRow }) {
  const d = priceDigits(t.symbol)
  return (
    <tr>
      <td><N>{t.number}</N></td><td><N>{t.symbol}</N></td><td><Side s={t.side} /></td><td className="text-muted">{t.strategy}</td>
      <td><N>{fmtTime(t.entry_time)}</N></td><td><N>{t.entry_price.toFixed(d)}</N></td><td><N>{fmtMoney(t.units)}</N></td>
      <td><N>{t.stop_loss.toFixed(d)}</N></td><td><N>{t.take_profit?.toFixed(d) ?? '—'}</N></td>
      <td><N>{t.current_price?.toFixed(d) ?? '—'}</N></td><td><Progress t={t} /></td><td><Pnl v={t.unrealized} /></td><td className="text-muted">—</td>
    </tr>
  )
}

function ClosedRow({ t }: { t: TradeRow }) {
  const d = priceDigits(t.symbol)
  return (
    <tr>
      <td><N>{t.number}</N></td><td><N>{t.symbol}</N></td><td><Side s={t.side} /></td><td className="text-muted">{t.strategy}</td>
      <td><N>{fmtTime(t.entry_time)}</N></td><td><N>{t.entry_price.toFixed(d)}</N></td><td><N>{fmtMoney(t.units)}</N></td>
      <td><N>{fmtTime(t.exit_time)}</N></td><td><N>{t.exit_price?.toFixed(d) ?? '—'}</N></td>
      <td><N>{fmtMoney(t.fees + t.spread_cost, 2)} ₪</N></td><td><Pnl v={t.net_pnl} /></td><td><N className="text-xs">{t.exit_reason ?? '—'}</N></td>
    </tr>
  )
}

export default function Trades() {
  const [tab, setTab] = useState<TabKey>('open')
  const open = useApi<{ items: TradeRow[] }>('/api/trades?status=open', 5_000)
  const closed = useApi<{ items: TradeRow[] }>('/api/trades?status=closed&limit=200', 15_000)
  const rows = tab === 'open' ? open.data?.items : tab === 'closed' ? closed.data?.items : []
  return (
    <Card flush>
      <div className="px-2">
        <Tabs value={tab} onChange={setTab} tabs={[
          { value: 'open', label: 'פתוחות', icon: Layers, count: open.data?.items.length ?? 0 },
          { value: 'closed', label: 'סגורות', icon: CheckCircle2, count: closed.data?.items.length ?? 0 },
          { value: 'pending', label: 'הוראות ממתינות', icon: Clock, count: 0 },
          { value: 'failed', label: 'בוטלו / נכשלו', icon: XCircle, count: 0 },
        ]} />
      </div>
      <div className="flex flex-wrap items-center gap-2 border-b border-line px-5 py-3">
        <Filter size={15} className="text-muted" />
        <Select className="h-9 w-40" defaultValue=""><option value="">כל הנכסים</option></Select>
        <Select className="h-9 w-44" defaultValue=""><option value="">כל האסטרטגיות</option></Select>
        <Select className="h-9 w-36" defaultValue="PAPER"><option value="PAPER">דמו (Paper)</option></Select>
        <Button size="sm" variant="ghost" icon={Download} className="ms-auto" disabled>ייצוא CSV</Button>
      </div>
      <div className="overflow-x-auto">
        <table className="tbl">
          <thead><tr>{COLS[tab].map(h => <th key={h}>{h}</th>)}</tr></thead>
          {!!rows?.length && <tbody>{rows.map(t => tab === 'open' ? <OpenRow key={t.number} t={t} /> : <ClosedRow key={t.number} t={t} />)}</tbody>}
        </table>
      </div>
      {!rows?.length && <Empty icon={Receipt} title={EMPTY[tab][0]} text={EMPTY[tab][1]} />}
    </Card>
  )
}
