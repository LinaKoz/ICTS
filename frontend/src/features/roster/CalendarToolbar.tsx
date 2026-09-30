import type { ReactNode } from 'react'
import { DatePicker } from './DatePicker'
import { rangeLabel, shiftAnchor, type CalendarView } from './calendar'

const VIEWS: { id: CalendarView; label: string }[] = [
  { id: 'day', label: 'Day' },
  { id: 'week', label: 'Week' },
  { id: 'month', label: 'Month' },
]

interface Props {
  view: CalendarView
  anchor: string
  today: string
  onView: (v: CalendarView) => void
  onAnchor: (date: string) => void
  /** Extra controls (worker search) shown before the view switch. */
  extra?: ReactNode
}

/** Google-Calendar-style navigation: Today, previous/next by the active unit, the visible range, a date picker and the view switch. */
export function CalendarToolbar({ view, anchor, today, onView, onAnchor, extra }: Props) {
  return (
    <div className="cal-toolbar" role="toolbar" aria-label="Calendar navigation">
      <button onClick={() => onAnchor(today)}>Today</button>
      <div className="cal-nav">
        <button aria-label={`Previous ${view}`} onClick={() => onAnchor(shiftAnchor(view, anchor, -1))}>‹</button>
        <button aria-label={`Next ${view}`} onClick={() => onAnchor(shiftAnchor(view, anchor, 1))}>›</button>
      </div>
      <h2 className="cal-range" aria-live="polite">{rangeLabel(view, anchor)}</h2>
      <DatePicker value={anchor} onChange={onAnchor} label="Go to date" />
      <span className="spacer" />
      {extra}
      <div className="seg" role="group" aria-label="Calendar view">
        {VIEWS.map((v) => (
          <button key={v.id} aria-pressed={view === v.id} className={view === v.id ? 'seg-on' : ''} onClick={() => onView(v.id)}>{v.label}</button>
        ))}
      </div>
    </div>
  )
}
