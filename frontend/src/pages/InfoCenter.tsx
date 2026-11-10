import { useState } from 'react'
import { Brain, CalendarClock, Database, ExternalLink, Globe, Landmark, LineChart, Newspaper, Rss, Target } from 'lucide-react'
import { Badge, Banner, Card, Empty, KV, N, Tabs, type Tone } from '../ui'
import { useApi } from '../hooks'

type TabKey = 'sources' | 'news' | 'macro' | 'eval'

interface Src { name: string; kind: string; url: string | null; poll_seconds: number; enabled: boolean; status: string; last_success_at: string | null; last_run: { received: number; new: number; error: string | null } | null }
interface Article { title: string; url: string; source: string; published_at: string; discovered_at: string; currencies: string[] }
interface BankEvent { bank: string; kind: string; title: string; url: string | null; event_time: string; available_at: string }

/** Connectors not built yet (FRED needs a key; no public Bank of Israel feed was found). */
const PLANNED = [
  { name: 'בנק ישראל', kind: 'בנק מרכזי', icon: Landmark, url: 'boi.org.il', freq: 'טרם נמצא פיד ציבורי' },
  { name: 'FRED', kind: 'נתוני מאקרו (עם Vintages)', icon: Database, url: 'api.stlouisfed.org', freq: 'דורש מפתח API' },
]

const KIND = { market: ['מחירי שוק', LineChart], news: ['חדשות', Rss], central_bank: ['בנק מרכזי', Landmark], macro: ['מאקרו', Database] } as const
const STATUS: Record<string, [string, Tone]> = {
  connected: ['מחובר', 'profit'], stale: ['לא מתעדכן', 'warn'], error: ['שגיאה', 'loss'], starting: ['מתחבר', 'warn'],
}
const BANK_NAMES: Record<string, string> = { FED: 'Fed', ECB: 'ECB', BOE: 'BoE', BOI: 'בנק ישראל' }
const EVENT_KINDS: Record<string, string> = { rate_decision: 'החלטת ריבית', speech: 'נאום', minutes: 'פרוטוקול', projection: 'תחזית', press: 'הודעה' }

const fmtTime = (iso: string) => new Date(iso).toLocaleString('he-IL', { dateStyle: 'short', timeStyle: 'short' })

function Link({ href, children }: { href: string | null; children: React.ReactNode }) {
  return href ? <a href={href} target="_blank" rel="noreferrer noopener" className="hover:text-accent hover:underline">{children}</a> : <>{children}</>
}

export default function InfoCenter() {
  const [tab, setTab] = useState<TabKey>('sources')
  const src = useApi<{ items: Src[] }>('/api/sources', 30_000)
  const news = useApi<{ items: Article[]; total: number }>('/api/news?limit=150', 60_000)
  const bank = useApi<{ items: BankEvent[] }>('/api/central-bank?limit=80', 60_000)
  const sources = src.data?.items ?? []
  const live = sources.filter(s => s.status === 'connected').length
  return (
    <div className="space-y-6">
      <Tabs value={tab} onChange={setTab} tabs={[
        { value: 'sources', label: 'מקורות מידע', icon: Database, count: sources.length + PLANNED.length },
        { value: 'news', label: 'מרכז חדשות', icon: Newspaper, count: news.data?.total ?? 0 },
        { value: 'macro', label: 'נגידים ומאקרו', icon: Landmark, count: bank.data?.items.length ?? 0 },
        { value: 'eval', label: 'בדיקת תחזיות AI', icon: Target },
      ]} />

      {tab === 'sources' && <>
        {src.error && <Banner tone="loss" icon={Database} title="שגיאה בטעינת מקורות">{src.error}</Banner>}
        <Banner tone={live ? 'info' : 'warn'} icon={Database} title={`${live} מתוך ${sources.length} מקורות פעילים`}>
          כל המקורות הם ציבוריים וללא מפתח. ניתוח AI של הידיעות עדיין לא מחובר — הידיעות נאספות ונשמרות בלבד, ואינן משפיעות על החלטות מסחר.
        </Banner>
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          {sources.map(s => {
            const [kindLabel, Icon] = KIND[s.kind as keyof typeof KIND] ?? [s.kind, Globe]
            const [stLabel, stTone] = STATUS[s.status] ?? [s.status, 'neutral' as Tone]
            return (
              <div key={s.name} className="rounded-2xl border border-line bg-surface p-4 shadow-card">
                <div className="flex items-start gap-3">
                  <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-fg/[0.05] text-muted"><Icon size={18} /></span>
                  <div className="min-w-0 flex-1"><div className="truncate font-semibold">{s.name}</div><div className="truncate text-xs text-muted">{kindLabel}</div></div>
                  <Badge tone={stTone} dot>{stLabel}</Badge>
                </div>
                <div className="mt-3 divide-y divide-line border-t border-line text-xs">
                  <KV k="כתובת" v={<N className="truncate text-xs">{s.url?.replace(/^https?:\/\//, '').split('/')[0] ?? '—'}</N>} />
                  <KV k="תדירות" v={s.poll_seconds >= 60 ? `${Math.round(s.poll_seconds / 60)} דק׳` : `${s.poll_seconds} שנ׳`} />
                  <KV k="עדכון אחרון" v={<N>{s.last_success_at ? fmtTime(s.last_success_at) : '—'}</N>} />
                  <KV k="פריטים חדשים / שגיאה" v={<N>{s.last_run ? `${s.last_run.new} / ${s.last_run.received}` : '—'}</N>} sub={s.last_run?.error ?? undefined} />
                </div>
              </div>
            )
          })}
          {PLANNED.map(s => (
            <div key={s.name} className="rounded-2xl border border-dashed border-line bg-surface p-4 opacity-70">
              <div className="flex items-start gap-3">
                <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-fg/[0.05] text-muted"><s.icon size={18} /></span>
                <div className="min-w-0 flex-1"><div className="truncate font-semibold">{s.name}</div><div className="truncate text-xs text-muted">{s.kind}</div></div>
                <Badge tone="loss" dot>לא מחובר</Badge>
              </div>
              <div className="mt-3 divide-y divide-line border-t border-line text-xs">
                <KV k="כתובת" v={<N className="text-xs">{s.url}</N>} />
                <KV k="הערה" v={s.freq} />
              </div>
            </div>
          ))}
        </div>
      </>}

      {tab === 'news' && (
        <Card flush>
          {news.data?.items.length ? (
            <div className="overflow-x-auto">
              <table className="tbl">
                <thead><tr>{['כותרת', 'מקור', 'פורסם', 'זוהה במערכת', 'מטבעות'].map(h => <th key={h}>{h}</th>)}</tr></thead>
                <tbody>{news.data.items.map(a => (
                  <tr key={a.url}>
                    <td className="max-w-xl" dir="auto"><Link href={a.url}>{a.title}</Link></td>
                    <td className="whitespace-nowrap text-muted">{a.source}</td>
                    <td className="whitespace-nowrap"><N>{fmtTime(a.published_at)}</N></td>
                    <td className="whitespace-nowrap"><N>{fmtTime(a.discovered_at)}</N></td>
                    <td>{a.currencies.length ? <div className="flex gap-1">{a.currencies.map(c => <Badge key={c} tone="accent">{c}</Badge>)}</div> : '—'}</td>
                  </tr>
                ))}</tbody>
              </table>
            </div>
          ) : <Empty icon={Newspaper} title={news.loading ? 'טוען…' : 'לא נאספו ידיעות'} text="ידיעות נשמרות עם זמן פרסום וזמן גילוי נפרדים, כפילויות מסוננות, ונשמרים כותרת וקישור בלבד. תיוג המטבעות נעשה לפי מילות מפתח בכותרת, לא לפי ניתוח AI." />}
        </Card>
      )}

      {tab === 'macro' && (
        <div className="grid gap-6 lg:grid-cols-2">
          <Card title="החלטות והודעות" icon={Landmark} flush={!!bank.data?.items.length}>
            {bank.data?.items.length ? (
              <div className="divide-y divide-line">{bank.data.items.map(e => (
                <div key={e.bank + e.event_time + e.title} className="flex items-start gap-3 px-4 py-3 text-sm">
                  <Badge tone="accent">{BANK_NAMES[e.bank] ?? e.bank}</Badge>
                  <div className="min-w-0 flex-1"><div dir="auto"><Link href={e.url}>{e.title}</Link></div>
                    <div className="mt-0.5 text-xs text-muted">{EVENT_KINDS[e.kind] ?? e.kind} · <N>{fmtTime(e.event_time)}</N></div></div>
                </div>
              ))}</div>
            ) : <Empty compact icon={Landmark} title={bank.loading ? 'טוען…' : 'אין פרסומים'} text="הודעות Fed, ECB ו-BoE מפידים ציבוריים: כותרת, קישור, זמן פרסום וזמן קליטה." />}
          </Card>
          <Card title="יומן אירועים קרובים" icon={CalendarClock}><Empty compact icon={CalendarClock} title="אין אירועים מתוזמנים" text="החלטות ריבית ופרסומי מאקרו קרובים. חלונות הימנעות ממסחר יחושבו מהם." /></Card>
          <Card title="נתוני מאקרו" icon={LineChart} className="lg:col-span-2"><Empty compact icon={LineChart} title="אין סדרות" text="אינפלציה, תעסוקה וריבית — כל תיקון בדיעבד נשמר כ-Vintage נפרד כדי שה-Backtest ישתמש בנתון שהיה ידוע באותו זמן. תחזית מול בפועל רק ממקור אמין." /></Card>
        </div>
      )}

      {tab === 'eval' && (
        <Card title="בדיקת תחזיות AI" icon={Brain} actions={<a className="flex items-center gap-1 text-xs text-muted"><ExternalLink size={12} />מתודולוגיה</a>}>
          <Empty icon={Target} title="אין עדיין תחזיות להערכה"
            text="לכל ניתוח יישמרו הכיוון החזוי ואופק הזמן. בתום האופק תחושב תנועת המחיר בפועל. המסך יבדיל בין ״תנועה בכיוון החזוי״ לבין תרומה אמיתית לביצועי אסטרטגיה, וציון הביטחון של המודל לא יוצג כהסתברות לפני כיול." />
        </Card>
      )}
    </div>
  )
}
