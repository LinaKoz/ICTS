import { useId, useState } from 'react'
import type { CostsOut, Role, Shift, WorkerRefOut } from '../../api/schemas'
import { useContracts } from '../workers/api'
import { dayLabel, monthLabel, monthOf, monthWeeks, weekdayShort } from './calendar'
import { SHIFT_INFO } from './names'

const ROLE_NAME: Record<Role, string> = { GENERAL_GUARD: 'General guard', SCREENER: 'Screener', SUPERVISOR: 'Supervisor' }

/** Search box that picks one worker to highlight across the calendar. */
export function WorkerSearch({ workers, focusId, onFocus }: { workers: WorkerRefOut[]; focusId: string | null; onFocus: (id: string | null) => void }) {
  const [q, setQ] = useState('')
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(0)
  const listId = useId()
  const focused = workers.find((w) => w.worker_id === focusId)
  const needle = q.trim().toLowerCase()
  const matches = needle ? workers.filter((w) => w.full_name.toLowerCase().includes(needle)).slice(0, 8) : []
  const pick = (id: string) => { onFocus(id); setQ(''); setOpen(false); setActive(0) }
  return (
    <div className={`worker-search${focused ? ' has-focus' : ''}`}>
      <label>
        <span className="sr-only">Find a worker</span>
        <svg className="search-icon" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" aria-hidden="true"><circle cx="11" cy="11" r="7" /><path d="M20 20l-3.5-3.5" /></svg>
        <input type="search" placeholder={focused ? focused.full_name : 'Find a worker…'} value={q} role="combobox" aria-expanded={open && matches.length > 0} aria-controls={listId} aria-autocomplete="list"
          aria-activedescendant={open && matches[active] ? `${listId}-${active}` : undefined}
          onChange={(e) => { setQ(e.target.value); setOpen(true); setActive(0) }} onFocus={() => setOpen(true)} onBlur={() => setTimeout(() => setOpen(false), 120)}
          onKeyDown={(e) => {
            if (e.key === 'ArrowDown' && matches.length > 0) { e.preventDefault(); setOpen(true); setActive((active + 1) % matches.length) }
            if (e.key === 'ArrowUp' && matches.length > 0) { e.preventDefault(); setActive((active - 1 + matches.length) % matches.length) }
            if (e.key === 'Enter' && matches[active]) { e.preventDefault(); pick(matches[active].worker_id) }
            if (e.key === 'Escape') setOpen(false)
          }} />
      </label>
      {focused && !q && (
        <button type="button" className="worker-clear" onClick={() => onFocus(null)} aria-label={`Stop highlighting ${focused.full_name}`} title="Stop highlighting">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18" /></svg>
        </button>
      )}
      {open && matches.length > 0 && (
        <ul className="worker-suggest" id={listId} role="listbox">
          {matches.map((w, i) => (
            <li key={w.worker_id} id={`${listId}-${i}`} role="option" aria-selected={i === active} className={i === active ? 'is-active' : ''}>
              <button onMouseDown={(e) => e.preventDefault()} onClick={() => pick(w.worker_id)}>{w.full_name} <span className="muted">{ROLE_NAME[w.role]}</span></button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

interface CardProps {
  worker: WorkerRefOut
  month: string
  costs: CostsOut | null | undefined
  today: string
  /** Every shift of the worker in `month`. */
  monthShifts: { date: string; shift: Shift }[]
  /** Dates currently visible in the calendar; outlined in the mini calendar. */
  visibleDates: string[]
  onOpenDay: (date: string) => void
}

/** The focused worker's load: month hours against the contract's minimum and maximum, plus their shifts in the visible range. */
export function WorkerFocusCard({ worker, month, costs, today, monthShifts, visibleDates, onOpenDay }: CardProps) {
  const contract = useContracts(Number(worker.worker_id), month)
  const c = contract.data?.resolved ?? null
  const hours = costs?.per_worker.find((w) => w.worker_id === worker.worker_id)?.hours ?? 0
  const state = !c ? null : hours < c.min_hours ? 'below' : hours > c.max_hours ? 'over' : 'ok'
  const scale = c ? Math.max(c.max_hours, hours, 1) : 1
  return (
    <section className="focus-card" aria-label={`${worker.full_name}: hours and shifts`}>
      <header>
        <strong>{worker.full_name}</strong>
        <span className="badge">{ROLE_NAME[worker.role]}</span>
        {worker.status !== 'ACTIVE' && <span className="badge">{worker.status.toLowerCase()}</span>}
      </header>
      <div className="focus-shifts">
        <p className="focus-total"><strong>{monthShifts.length} shifts</strong> in {monthLabel(month)}</p>
        <ul className="shift-legend" aria-label="Shift key">
          {(['A', 'B', 'C'] as Shift[]).map((sh) => (
            <li key={sh}>
              <b className={`legend-letter shift-tag shift-${sh}`}>{sh}</b>
              <span className="legend-count" title={`${monthShifts.filter((m) => m.shift === sh).length} ${SHIFT_INFO[sh].name.toLowerCase()} shifts`}>{monthShifts.filter((m) => m.shift === sh).length}</span>
              <span>{SHIFT_INFO[sh].name} <span className="muted">{SHIFT_INFO[sh].hours}</span></span>
            </li>
          ))}
        </ul>
        <div className="mini-cal" role="grid" aria-label={`${worker.full_name}'s shifts in ${monthLabel(month)}`}>
          <div className="mini-head" role="row">{monthWeeks(`${month}-01`)[0]!.map((d) => <span key={d} role="columnheader">{weekdayShort(d).slice(0, 2)}</span>)}</div>
          {monthWeeks(`${month}-01`).map((week) => (
            <div key={week[0]} className="mini-week" role="row">
              {week.map((d) => {
                const mine = monthShifts.filter((m) => m.date === d).map((m) => m.shift)
                if (monthOf(d) !== month) return <span key={d} className="mini-day mini-out" role="gridcell" />
                return (
                  <button key={d} role="gridcell" onClick={() => onOpenDay(d)}
                    className={`mini-day${mine.length ? ' mini-has' : ''}${visibleDates.includes(d) ? ' mini-visible' : ''}${d === today ? ' mini-today' : ''}`}
                    aria-label={`${dayLabel(d)}${mine.length ? `, shifts ${mine.join(' and ')}` : ', no shifts'}`}>
                    <span className="mini-num">{Number(d.slice(8))}</span>
                    <span className="mini-shifts">{mine.map((sh) => <i key={sh} className={`sh sh-${sh}`}>{sh}</i>)}</span>
                  </button>
                )
              })}
            </div>
          ))}
        </div>
      </div>
      <div className="focus-load">
        <div className="focus-hours">
          <strong>{hours} h</strong> <span className="muted">in {monthLabel(month)}</span>
          {contract.isPending && <span className="muted"> · loading contract…</span>}
          {contract.isError && <span className="muted"> · contract unavailable</span>}
          {contract.data && !c && <span className="muted"> · no contract for this month</span>}
          {c && <span className="muted"> · contract {c.min_hours}–{c.max_hours} h</span>}
        </div>
        {c && (
          <>
            <div className="hours-bar" role="img" aria-label={`${hours} hours; minimum ${c.min_hours}, maximum ${c.max_hours}`}>
              <div className={`hours-fill ${state}`} style={{ width: `${Math.min(100, (hours / scale) * 100)}%` }} />
              <span className="hours-mark" style={{ left: `${(c.min_hours / scale) * 100}%` }} title={`Minimum ${c.min_hours} h`} />
              <span className="hours-mark hours-max" style={{ left: `${(c.max_hours / scale) * 100}%` }} title={`Maximum ${c.max_hours} h`} />
            </div>
            <p className={`hours-state ${state}`}>
              {state === 'below' && <><span aria-hidden="true">⚠ </span>{c.min_hours - hours} h below the minimum</>}
              {state === 'over' && <><span aria-hidden="true">⚠ </span>{hours - c.max_hours} h over the maximum</>}
              {state === 'ok' && <>Within contract ({c.max_hours - hours} h to the maximum)</>}
            </p>
          </>
        )}
      </div>
    </section>
  )
}
