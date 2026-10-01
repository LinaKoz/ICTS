import type { CostsOut } from '../../api/schemas'

export const TOP_N = 10

export interface CostRow {
  workerId: string
  name: string
  hours: number
  /** The backend's figure for this worker, as sent; null when their contract rate is unknown. */
  amount: string | null
}

/**
 * Per-worker costs as the backend calculated them, highest first. Ties (and unknown costs, which go last)
 * fall back to name, then id, so the order never depends on what the API happened to send first.
 */
export function costRows(perWorker: CostsOut['per_worker'], nameOf: (workerId: string) => string): CostRow[] {
  return perWorker
    .map((w) => ({ workerId: w.worker_id, name: nameOf(w.worker_id), hours: Number(w.hours), amount: w.amount_ils }))
    .sort((a, b) =>
      (a.amount === null ? 1 : 0) - (b.amount === null ? 1 : 0)
      || Number(b.amount ?? 0) - Number(a.amount ?? 0)
      || a.name.localeCompare(b.name)
      || a.workerId.localeCompare(b.workerId))
}

/** Same rounding the table's total row has always used. */
export const totalHours = (perWorker: CostsOut['per_worker']): number =>
  Math.round(perWorker.reduce((s, w) => s + Number(w.hours), 0) * 100) / 100

/**
 * A zero-based axis for the largest cost: the smallest round step (1, 2, 2.5 or 5 × 10ⁿ) that covers it in at most
 * four intervals, so the top dot sits near the end. All zero (or no known cost) still gets a non-zero span.
 */
export function costScale(rows: CostRow[]): { max: number; ticks: number[] } {
  const top = Math.max(0, ...rows.map((r) => Number(r.amount ?? 0)))
  if (top <= 0) return { max: 1, ticks: [0] }
  const pow = 10 ** Math.floor(Math.log10(top / 4))
  const step = [1, 2, 2.5, 5, 10].map((m) => m * pow).find((st) => Math.ceil(top / st) <= 4) ?? 10 * pow
  const intervals = Math.ceil(top / step)
  return { max: intervals * step, ticks: Array.from({ length: intervals + 1 }, (_, i) => i * step) }
}

const wholeFmt = new Intl.NumberFormat('en-IL', { maximumFractionDigits: 0 })
const hoursFmt = new Intl.NumberFormat('en-IL', { maximumFractionDigits: 2 })
export const formatHours = (h: number): string => hoursFmt.format(h)

/** Axis labels: same shekel format as `ils`, without the agorot. */
export const ilsWhole = (amount: number): string => `₪${wholeFmt.format(amount)}`
