import { useEffect, useState } from 'react'
import { NavLink, Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { BarChart3, CandlestickChart, FlaskConical, LayoutDashboard, Menu, Moon, Newspaper, Receipt, Settings as Cog, ShieldCheck, Sun, X } from 'lucide-react'
import Dashboard from './pages/Dashboard'
import Markets from './pages/Markets'
import Trades from './pages/Trades'
import Strategies from './pages/Strategies'
import InfoCenter from './pages/InfoCenter'
import Settings from './pages/Settings'
import { type Status } from './api'
import { StatusCtx, useApi } from './hooks'
import { useTheme } from './theme'
import { Badge, StatusDot, cx } from './ui'

const GROUPS = [
  { title: 'מסחר', items: [
    { to: '/', label: 'לוח בקרה', icon: LayoutDashboard },
    { to: '/markets', label: 'שווקים וניתוחים', icon: BarChart3 },
    { to: '/trades', label: 'עסקאות', icon: Receipt },
  ] },
  { title: 'מחקר', items: [
    { to: '/strategies', label: 'אסטרטגיות ומעבדה', icon: FlaskConical },
    { to: '/info', label: 'מרכז מידע ו-AI', icon: Newspaper },
  ] },
  { title: 'ניהול', items: [{ to: '/settings', label: 'הגדרות מערכת', icon: Cog }] },
]

const META: Record<string, [string, string]> = {
  '/': ['לוח בקרה', 'מצב החשבון, הסיכון והמערכת'],
  '/markets': ['שווקים וניתוחים', 'גרפים, ניתוח טכני, חדשות ונגידים לכל נכס'],
  '/trades': ['עסקאות', 'פוזיציות פתוחות, היסטוריה והוראות'],
  '/strategies': ['אסטרטגיות ומעבדת ניסויים', 'בדיקות היסטוריות, גרסאות ואופטימיזציה'],
  '/info': ['מרכז מידע ו-AI', 'מקורות, חדשות, בנקים מרכזיים ובדיקת תחזיות'],
  '/settings': ['הגדרות מערכת', 'תצורה מגורסאת עם יומן ביקורת'],
}

const SYS: Record<string, [string, 'profit' | 'warn' | 'loss']> = {
  ACTIVE: ['פעיל', 'profit'], PAUSED: ['מושהה', 'warn'], FAULT: ['תקלה', 'loss'], EMERGENCY_STOP: ['עצירת חירום', 'loss'],
}

function Clock() {
  const [now, setNow] = useState(() => new Date())
  useEffect(() => { const t = setInterval(() => setNow(new Date()), 1000); return () => clearInterval(t) }, [])
  const f = (tz?: string) => now.toLocaleTimeString('he-IL', { hour: '2-digit', minute: '2-digit', second: '2-digit', timeZone: tz, hour12: false })
  return (
    <div className="hidden items-center gap-3 rounded-xl border border-line bg-surface2 px-3 py-1.5 text-xs md:flex">
      <span className="text-muted">ירושלים</span><span dir="ltr" className="num font-medium">{f('Asia/Jerusalem')}</span>
      <span className="h-3 w-px bg-line" />
      <span className="text-muted">UTC</span><span dir="ltr" className="num font-medium">{f('UTC')}</span>
    </div>
  )
}

export default function App() {
  const { dark, toggle } = useTheme()
  const [open, setOpen] = useState(false)
  const loc = useLocation()
  const st = useApi<Status>('/api/status', 10_000)
  useEffect(() => setOpen(false), [loc.pathname])
  const [title, desc] = META[loc.pathname] ?? ['', '']
  const sys = SYS[st.data?.system ?? ''] ?? ['לא ידוע', 'loss']
  const dbOk = st.data?.database === 'connected'

  return (
    <StatusCtx.Provider value={{ status: st.data, error: st.error }}>
      <div className="min-h-screen overflow-x-clip lg:flex">
        {open && <div className="fixed inset-0 z-30 bg-black/50 backdrop-blur-sm lg:hidden" onClick={() => setOpen(false)} />}

        <aside className={cx('fixed inset-y-0 start-0 z-40 flex w-[264px] shrink-0 flex-col border-e border-line bg-surface transition-transform duration-200 lg:sticky lg:top-0 lg:h-screen lg:translate-x-0',
          open ? 'translate-x-0' : 'translate-x-full')}>
          <div className="flex items-center gap-3 px-5 pb-4 pt-5">
            <div className="grid h-10 w-10 place-items-center rounded-xl bg-gradient-to-br from-accent to-indigo-600 text-white shadow-lg shadow-accent/20">
              <CandlestickChart size={20} />
            </div>
            <div className="min-w-0">
              <div className="font-bold tracking-tight">Broiner Trade</div>
              <div className="text-xs text-muted">פלטפורמת מסחר אלגוריתמי</div>
            </div>
            <button className="ms-auto rounded-lg p-1 text-muted hover:bg-fg/5 lg:hidden" onClick={() => setOpen(false)} aria-label="סגור"><X size={18} /></button>
          </div>

          <nav className="flex-1 space-y-5 overflow-y-auto px-3 py-2">
            {GROUPS.map(g => (
              <div key={g.title}>
                <div className="mb-1.5 px-3 text-[11px] font-semibold uppercase tracking-wider text-muted/80">{g.title}</div>
                <div className="space-y-0.5">
                  {g.items.map(({ to, label, icon: Icon }) => (
                    <NavLink key={to} to={to} end={to === '/'} className={({ isActive }) => cx(
                      'group relative flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition',
                      isActive ? 'bg-accent/10 text-accent' : 'text-fg/70 hover:bg-fg/[0.04] hover:text-fg')}>
                      {({ isActive }) => <>
                        {isActive && <span className="absolute inset-y-2 start-0 w-[3px] rounded-full bg-accent" />}
                        <Icon size={18} className={isActive ? '' : 'text-muted group-hover:text-fg'} />{label}
                      </>}
                    </NavLink>
                  ))}
                </div>
              </div>
            ))}
          </nav>

          <div className="m-3 rounded-2xl border border-profit/25 bg-profit/[0.06] p-3.5">
            <div className="flex items-center gap-2 text-sm font-semibold text-profit"><ShieldCheck size={16} />סביבת דמו</div>
            <p className="mt-1 text-xs leading-relaxed text-fg/70">PaperBroker בלבד. מסחר חי חסום ודורש אישור מנהל נפרד.</p>
          </div>
        </aside>

        <div className="min-w-0 flex-1">
          <header className="sticky top-0 z-20 border-b border-line bg-bg/80 backdrop-blur-xl">
            <div className="mx-auto flex max-w-[1440px] items-center gap-3 px-4 py-3 lg:px-8">
              <button className="rounded-lg p-1.5 text-muted hover:bg-fg/5 lg:hidden" onClick={() => setOpen(true)} aria-label="תפריט"><Menu size={20} /></button>
              <div className="min-w-0 flex-1">
                <h1 className="truncate text-lg font-bold tracking-tight">{title}</h1>
                <p className="hidden truncate text-xs text-muted sm:block">{desc}</p>
              </div>
              <div className="hidden items-center gap-2 sm:flex">
                <Badge tone="accent" dot>PAPER</Badge>
                <Badge tone={sys[1]} dot>{sys[0]}</Badge>
                <span className="flex items-center gap-1.5 rounded-full px-2 text-xs text-muted" title="מסד נתונים">
                  <StatusDot tone={st.error ? 'loss' : dbOk ? 'profit' : 'loss'} pulse={dbOk && !st.error} />DB
                </span>
              </div>
              <Clock />
              <button onClick={toggle} className="grid h-9 w-9 place-items-center rounded-xl border border-line bg-surface text-muted transition hover:text-fg" aria-label="החלפת ערכת צבע">
                {dark ? <Sun size={16} /> : <Moon size={16} />}
              </button>
            </div>
          </header>

          <main className="mx-auto max-w-[1440px] space-y-6 p-4 lg:p-8">
            {st.error && !st.data && (
              <div className="rounded-2xl border border-loss/30 bg-loss/[0.06] px-4 py-3 text-sm">
                <b className="text-loss">אין חיבור לשרת ה-API.</b> הפעל: <span dir="ltr" className="num">uvicorn app.main:app --port 8000</span>
              </div>
            )}
            <Routes>
              <Route path="/" element={<Dashboard />} />
              <Route path="/markets" element={<Markets />} />
              <Route path="/trades" element={<Trades />} />
              <Route path="/strategies" element={<Strategies />} />
              <Route path="/info" element={<InfoCenter />} />
              <Route path="/settings" element={<Settings />} />
              <Route path="*" element={<Navigate to="/" />} />
            </Routes>
          </main>
        </div>
      </div>
    </StatusCtx.Provider>
  )
}
