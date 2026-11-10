import { useState } from 'react'
import { KeyRound } from 'lucide-react'
import { Button, Input, N } from './ui'

const TOKEN = 'admin_token'
export const getToken = () => { try { return sessionStorage.getItem(TOKEN) } catch { return null } }
export const setToken = (t: string | null) => { try { if (t) sessionStorage.setItem(TOKEN, t); else sessionStorage.removeItem(TOKEN) } catch { /* ignore */ } }

export function TokenPrompt({ onDone, onCancel, reason = 'שינוי הגדרות דורש טוקן מנהל' }: { onDone: (t: string) => void; onCancel: () => void; reason?: string }) {
  const [v, setV] = useState('')
  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/50 p-4 backdrop-blur-sm" onClick={onCancel}>
      <div className="w-full max-w-md rounded-2xl border border-line bg-surface p-6 shadow-pop" onClick={e => e.stopPropagation()}>
        <div className="flex items-center gap-3"><span className="grid h-10 w-10 place-items-center rounded-xl bg-accent/10 text-accent"><KeyRound size={18} /></span>
          <div><h3 className="font-semibold">אימות מנהל</h3><p className="text-xs text-muted">{reason}</p></div></div>
        <p className="mt-4 text-sm text-fg/80">הזן את הערך של <N className="rounded bg-fg/[0.06] px-1">ADMIN_TOKEN</N> מתוך הקובץ <N className="rounded bg-fg/[0.06] px-1">backend/.env</N>. הטוקן נשמר רק ללשונית זו.</p>
        <Input className="mt-4" dir="ltr" type="password" autoFocus value={v} onChange={e => setV(e.target.value)} onKeyDown={e => e.key === 'Enter' && v && onDone(v)} />
        <div className="mt-5 flex justify-end gap-2"><Button variant="ghost" onClick={onCancel}>ביטול</Button><Button variant="primary" disabled={!v} onClick={() => onDone(v)}>אישור</Button></div>
      </div>
    </div>
  )
}
