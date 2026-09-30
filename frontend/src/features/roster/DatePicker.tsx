import { useEffect, useId, useRef, useState, type KeyboardEvent } from 'react'
import { addDays, addMonths, clampDate, dateLabel, dayLabel, monthLabel, monthOf, monthWeeks, startOfWeek, todayIso } from './calendar'

interface Props {
  /** `YYYY-MM-DD`. */
  value: string
  onChange: (date: string) => void
  /** Accessible name of the trigger, e.g. "Go to date". */
  label: string
  min?: string
  max?: string
  /** Render the popover open (tests render statically; effects do not run there). */
  defaultOpen?: boolean
}

const DOW = ['Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa', 'Su']
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

const Chevron = ({ dir }: { dir: 'left' | 'right' }) => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d={dir === 'left' ? 'M15 5l-7 7 7 7' : 'M9 5l7 7-7 7'} />
  </svg>
)

/**
 * A themed date picker in place of the browser's `<input type="date">`: a trigger showing the date and a
 * popover with a Monday-first month grid, month/year navigation, Today, and arrow-key navigation.
 * Closes on Escape (focus returns to the trigger), a click outside, or picking a day.
 */
export function DatePicker({ value, onChange, label, min, max, defaultOpen = false }: Props) {
  const [open, setOpen] = useState(defaultOpen)
  const [mode, setMode] = useState<'days' | 'months'>('days')
  const [cursor, setCursor] = useState(value)
  const ref = useRef<HTMLDivElement>(null)
  const trigger = useRef<HTMLButtonElement>(null)
  const focusDay = useRef(false)
  const popId = useId()
  const today = todayIso()

  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) setOpen(false) }
    const onKey = (e: globalThis.KeyboardEvent) => { if (e.key === 'Escape') { setOpen(false); trigger.current?.focus() } }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => { document.removeEventListener('mousedown', onDown); document.removeEventListener('keydown', onKey) }
  }, [open])

  useEffect(() => {
    if (!open || mode !== 'days' || !focusDay.current) return
    focusDay.current = false
    ref.current?.querySelector<HTMLButtonElement>(`[data-date="${cursor}"]`)?.focus()
  }, [open, mode, cursor])

  const move = (date: string) => { focusDay.current = true; setCursor(clampDate(date, min, max)) }
  const outOfRange = (date: string) => (min != null && date < min) || (max != null && date > max)
  const monthDisabled = (ym: string) => (min != null && ym < monthOf(min)) || (max != null && ym > monthOf(max))
  const pick = (date: string) => { if (outOfRange(date)) return; onChange(date); setOpen(false); trigger.current?.focus() }

  function toggle() {
    if (open) { setOpen(false); return }
    setCursor(clampDate(value, min, max)); setMode('days'); focusDay.current = true; setOpen(true)
  }

  function onGridKey(e: KeyboardEvent<HTMLDivElement>) {
    const step: Record<string, string> = {
      ArrowLeft: addDays(cursor, -1), ArrowRight: addDays(cursor, 1), ArrowUp: addDays(cursor, -7), ArrowDown: addDays(cursor, 7),
      PageUp: addMonths(cursor, -1), PageDown: addMonths(cursor, 1),
      Home: startOfWeek(cursor), End: addDays(startOfWeek(cursor), 6),
    }
    const next = step[e.key]
    if (next) { e.preventDefault(); move(next) }
  }

  const cursorMonth = monthOf(cursor)
  const [cy, cm] = cursor.split('-').map(Number) as [number, number]
  const unit = mode === 'days' ? 1 : 12 // the months view pages by year
  const prevBlocked = monthDisabled(monthOf(addMonths(cursor, -unit)))
  const nextBlocked = monthDisabled(monthOf(addMonths(cursor, unit)))
  const page = (dir: 1 | -1) => setCursor(clampDate(addMonths(cursor, dir * unit), min, max))

  return (
    <div className="dp" ref={ref}>
      <button ref={trigger} type="button" className={`dp-trigger${open ? ' is-open' : ''}`} aria-label={`${label}: ${dayLabel(value)}`}
        aria-haspopup="dialog" aria-expanded={open} aria-controls={popId} onClick={toggle}>
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <rect x="3" y="5" width="18" height="16" rx="3" /><path d="M8 3v4M16 3v4M3 10h18" />
        </svg>
        {dateLabel(value)}
      </button>
      {open && (
        <div className="dp-pop" id={popId} role="dialog" aria-label={label}>
          <div className="dp-head">
            <button type="button" className="dp-nav" aria-label={mode === 'days' ? 'Previous month' : 'Previous year'} disabled={prevBlocked}
              onClick={() => page(-1)}><Chevron dir="left" /></button>
            <button type="button" className="dp-title" aria-live="polite" onClick={() => setMode(mode === 'days' ? 'months' : 'days')}>
              {mode === 'days' ? monthLabel(cursorMonth) : cy}
            </button>
            <button type="button" className="dp-nav" aria-label={mode === 'days' ? 'Next month' : 'Next year'} disabled={nextBlocked}
              onClick={() => page(1)}><Chevron dir="right" /></button>
          </div>
          {mode === 'days' ? (
            <div role="grid" aria-label={monthLabel(cursorMonth)} onKeyDown={onGridKey}>
              <div className="dp-grid" aria-hidden="true">{DOW.map((d) => <span key={d} className="dp-dow">{d}</span>)}</div>
              <div className="dp-grid">
                {monthWeeks(cursor).flat().map((d) => (
                  <button key={d} type="button" data-date={d} tabIndex={d === cursor ? 0 : -1} disabled={outOfRange(d)}
                    className={`dp-day${monthOf(d) !== cursorMonth ? ' dp-out' : ''}${d === today ? ' dp-today' : ''}${d === value ? ' dp-sel' : ''}`}
                    aria-label={dayLabel(d)} aria-pressed={d === value} aria-current={d === today ? 'date' : undefined} onClick={() => pick(d)}>
                    {Number(d.slice(8))}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <div className="dp-months">
              {MONTHS.map((name, i) => {
                const ym = `${cy}-${String(i + 1).padStart(2, '0')}`
                return (
                  <button key={ym} type="button" disabled={monthDisabled(ym)} aria-pressed={ym === monthOf(value)}
                    className={`dp-month${ym === monthOf(value) ? ' dp-sel' : ''}${ym === monthOf(today) ? ' dp-today' : ''}`}
                    onClick={() => { focusDay.current = true; setCursor(clampDate(addMonths(cursor, i + 1 - cm), min, max)); setMode('days') }}>
                    {name}
                  </button>
                )
              })}
            </div>
          )}
          <div className="dp-foot">
            <button type="button" className="dp-link" disabled={outOfRange(today)} onClick={() => pick(today)}>Today</button>
          </div>
        </div>
      )}
    </div>
  )
}
