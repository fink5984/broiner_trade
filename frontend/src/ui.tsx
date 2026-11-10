/* In-house UI kit. Every component reads design tokens from index.css (no third-party component library). */
import { useId, type ButtonHTMLAttributes, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes, type TextareaHTMLAttributes } from 'react'
import type { LucideIcon } from 'lucide-react'

export type Tone = 'neutral' | 'accent' | 'profit' | 'loss' | 'warn' | 'info'
export const cx = (...a: (string | false | null | undefined)[]) => a.filter(Boolean).join(' ')

const TEXT: Record<Tone, string> = { neutral: 'text-muted', accent: 'text-accent', profit: 'text-profit', loss: 'text-loss', warn: 'text-warn', info: 'text-info' }
const SOLID: Record<Tone, string> = { neutral: 'bg-muted', accent: 'bg-accent', profit: 'bg-profit', loss: 'bg-loss', warn: 'bg-warn', info: 'bg-info' }
const SOFT: Record<Tone, string> = {
  neutral: 'bg-fg/[0.06] text-muted ring-fg/10', accent: 'bg-accent/10 text-accent ring-accent/25',
  profit: 'bg-profit/10 text-profit ring-profit/25', loss: 'bg-loss/10 text-loss ring-loss/25',
  warn: 'bg-warn/10 text-warn ring-warn/30', info: 'bg-info/10 text-info ring-info/25',
}
export const toneText = (t: Tone) => TEXT[t]
export const pnlTone = (v: number | null | undefined): Tone => v == null || v === 0 ? 'neutral' : v > 0 ? 'profit' : 'loss'

/** Inline number: LTR-isolated, tabular, monospace. */
export function N({ children, className }: { children: ReactNode; className?: string }) {
  return <span dir="ltr" className={cx('num', className)}>{children}</span>
}

export function Card({ title, subtitle, icon: Icon, actions, children, className, flush, footer }: {
  title?: ReactNode; subtitle?: ReactNode; icon?: LucideIcon; actions?: ReactNode; children?: ReactNode
  className?: string; flush?: boolean; footer?: ReactNode
}) {
  return (
    <section className={cx('flex flex-col overflow-hidden rounded-2xl border border-line bg-surface shadow-card', className)}>
      {(title || actions) && (
        <header className="flex items-center gap-3 border-b border-line px-5 py-3.5">
          {Icon && <span className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-accent/10 text-accent"><Icon size={16} /></span>}
          <div className="min-w-0 flex-1">
            <h3 className="truncate text-[15px] font-semibold">{title}</h3>
            {subtitle && <p className="truncate text-xs text-muted">{subtitle}</p>}
          </div>
          {actions}
        </header>
      )}
      <div className={cx('flex-1', !flush && 'p-5')}>{children}</div>
      {footer && <footer className="border-t border-line bg-surface2/60 px-5 py-3">{footer}</footer>}
    </section>
  )
}

const BTN: Record<string, string> = {
  primary: 'bg-accent text-white shadow-sm hover:brightness-110 active:brightness-95',
  secondary: 'border border-line bg-surface text-fg hover:bg-surface2',
  ghost: 'text-muted hover:bg-fg/5 hover:text-fg',
  danger: 'bg-loss text-white shadow-sm hover:brightness-110',
  success: 'bg-profit text-white shadow-sm hover:brightness-110',
  warn: 'bg-warn text-white shadow-sm hover:brightness-110',
}
export function Button({ variant = 'secondary', size = 'md', icon: Icon, children, className, ...p }:
  ButtonHTMLAttributes<HTMLButtonElement> & { variant?: keyof typeof BTN; size?: 'sm' | 'md' | 'lg'; icon?: LucideIcon }) {
  return (
    <button className={cx('inline-flex select-none items-center justify-center gap-2 whitespace-nowrap rounded-xl font-medium transition disabled:pointer-events-none disabled:opacity-40',
      size === 'sm' ? 'h-8 px-3 text-xs' : size === 'lg' ? 'h-11 px-5 text-sm' : 'h-10 px-4 text-sm', BTN[variant], className)} {...p}>
      {Icon && <Icon size={size === 'sm' ? 14 : 16} />}{children}
    </button>
  )
}

export function Badge({ tone = 'neutral', dot, children, className }: { tone?: Tone; dot?: boolean; children: ReactNode; className?: string }) {
  return (
    <span className={cx('inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 ring-inset', SOFT[tone], className)}>
      {dot && <span className={cx('h-1.5 w-1.5 rounded-full', SOLID[tone])} />}{children}
    </span>
  )
}

export function StatusDot({ tone, pulse }: { tone: Tone; pulse?: boolean }) {
  return (
    <span className="relative flex h-2.5 w-2.5 shrink-0">
      {pulse && <span className={cx('absolute inline-flex h-full w-full animate-ping rounded-full opacity-50', SOLID[tone])} />}
      <span className={cx('relative inline-flex h-2.5 w-2.5 rounded-full', SOLID[tone])} />
    </span>
  )
}

export function Sparkline({ data, tone = 'accent', className }: { data: number[]; tone?: Tone; className?: string }) {
  const id = 'sp' + useId().replace(/[^a-zA-Z0-9]/g, '')
  if (data.length < 2) return null
  const min = Math.min(...data), max = Math.max(...data), r = max - min || 1
  const line = data.map((v, i) => (i ? 'L' : 'M') + ((i / (data.length - 1)) * 100).toFixed(2) + ' ' + (29 - ((v - min) / r) * 27).toFixed(2)).join(' ')
  return (
    <svg viewBox="0 0 100 30" preserveAspectRatio="none" className={cx(TEXT[tone], className)} aria-hidden>
      <defs><linearGradient id={id} x1="0" x2="0" y1="0" y2="1"><stop offset="0" stopColor="currentColor" stopOpacity="0.28" /><stop offset="1" stopColor="currentColor" stopOpacity="0" /></linearGradient></defs>
      <path d={line + ' L100 30 L0 30 Z'} fill={`url(#${id})`} />
      <path d={line} fill="none" stroke="currentColor" strokeWidth="1.6" vectorEffect="non-scaling-stroke" strokeLinejoin="round" />
    </svg>
  )
}

export function Stat({ label, value, sub, tone, icon: Icon, spark }: {
  label: string; value: ReactNode; sub?: ReactNode; tone?: Tone; icon?: LucideIcon; spark?: number[]
}) {
  return (
    <div className="rounded-2xl border border-line bg-surface p-4 shadow-card">
      <div className="flex items-center justify-between gap-2 text-xs font-medium text-muted">
        <span className="truncate">{label}</span>{Icon && <Icon size={15} className="shrink-0 opacity-70" />}
      </div>
      <div className={cx('mt-2 text-2xl font-semibold tracking-tight', tone && TEXT[tone])}><N>{value}</N></div>
      {sub && <div className="mt-1 truncate text-xs text-muted">{sub}</div>}
      {spark && <Sparkline data={spark} tone={tone ?? 'accent'} className="mt-3 h-8 w-full" />}
    </div>
  )
}

export function Segmented<T extends string>({ options, value, onChange, size = 'sm' }: {
  options: { value: T; label: ReactNode }[]; value: T; onChange: (v: T) => void; size?: 'sm' | 'md'
}) {
  return (
    <div className="inline-flex rounded-xl border border-line bg-surface2 p-0.5" role="tablist">
      {options.map(o => (
        <button key={o.value} role="tab" aria-selected={o.value === value} onClick={() => onChange(o.value)}
          className={cx('rounded-[10px] px-3 font-medium transition', size === 'sm' ? 'h-7 text-xs' : 'h-9 text-sm',
            o.value === value ? 'bg-surface text-fg shadow-sm ring-1 ring-line' : 'text-muted hover:text-fg')}>{o.label}</button>
      ))}
    </div>
  )
}

export function Tabs<T extends string>({ tabs, value, onChange }: {
  tabs: { value: T; label: string; icon?: LucideIcon; count?: number }[]; value: T; onChange: (v: T) => void
}) {
  return (
    <div className="flex gap-1 overflow-x-auto border-b border-line" role="tablist">
      {tabs.map(t => {
        const on = t.value === value
        return (
          <button key={t.value} role="tab" aria-selected={on} onClick={() => onChange(t.value)}
            className={cx('relative flex items-center gap-2 whitespace-nowrap px-4 py-3 text-sm font-medium transition', on ? 'text-fg' : 'text-muted hover:text-fg')}>
            {t.icon && <t.icon size={16} />}{t.label}
            {t.count !== undefined && <span className={cx('num rounded-md px-1.5 text-[11px]', on ? 'bg-accent/15 text-accent' : 'bg-fg/[0.06]')}>{t.count}</span>}
            {on && <span className="absolute inset-x-3 -bottom-px h-0.5 rounded-full bg-accent" />}
          </button>
        )
      })}
    </div>
  )
}

export function Field({ label, hint, unit, children, className }: { label: string; hint?: string; unit?: string; children: ReactNode; className?: string }) {
  return (
    <label className={cx('block', className)}>
      <span className="mb-1.5 flex items-baseline gap-1.5 text-sm font-medium">{label}{unit && <span className="text-xs font-normal text-muted">{unit}</span>}</span>
      {children}
      {hint && <span className="mt-1.5 block text-xs leading-relaxed text-muted">{hint}</span>}
    </label>
  )
}
export const Input = ({ className, ...p }: InputHTMLAttributes<HTMLInputElement>) => <input className={cx('input', className)} {...p} />
export const Select = ({ className, children, ...p }: SelectHTMLAttributes<HTMLSelectElement>) => <select className={cx('input', className)} {...p}>{children}</select>
export const Textarea = ({ className, ...p }: TextareaHTMLAttributes<HTMLTextAreaElement>) => <textarea className={cx('input', className)} {...p} />

export function Switch({ checked, onChange, label }: { checked: boolean; onChange: (v: boolean) => void; label?: string }) {
  return (
    <button type="button" role="switch" aria-checked={checked} aria-label={label} onClick={() => onChange(!checked)}
      className={cx('relative inline-flex h-6 w-11 shrink-0 items-center rounded-full transition', checked ? 'bg-accent' : 'bg-fg/15')}>
      <span className={cx('absolute h-5 w-5 rounded-full bg-white shadow transition-all', checked ? 'end-0.5' : 'start-0.5')} />
    </button>
  )
}

export function Empty({ icon: Icon, title, text, action, compact }: { icon?: LucideIcon; title: string; text?: ReactNode; action?: ReactNode; compact?: boolean }) {
  return (
    <div className={cx('flex flex-col items-center justify-center px-6 text-center', compact ? 'py-8' : 'py-14')}>
      {Icon && <div className="mb-3 grid h-12 w-12 place-items-center rounded-2xl bg-fg/[0.05] text-muted ring-1 ring-inset ring-fg/[0.06]"><Icon size={22} /></div>}
      <div className="font-medium">{title}</div>
      {text && <p className="mt-1 max-w-md text-sm leading-relaxed text-muted">{text}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  )
}

const BANNER: Record<Tone, string> = {
  neutral: 'border-line bg-surface2', accent: 'border-accent/25 bg-accent/[0.06]', profit: 'border-profit/25 bg-profit/[0.06]',
  loss: 'border-loss/30 bg-loss/[0.06]', warn: 'border-warn/30 bg-warn/[0.07]', info: 'border-info/25 bg-info/[0.06]',
}
export function Banner({ tone = 'warn', icon: Icon, title, children, action }: { tone?: Tone; icon?: LucideIcon; title?: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className={cx('flex items-start gap-3 rounded-2xl border px-4 py-3 text-sm', BANNER[tone])}>
      {Icon && <Icon size={18} className={cx('mt-0.5 shrink-0', TEXT[tone])} />}
      <div className="min-w-0 flex-1 leading-relaxed">{title && <span className="font-semibold">{title}. </span>}<span className="text-fg/80">{children}</span></div>
      {action}
    </div>
  )
}

export function KV({ k, v, sub }: { k: ReactNode; v: ReactNode; sub?: ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-4 py-2.5 text-sm">
      <span className="text-muted">{k}</span>
      <span className="text-end font-medium">{v}{sub && <span className="ms-1.5 text-xs font-normal text-muted">{sub}</span>}</span>
    </div>
  )
}

/** Horizontal bar with threshold markers (e.g. drawdown tiers). Axis runs left->right like a chart. */
export function ThresholdMeter({ value, max, marks }: { value: number | null; max: number; marks: { at: number; tone: Tone }[] }) {
  const pct = (v: number) => Math.min(100, Math.max(0, (v / max) * 100))
  return (
    <div dir="ltr" className="pb-1 pt-7">
      <div className="relative h-2.5 rounded-full bg-gradient-to-r from-profit/20 via-warn/25 to-loss/35">
        {value !== null && <div className="absolute inset-y-0 left-0 rounded-full bg-accent" style={{ width: pct(value) + '%' }} />}
        {marks.map(m => (
          <div key={m.at} className="absolute -top-7 -translate-x-1/2 text-center" style={{ left: pct(m.at) + '%' }}>
            <div className={cx('num text-[11px] font-semibold', TEXT[m.tone])}>{m.at}%</div>
            <div className={cx('mx-auto mt-1 h-[22px] w-0.5 rounded-full', SOLID[m.tone])} />
          </div>
        ))}
      </div>
      <div className="num mt-2 flex justify-between text-[11px] text-muted"><span>0%</span><span>{max}%</span></div>
    </div>
  )
}

/** Centered bar for a signal in [-1, 1]. */
export function SignalBar({ value }: { value: number }) {
  const v = Math.max(-1, Math.min(1, value)), w = Math.abs(v) * 50
  return (
    <div dir="ltr" className="relative h-1.5 w-full rounded-full bg-fg/10">
      <div className="absolute inset-y-[-3px] left-1/2 w-px bg-fg/30" />
      <div className={cx('absolute inset-y-0 rounded-full', v >= 0 ? 'bg-profit' : 'bg-loss')} style={v >= 0 ? { left: '50%', width: w + '%' } : { right: '50%', width: w + '%' }} />
    </div>
  )
}

export const Skeleton = ({ className }: { className?: string }) => <div className={cx('animate-pulse rounded-lg bg-fg/[0.06]', className)} />

export function SectionTitle({ children, action }: { children: ReactNode; action?: ReactNode }) {
  return <div className="mb-3 flex items-center justify-between"><h4 className="text-xs font-semibold uppercase tracking-wider text-muted">{children}</h4>{action}</div>
}
