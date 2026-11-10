import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Bell,
  Brain,
  Check,
  CircleAlert,
  Database,
  History,
  Landmark,
  Lock,
  RotateCcw,
  Save,
  Scale,
  ServerCog,
  ShieldCheck,
  SlidersHorizontal,
  type LucideIcon
} from 'lucide-react'
import { api, type SettingDoc } from '../api'
import { TokenPrompt, getToken, setToken } from '../auth'
import { Badge, Banner, Button, Card, Empty, Field, Input, N, Select, Switch, Textarea, cx } from '../ui'

type Kind = 'number' | 'text' | 'bool' | 'textarea' | 'select'
type F = { name: string; label: string; hint?: string; kind?: Kind; options?: string[]; step?: number; unit?: string; readOnly?: boolean }
interface Section { key: string; label: string; desc: string; icon: LucideIcon; intro: string; groups: { title: string; fields: F[] }[] }

const SECTIONS: Section[] = [
  { key: 'general', label: 'כלליות', desc: 'אזור זמן, הון ונכס ראשי', icon: SlidersHorizontal,
    intro: 'הגדרות בסיס. כל הזמנים נשמרים ב-UTC ומוצגים לפי אזור הזמן שנבחר. מצב המסחר נעול על דמו.', groups: [
      { title: 'תצוגה', fields: [{ name: 'timezone', label: 'אזור זמן', kind: 'select', options: ['Asia/Jerusalem', 'UTC', 'Europe/London', 'America/New_York'] }] },
      { title: 'חשבון', fields: [
        { name: 'initial_capital', label: 'הון התחלתי', unit: '₪', step: 100, hint: 'ההון המרבי המתוכנן למסחר.' },
        { name: 'account_currency', label: 'מטבע חשבון', kind: 'text', hint: 'מטבע הבסיס לחישובי סיכון ורו״ה.' },
        { name: 'primary_asset', label: 'נכס ראשי', kind: 'text' },
        { name: 'trading_mode', label: 'מצב מסחר', kind: 'text', readOnly: true, hint: 'מעבר למסחר חי דורש תהליך אישור נפרד ואינו אפשרי מכאן.' },
      ] },
    ] },
  { key: 'risk', label: 'ניהול סיכונים', desc: 'מגבלות, Drawdown ועצירת חירום', icon: ShieldCheck,
    intro: 'נאכף על ידי מנוע סיכונים עצמאי שאינו תלוי ב-AI. תקרות קשיחות לא ניתנות לעקיפה, ושינויים נכנסים לתוקף מיידית.', groups: [
      { title: 'סיכון לעסקה ולתיק', fields: [
        { name: 'risk_per_trade_pct', label: 'סיכון לעסקה', unit: '%', step: 0.05, hint: 'הפסד מרבי מתוכנן בעסקה אחת. תקרה 1%.' },
        { name: 'max_aggregate_risk_pct', label: 'סיכון מצטבר', unit: '%', step: 0.05, hint: 'סך הסיכון בכל הפוזיציות. תקרה 3%.' },
        { name: 'max_open_positions', label: 'פוזיציות במקביל', step: 1 },
        { name: 'max_leverage', label: 'מינוף מרבי', unit: '×', step: 0.5, hint: 'חשיפה נומינלית ביחס להון. תקרה 30.' },
        { name: 'max_currency_exposure_pct', label: 'חשיפה למטבע', unit: '%', step: 10 },
      ] },
      { title: 'עצירות הפסד', fields: [
        { name: 'daily_loss_pct', label: 'הפסד יומי', unit: '%', step: 0.1, hint: 'חוסם עסקאות חדשות עד מחר.' },
        { name: 'weekly_loss_pct', label: 'הפסד שבועי', unit: '%', step: 0.1 },
        { name: 'dd_reduce_pct', label: 'Drawdown — הפחתת סיכון', unit: '%', step: 0.5, hint: 'הסיכון לעסקה מופחת בחצי.' },
        { name: 'dd_block_pct', label: 'Drawdown — חסימת עסקאות', unit: '%', step: 0.5, hint: 'חייב להיות ≥ סף ההפחתה.' },
        { name: 'dd_emergency_pct', label: 'Drawdown — עצירת חירום', unit: '%', step: 0.5, hint: 'EMERGENCY_STOP, חזרה באישור ידני. תקרה 20%.' },
      ] },
      { title: 'זמן ונתונים', fields: [
        { name: 'max_hold_hours', label: 'החזקה מרבית', unit: 'שעות', step: 1, hint: 'סגירה אוטומטית לאחר זמן זה. תקרה 72.' },
        { name: 'max_data_age_seconds', label: 'גיל מחיר מרבי', unit: 'שניות', step: 10, hint: 'מחיר ישן יותר חוסם פתיחת עסקה.' },
      ] },
    ] },
  { key: 'decision', label: 'מנוע החלטות', desc: 'משקלים, ספים ווטו', icon: Scale,
    intro: 'שקלול שלושת המנועים. המשקלים חייבים להסתכם ב-100%. ברירת המחדל ניסיונית, וציון ה-AI אינו הסתברות לפני כיול.', groups: [
      { title: 'משקלי מנועים', fields: [
        { name: 'w_technical', label: 'ניתוח טכני', unit: '%', step: 5 },
        { name: 'w_news', label: 'חדשות', unit: '%', step: 5 },
        { name: 'w_macro', label: 'נגידים ומאקרו', unit: '%', step: 5 },
      ] },
      { title: 'תנאי כניסה', fields: [
        { name: 'min_signal', label: 'סף אות מינימלי', step: 0.05, hint: 'ציון משוקלל (0–1) הנדרש לפתיחה.' },
        { name: 'min_agreeing_engines', label: 'מנועים מסכימים', step: 1, hint: 'כמה מנועים חייבים להצביע לאותו כיוון.' },
        { name: 'cooldown_minutes', label: 'קירור לאחר כניסה', unit: 'דקות', step: 5 },
      ] },
      { title: 'וטו', fields: [
        { name: 'veto_news_against', label: 'וטו חדשות', step: 0.05, hint: 'התנגדות בעוצמה זו חוסמת עסקה.' },
        { name: 'veto_macro_against', label: 'וטו נגידים', step: 0.05 },
      ] },
    ] },
  { key: 'ai', label: 'מודלי AI ופרומפטים', desc: 'ספק, מודל, תקציב ופרומפטים', icon: Brain,
    intro: 'כל שינוי יוצר גרסת תצורה חדשה ללא פריסת קוד. שם המודל חייב להילקח מרשימת המודלים הזמינה בפועל אצל הספק (חיבור Gemini טרם הוגדר).', groups: [
      { title: 'מודל', fields: [
        { name: 'provider', label: 'ספק', kind: 'select', options: ['gemini', 'openai'] },
        { name: 'model', label: 'מודל', kind: 'text', hint: 'מודל ברירת המחדל לכל המשימות. אין בחירת מודל לכל עסקה.' },
        { name: 'temperature', label: 'Temperature', step: 0.1 },
        { name: 'max_tokens', label: 'מגבלת טוקנים', step: 128 },
      ] },
      { title: 'תקציב ואמינות', fields: [
        { name: 'daily_budget_usd', label: 'תקציב יומי', unit: '$', step: 0.5 },
        { name: 'monthly_budget_usd', label: 'תקציב חודשי', unit: '$', step: 1 },
        { name: 'timeout_seconds', label: 'Timeout', unit: 'שניות', step: 5 },
        { name: 'max_retries', label: 'ניסיונות חוזרים', step: 1 },
      ] },
      { title: 'פרומפטים', fields: [
        { name: 'system_prompt', label: 'פרומפט מערכת', kind: 'textarea', hint: 'תוכן כתבות מועבר תמיד כמידע חיצוני בלתי מהימן.' },
        { name: 'news_prompt', label: 'פרומפט חדשות', kind: 'textarea', hint: 'הפלט חייב להיות JSON שעובר אימות Pydantic.' },
        { name: 'central_bank_prompt', label: 'פרומפט נגידים', kind: 'textarea', hint: 'אין להמציא ציפיות שוק חסרות.' },
      ] },
    ] },
  { key: 'alerts', label: 'התראות', desc: 'ערוצים ואירועים', icon: Bell,
    intro: 'שליחת מייל דורשת הגדרת שרת SMTP בקובץ ‎.env (טרם הוגדר). Telegram ייתמך בהמשך.', groups: [
      { title: 'ערוץ מייל', fields: [{ name: 'email_enabled', label: 'שליחת התראות במייל', kind: 'bool' }, { name: 'email_to', label: 'כתובת נמען', kind: 'text' }] },
      { title: 'אירועים', fields: [
        { name: 'on_trade_open', label: 'פתיחת עסקה', kind: 'bool' }, { name: 'on_trade_close', label: 'סגירת עסקה', kind: 'bool' },
        { name: 'on_emergency_stop', label: 'עצירת חירום', kind: 'bool' }, { name: 'on_broker_disconnect', label: 'ניתוק ברוקר', kind: 'bool' },
        { name: 'on_data_source_down', label: 'מקור נתונים לא זמין', kind: 'bool' }, { name: 'on_ai_budget', label: 'חריגה מתקציב AI', kind: 'bool' },
      ] },
    ] },
]

const PENDING: { key: string; label: string; icon: LucideIcon; text: string }[] = [
  { key: 'brokers', label: 'ברוקרים וחיבורי מסחר', icon: Landmark, text: 'PaperBroker קיים בקוד. אין חיבור לברוקר חי; הוא חסום כברירת מחדל ויחייב אימות הרשאות, בדיקות בטיחות ואישור מנהל נפרד.' },
  { key: 'sources', label: 'מקורות מידע', icon: Database, text: 'הגדרת מחברי GDELT, RSS, בנקים מרכזיים ו-FRED ותדירות האיסוף תתווסף יחד עם המחברים עצמם.' },
  { key: 'security', label: 'אבטחה ומשתמשים', icon: Lock, text: 'התחברות, 2FA ו-RBAC טרם נבנו. בינתיים שמירת הגדרות מוגנת בטוקן מנהל. אין לחשוף את המערכת לרשת לפני שייבנו.' },
  { key: 'system', label: 'מערכת ולוגים', icon: ServerCog, text: 'מציג לוגים עם סינון לפי שירות, זמן, חומרה ומזהה עסקה ייבנה עם שירותי הרקע.' },
]

type Hist = { version: number; value: Record<string, unknown>; at: string; current: boolean }

function FieldInput({ f, value, onChange }: { f: F; value: unknown; onChange: (v: unknown) => void }) {
  if (f.kind === 'bool') return null
  if (f.kind === 'textarea') return <Textarea dir="ltr" rows={3} value={String(value ?? '')} onChange={e => onChange(e.target.value)} />
  if (f.kind === 'select') return <Select dir="ltr" value={String(value)} onChange={e => onChange(e.target.value)}>{f.options!.map(o => <option key={o}>{o}</option>)}</Select>
  return <Input dir="ltr" disabled={f.readOnly} type={f.kind === 'text' ? 'text' : 'number'} step={f.step ?? 'any'} value={String(value ?? '')}
    onChange={e => onChange(f.kind === 'text' ? e.target.value : e.target.value === '' ? '' : Number(e.target.value))} />
}

function SettingsForm({ s }: { s: Section }) {
  const [cur, setCur] = useState<SettingDoc | null>(null)
  const [draft, setDraft] = useState<Record<string, unknown>>({})
  const [hist, setHist] = useState<Hist[]>([])
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null)
  const [busy, setBusy] = useState(false)
  const [ask, setAsk] = useState(false)

  const load = useCallback(async () => {
    try {
      const c = await api<SettingDoc>('/api/settings/' + s.key)
      setCur(c); setDraft(c.value)
      setHist(await api<Hist[]>('/api/settings/' + s.key + '/history'))
    } catch (e) { setMsg({ ok: false, text: (e as Error).message }) }
  }, [s.key])
  useEffect(() => { setMsg(null); setCur(null); load() }, [load])

  const dirty = cur ? JSON.stringify(draft) !== JSON.stringify(cur.value) : false
  const changedKeys = useMemo(() => cur ? Object.keys(draft).filter(k => JSON.stringify(draft[k]) !== JSON.stringify(cur.value[k])) : [], [draft, cur])
  const sumW = s.key === 'decision' ? ['w_technical', 'w_news', 'w_macro'].reduce((a, k) => a + Number(draft[k] ?? 0), 0) : null

  const save = async (token?: string) => {
    const t = token ?? getToken()
    if (!t) { setAsk(true); return }
    setBusy(true); setMsg(null)
    try {
      const r = await api<SettingDoc & { effective?: string; unchanged?: boolean }>('/api/settings/' + s.key, { method: 'PUT', body: draft, token: t })
      setToken(t)
      setMsg({ ok: true, text: `נשמר כגרסה ${r.version} · תוקף ${r.effective === 'immediate' ? 'מיידי' : 'מהמחזור הבא'}` })
      await load()
    } catch (e) {
      const err = e as Error & { status?: number }
      if (err.status === 401) { setToken(null); setAsk(true) }
      setMsg({ ok: false, text: err.message })
    } finally { setBusy(false) }
  }

  if (!cur) return <Card><div className="py-10 text-center text-sm text-muted">{msg ? <span className="text-loss">{msg.text}</span> : 'טוען הגדרות…'}</div></Card>

  return (
    <div className="space-y-6">
      {ask && <TokenPrompt onCancel={() => setAsk(false)} onDone={t => { setAsk(false); save(t) }} />}
      <Card title={s.label} subtitle={s.intro} icon={s.icon}
        actions={<Badge tone={cur.is_default ? 'neutral' : 'accent'}>{cur.is_default ? 'ברירת מחדל' : <>גרסה <N>{cur.version}</N></>}</Badge>}
        footer={
          <div className="flex flex-wrap items-center gap-3">
            <Button variant="primary" icon={Save} disabled={!dirty || busy || (sumW !== null && sumW !== 100)} onClick={() => save()}>{busy ? 'שומר…' : 'שמור גרסה חדשה'}</Button>
            <Button variant="ghost" icon={RotateCcw} disabled={!dirty || busy} onClick={() => { setDraft(cur.value); setMsg(null) }}>בטל שינויים</Button>
            {dirty && !msg && <span className="text-xs text-muted"><N>{changedKeys.length}</N> שדות שונו</span>}
            {msg && <span className={cx('flex items-center gap-1.5 text-sm', msg.ok ? 'text-profit' : 'text-loss')}>{msg.ok ? <Check size={15} /> : <CircleAlert size={15} />}{msg.text}</span>}
          </div>}>
        <div className="space-y-8">
          {s.groups.map(g => (
            <fieldset key={g.title}>
              <legend className="mb-4 text-xs font-semibold uppercase tracking-wider text-muted">{g.title}</legend>
              {g.fields.every(f => f.kind === 'bool') ? (
                <div className="divide-y divide-line rounded-xl border border-line">
                  {g.fields.map(f => (
                    <div key={f.name} className="flex items-center justify-between gap-4 px-4 py-3">
                      <span className={cx('text-sm', changedKeys.includes(f.name) && 'font-semibold text-accent')}>{f.label}</span>
                      <Switch label={f.label} checked={!!draft[f.name]} onChange={v => setDraft({ ...draft, [f.name]: v })} />
                    </div>
                  ))}
                </div>
              ) : (
                <div className={cx('grid gap-x-5 gap-y-5', g.fields.some(f => f.kind === 'textarea') ? 'grid-cols-1' : 'sm:grid-cols-2 xl:grid-cols-3')}>
                  {g.fields.map(f => f.kind === 'bool' ? (
                    <div key={f.name} className="flex items-center justify-between rounded-xl border border-line px-4 py-3"><span className="text-sm">{f.label}</span>
                      <Switch label={f.label} checked={!!draft[f.name]} onChange={v => setDraft({ ...draft, [f.name]: v })} /></div>
                  ) : (
                    <Field key={f.name} label={f.label} unit={f.unit} hint={f.hint} className={cx(changedKeys.includes(f.name) && '[&_.input]:border-accent [&_.input]:ring-4 [&_.input]:ring-accent/10')}>
                      <FieldInput f={f} value={draft[f.name]} onChange={v => setDraft({ ...draft, [f.name]: v })} />
                    </Field>
                  ))}
                </div>
              )}
              {g.title === 'משקלי מנועים' && sumW !== null && (
                <div className="mt-4">
                  <div dir="ltr" className="flex h-2.5 overflow-hidden rounded-full bg-fg/[0.06]">
                    <div className="bg-accent" style={{ width: `${Math.min(100, Number(draft.w_technical))}%` }} />
                    <div className="bg-info" style={{ width: `${Math.min(100, Number(draft.w_news))}%` }} />
                    <div className="bg-warn" style={{ width: `${Math.min(100, Number(draft.w_macro))}%` }} />
                  </div>
                  <div className="mt-2 flex flex-wrap items-center gap-x-5 gap-y-1 text-xs">
                    <span className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-full bg-accent" />טכני</span>
                    <span className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-full bg-info" />חדשות</span>
                    <span className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-full bg-warn" />נגידים</span>
                    <span className={cx('ms-auto flex items-center gap-1 font-semibold', sumW === 100 ? 'text-profit' : 'text-loss')}>
                      {sumW === 100 ? <Check size={14} /> : <CircleAlert size={14} />}סה״כ <N>{sumW}%</N>{sumW !== 100 && ' — חייב להיות 100%'}
                    </span>
                  </div>
                </div>
              )}
            </fieldset>
          ))}
        </div>
      </Card>

      <Card title="היסטוריית גרסאות" subtitle="כל שינוי נרשם גם ביומן הביקורת · גרסאות קודמות לא נמחקות" icon={History} flush>
        {hist.length === 0 ? <Empty compact icon={History} title="עדיין לא נשמרו גרסאות" text="המערכת פועלת כרגע לפי ברירות המחדל שבקוד." /> : (
          <div className="overflow-x-auto">
            <table className="tbl">
              <thead><tr><th>גרסה</th><th>תאריך</th><th>שינויים (קודם ← חדש)</th></tr></thead>
              <tbody>
                {hist.map((h, i) => {
                  const prev = hist[i + 1]?.value
                  const keys = prev ? Object.keys(h.value).filter(k => JSON.stringify(h.value[k]) !== JSON.stringify(prev[k])) : []
                  return (
                    <tr key={h.version}>
                      <td><span className="flex items-center gap-2"><N className="font-semibold">v{h.version}</N>{h.current && <Badge tone="profit">נוכחית</Badge>}</span></td>
                      <td><N className="text-xs text-muted">{new Date(h.at).toLocaleString('he-IL')}</N></td>
                      <td className="!whitespace-normal">
                        {!prev ? <span className="text-xs text-muted">גרסה ראשונה</span> : (
                          <div className="flex flex-wrap gap-1.5">
                            {keys.map(k => (
                              <span key={k} dir="ltr" className="num rounded-lg bg-fg/[0.04] px-2 py-1 text-[11px]">
                                {k}: <span className="text-loss line-through decoration-loss/50">{JSON.stringify(prev[k]).slice(0, 40)}</span> → <span className="text-profit">{JSON.stringify(h.value[k]).slice(0, 40)}</span>
                              </span>
                            ))}
                          </div>
                        )}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  )
}

export default function Settings() {
  const [sel, setSel] = useState('general')
  const s = SECTIONS.find(x => x.key === sel)
  const p = PENDING.find(x => x.key === sel)
  const item = (key: string, label: string, Icon: LucideIcon, desc?: string, pending?: boolean) => (
    <button key={key} onClick={() => setSel(key)} className={cx('relative flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-start transition',
      sel === key ? 'bg-accent/10 text-accent' : 'hover:bg-fg/[0.04]', pending && sel !== key && 'text-muted')}>
      <Icon size={17} className="shrink-0" />
      <span className="min-w-0 flex-1"><span className="block truncate text-sm font-medium">{label}</span>{desc && <span className={cx('block truncate text-xs', sel === key ? 'text-accent/70' : 'text-muted')}>{desc}</span>}</span>
    </button>
  )
  return (
    <div className="space-y-6">
      <Banner tone="profit" icon={Database} title="נשמר במסד הנתונים">
        כל לשונית עם טופס נשמרת ב-PostgreSQL כגרסה חדשה, עם אימות בצד השרת ויומן ביקורת. שינויים לא דורסים היסטוריה.
      </Banner>
      <div className="grid gap-6 lg:grid-cols-[260px_1fr]">
        <nav className="space-y-4 lg:sticky lg:top-24 lg:self-start">
          <div className="rounded-2xl border border-line bg-surface p-2 shadow-card">{SECTIONS.map(x => item(x.key, x.label, x.icon, x.desc))}</div>
          <div className="rounded-2xl border border-dashed border-line p-2">
            <div className="px-3 pb-1 pt-2 text-[11px] font-semibold uppercase tracking-wider text-muted">טרם פעיל</div>
            {PENDING.map(x => item(x.key, x.label, x.icon, undefined, true))}
          </div>
        </nav>
        <div className="min-w-0">
          {s && <SettingsForm key={s.key} s={s} />}
          {p && <Card title={p.label} icon={p.icon} actions={<Badge tone="warn" dot>טרם נבנה</Badge>}><Empty icon={p.icon} title="הלשונית עדיין לא פעילה" text={p.text} /></Card>}
        </div>
      </div>
    </div>
  )
}
