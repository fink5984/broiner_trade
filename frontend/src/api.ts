export async function api<T>(path: string, init?: { method?: string; body?: unknown; token?: string | null }): Promise<T> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  if (init?.token) headers['X-Admin-Token'] = init.token
  const res = await fetch(path, { method: init?.method ?? (init?.body ? 'POST' : 'GET'), headers, body: init?.body ? JSON.stringify(init.body) : undefined })
  const j = await res.json().catch(() => ({}))
  if (!res.ok) {
    const err = new Error(typeof j.detail === 'string' ? j.detail : res.status === 0 ? 'השרת אינו זמין' : `שגיאה ${res.status}`) as Error & { status?: number }
    err.status = res.status
    throw err
  }
  return j as T
}

export interface Status {
  mode: string; live_trading_enabled: boolean; system: string; database: string; trading_mode: string; broker: string
  market_data: string; ai: string; news: string; initial_capital: number; currency: string; demo_note: string
}
export interface Candle { time: number; open: number; high: number; low: number; close: number }
export interface Point { time: number; value: number }

export interface Overview {
  state: string; service_running: boolean; last_step_at: string | null; last_error: string | null; currency: string
  initial_capital: number; balance: number; equity: number; unrealized: number; realized: number; margin_used: number
  peak_equity: number; drawdown_pct: number; pnl: { day: number; week: number; month: number; total: number }
  open_trades: number; closed_trades: number; win_rate: number | null; open_risk_pct: number; mode: string; engine_mode: string
}
export interface TradeRow {
  number: number; symbol: string; strategy: string; side: string; units: number; entry_time: string; entry_price: number
  stop_loss: number; take_profit: number | null; exit_time: string | null; exit_price: number | null; fees: number
  spread_cost: number; net_pnl: number | null; entry_reason: string | null; exit_reason: string | null
  current_price: number | null; unrealized: number | null
}
export interface DecisionRow { ts: string; symbol: string; action: string; score: number; reasons: string[]; blockers: string[]; execution_status: string }
export interface AlertRow { ts: string; severity: string; kind: string; message: string }
export interface SettingDoc<T = Record<string, unknown>> { version: number; value: T; is_default: boolean; changed_at: string | null }

export const SYMBOL_NAMES: Record<string, string> = {
  USDILS: 'דולר / שקל', GBPILS: 'ליש״ט / שקל', GBPUSD: 'ליש״ט / דולר', EURUSD: 'אירו / דולר', XAUUSD: 'זהב / דולר',
  AUDUSD: 'דולר אוסטרלי / דולר', NZDUSD: 'דולר ניו-זילנד / דולר', USDCAD: 'דולר / דולר קנדי',
  USDCHF: 'דולר / פרנק שווייצרי', USDJPY: 'דולר / ין',
  XAGUSD: 'כסף / דולר', USOIL: 'נפט WTI', UKOIL: 'נפט ברנט', NGAS: 'גז טבעי', COPPER: 'נחושת',
}
export const fmtSymbol = (s: string) => /^[A-Z]{3}(USD|ILS|JPY|CAD|CHF|GBP|EUR|AUD|NZD)$/.test(s) ? s.slice(0, 3) + '/' + s.slice(3) : s
export const fmtMoney = (n: number, d = 0) => n.toLocaleString('he-IL', { minimumFractionDigits: d, maximumFractionDigits: d })
export const priceDigits = (s: string) => s.startsWith('XAU') || s.endsWith('OIL') ? 2 : s.endsWith('JPY') || s === 'XAGUSD' || s === 'NGAS' ? 3 : 4
