/**
 * Calendar date math for the roster page. Dates are `YYYY-MM-DD` strings and are only ever
 * computed in UTC, so they cannot drift with the browser's timezone. "Today" is decided in
 * `Asia/Jerusalem`, like the backend (README, Time). Weeks start on Monday, the app's weekday
 * order (MON..SUN) everywhere else.
 */
export type CalendarView = 'day' | 'week' | 'month'

const TZ = 'Asia/Jerusalem'

const utc = (iso: string) => new Date(`${iso}T00:00:00Z`)
const iso = (d: Date) => d.toISOString().slice(0, 10)

export function todayIso(now: Date = new Date()): string {
  return new Intl.DateTimeFormat('en-CA', { timeZone: TZ, year: 'numeric', month: '2-digit', day: '2-digit' }).format(now)
}

export const monthOf = (date: string): string => date.slice(0, 7)

/** This month (`YYYY-MM`) in Asia/Jerusalem, the same "today" as the calendar and the backend. */
export const currentMonth = (now: Date = new Date()): string => monthOf(todayIso(now))

export function daysInMonth(month: string): number {
  const [y, m] = month.split('-').map(Number) as [number, number]
  return new Date(Date.UTC(y, m, 0)).getUTCDate()
}

export function addDays(date: string, n: number): string {
  const d = utc(date)
  d.setUTCDate(d.getUTCDate() + n)
  return iso(d)
}

/** Same day of the month `n` months away, clamped to the last day (31 Jan + 1 month = 28/29 Feb). */
export function addMonths(date: string, n: number): string {
  const [y, m, day] = date.split('-').map(Number) as [number, number, number]
  const first = new Date(Date.UTC(y, m - 1 + n, 1))
  const month = iso(first).slice(0, 7)
  return `${month}-${String(Math.min(day, daysInMonth(month))).padStart(2, '0')}`
}

/** 0 = Monday ... 6 = Sunday. */
export const weekdayIndex = (date: string): number => (utc(date).getUTCDay() + 6) % 7

export const startOfWeek = (date: string): string => addDays(date, -weekdayIndex(date))

export const weekDays = (date: string): string[] => Array.from({ length: 7 }, (_, i) => addDays(startOfWeek(date), i))

/** Whole weeks (Monday first) that cover the anchor's month, including the neighbouring months' days. */
export function monthWeeks(date: string): string[][] {
  const first = `${monthOf(date)}-01`
  const last = `${monthOf(date)}-${String(daysInMonth(monthOf(date))).padStart(2, '0')}`
  const weeks: string[][] = []
  for (let start = startOfWeek(first); start <= last; start = addDays(start, 7)) weeks.push(weekDays(start))
  return weeks
}

export function visibleDates(view: CalendarView, anchor: string): string[] {
  if (view === 'day') return [anchor]
  if (view === 'week') return weekDays(anchor)
  return monthWeeks(anchor).flat()
}

/** Months whose rosters the view touches, in order. */
export function visibleMonths(view: CalendarView, anchor: string): string[] {
  return [...new Set(visibleDates(view, anchor).map(monthOf))]
}

export function shiftAnchor(view: CalendarView, anchor: string, direction: 1 | -1): string {
  if (view === 'day') return addDays(anchor, direction)
  if (view === 'week') return addDays(anchor, 7 * direction)
  return addMonths(anchor, direction)
}

const fmt = (date: string, opts: Intl.DateTimeFormatOptions) =>
  new Intl.DateTimeFormat('en-GB', { timeZone: 'UTC', ...opts }).format(utc(date))

export const monthLabel = (month: string): string => fmt(`${month}-01`, { month: 'long', year: 'numeric' })

/** "7 Nov 2026". */
export const dateLabel = (date: string): string => fmt(date, { day: 'numeric', month: 'short', year: 'numeric' })

/** `date` limited to `[min, max]` (either bound optional); ISO dates compare as strings. */
export function clampDate(date: string, min?: string, max?: string): string {
  if (min && date < min) return min
  if (max && date > max) return max
  return date
}

export const dayLabel = (date: string): string => fmt(date, { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' })

export const weekdayShort = (date: string): string => fmt(date, { weekday: 'short' })

export function rangeLabel(view: CalendarView, anchor: string): string {
  if (view === 'day') return dayLabel(anchor)
  if (view === 'month') return monthLabel(monthOf(anchor))
  const days = weekDays(anchor)
  const [a, b] = [days[0]!, days[6]!]
  if (monthOf(a) === monthOf(b)) return `${fmt(a, { day: 'numeric' })} – ${fmt(b, { day: 'numeric', month: 'long', year: 'numeric' })}`
  if (a.slice(0, 4) === b.slice(0, 4)) return `${fmt(a, { day: 'numeric', month: 'short' })} – ${fmt(b, { day: 'numeric', month: 'short', year: 'numeric' })}`
  return `${fmt(a, { day: 'numeric', month: 'short', year: 'numeric' })} – ${fmt(b, { day: 'numeric', month: 'short', year: 'numeric' })}`
}
