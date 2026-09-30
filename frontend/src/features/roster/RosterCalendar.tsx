import { useState, type DragEvent } from 'react'
import type { AssignmentOut, Role, Shift } from '../../api/schemas'
import { Modal } from '../../components/Modal'
import { dayLabel, monthLabel, monthOf, monthWeeks, weekDays, weekdayShort, type CalendarView } from './calendar'
import { ViolationFix, type FixProps } from './FixPanel'
import { type CalendarIndex, violatingWorkers, violationKey } from './calendarData'
import { dropAction, explainViolation, isLockedShift, type CellRef, type DropAction, type DropTarget } from './edit'
import { isFiltering, NO_FILTER, slotMatches, type RosterFilter } from './filter'
import { ils, SHIFT_INFO, violationLabel } from './names'

const ROLE_LABEL: Record<Role, string> = { GENERAL_GUARD: 'GG', SCREENER: 'SCR', SUPERVISOR: 'SUP' }
const ROLE_NAME: Record<Role, string> = { GENERAL_GUARD: 'General guard', SCREENER: 'Screener', SUPERVISOR: 'Supervisor' }

export interface CalendarEdit {
  onAssignment: (a: AssignmentOut) => void
  onGap: (slot: CellRef) => void
  /** A chip was dropped on a free slot (move) or on another worker's chip (swap). */
  onDrop: (from: AssignmentOut, action: DropAction, where: CellRef) => void
  /** Why the last attempted change to a cell was refused; shown inside that cell. */
  problem?: { cell: CellRef; lines: string[]; onDismiss: () => void } | null
  /** `worker|date|shift` of the assignment open in the edit dialog. */
  selectedKey?: string | null
}

interface Props {
  view: CalendarView
  anchor: string
  today: string
  /** Month that generate/save/approve/edit act on. Cells of other months are view-only. */
  targetMonth: string
  shifts: Shift[]
  roles: Role[]
  demand: { shift: Shift; role: Role; headcount: number }[]
  index: CalendarIndex
  edit?: CalendarEdit
  /** Worker to highlight; everyone else is dimmed. */
  focusId?: string | null
  /** Role/shift filter; non-matching slots are dimmed. */
  filter?: RosterFilter
  /** When set, Day view lists replacement options under each violation of the day. */
  fix?: FixProps
  onOpenDay: (date: string) => void
}

interface Ctx extends Props {
  head: (s: Shift, r: Role) => number
  dnd: ReturnType<typeof useDnd>
}

/** Drag-and-drop state and rules, shared by the Day and Week views. */
function useDnd(p: Pick<Props, 'index' | 'targetMonth' | 'edit'> & { head: (s: Shift, r: Role) => number }) {
  const { index, targetMonth, edit, head } = p
  const [dragging, setDragging] = useState<AssignmentOut | null>(null)
  const [over, setOver] = useState<string | null>(null)

  /** What a drop does. Dropping on the background of a full slot means "swap with whoever is there". */
  const actionFor = (target: DropTarget): DropAction | null => {
    if (!dragging || !edit) return null
    const where = target.kind === 'slot' ? target.slot : target.assignment
    if (monthOf(where.date) !== targetMonth) return null
    const base = dropAction(dragging, target, index.freeFrom(monthOf(where.date)))
    if (target.kind !== 'slot' || base?.kind !== 'move') return base
    const { date, shift, role } = target.slot
    const here = index.assignmentsAt(date, shift, role)
    if (here.length === 0 || here.length < head(shift, role)) return base
    if (here.length === 1) return dropAction(dragging, { kind: 'assignment', assignment: here[0]! }, index.freeFrom(monthOf(date)))
    return { kind: 'reject', message: 'This shift is full. To swap, drop onto the name of the worker you want to swap with.' }
  }
  const dropProps = (target: DropTarget, key: string) => {
    const where = target.kind === 'slot' ? target.slot : target.assignment
    const action = actionFor(target)
    if (!dragging || !edit || !action) return {}
    return {
      onDragOver: (e: DragEvent) => { e.preventDefault(); e.stopPropagation(); e.dataTransfer.dropEffect = action.kind === 'reject' ? 'none' : 'move'; setOver(key) },
      onDragLeave: () => setOver((o) => (o === key ? null : o)),
      onDrop: (e: DragEvent) => { e.preventDefault(); e.stopPropagation(); setOver(null); setDragging(null); edit.onDrop(dragging, action, { date: where.date, shift: where.shift, role: where.role }) },
    }
  }
  const dropClass = (target: DropTarget, key: string) => {
    const action = actionFor(target)
    return !action ? '' : over === key ? (action.kind === 'reject' ? ' drop-bad' : ' drop-over') : action.kind === 'reject' ? '' : ' drop-ok'
  }
  return { dragging, setDragging, setOver, dropProps, dropClass }
}

/** The three roles of one shift on one date, with chips, gaps, warnings and cost. */
function ShiftBlock({ date, shift, ctx, full }: { date: string; shift: Shift; ctx: Ctx; full: boolean }) {
  const { index, edit, roles, targetMonth, dnd, head, focusId, filter = NO_FILTER } = ctx
  const focusClass = (id: string) => (focusId ? (id === focusId ? ' chip-focus' : ' chip-dim') : '')
  const filtering = isFiltering(filter)
  const month = monthOf(date)
  const status = index.status(month)
  if (status !== 'ready') {
    return <div className="cal-noroster muted">{status === 'loading' ? 'Loading…' : status === 'error' ? 'Could not load' : 'No roster loaded'}</div>
  }
  const locked = isLockedShift(date, shift, index.freeFrom(month))
  const editable = edit != null && !locked && month === targetMonth
  const warnings = index.warningsAt(date, shift)
  const violating = violatingWorkers(warnings, date, shift)
  const violationTitle = [...new Set(warnings.map((v) => violationLabel(v.code)))].join(', ')
  const cost = index.costAt(date, shift)
  const problem = edit?.problem && edit.problem.cell.date === date && edit.problem.cell.shift === shift ? edit.problem : null
  return (
    <div className={`shift-block${locked ? ' locked' : ''}${problem ? ' cell-problem' : ''}${warnings.length > 0 ? ' has-violation' : ''}`}>
      {locked && <span className="lock" title="Shift already started">locked</span>}
      {roles.map((r) => {
        const names = index.assignmentsAt(date, shift, r)
        const gap = index.gapAt(date, shift, r)
        const missing = gap?.missing ?? Math.max(0, head(shift, r) - names.length)
        const slotKey = `s|${date}|${shift}|${r}`
        const slotTarget: DropTarget = { kind: 'slot', slot: { date, shift, role: r } }
        return (
          <div key={r} className={`slot${full ? ' slot-full' : ''}${filtering && !slotMatches(filter, shift, r) ? ' slot-dim' : ''}${editable ? dnd.dropClass(slotTarget, slotKey) : ''}`} {...(editable ? dnd.dropProps(slotTarget, slotKey) : {})}>
            <span className={`role role-${r}`} title={ROLE_NAME[r]}><i className="role-dot" aria-hidden="true" />{ROLE_LABEL[r]}</span>
            {names.map((a) => {
              const name = index.nameOf(a.worker_id)
              const bad = violating.has(a.worker_id)
              const badClass = bad ? ' chip-violation' : ''
              const badMark = bad ? <span className="chip-violation-mark" aria-label="Rule violation">⚠</span> : null
              const chipKey = `a|${a.worker_id}|${date}|${shift}`
              const target: DropTarget = { kind: 'assignment', assignment: a }
              return editable
                ? <button key={a.worker_id} title={bad ? `${name}: ${violationTitle} — click to fix` : `${name} — click to open, drag to move or swap`} draggable
                    className={`chip chip-btn${badClass}${focusClass(a.worker_id)}${dnd.dragging === a ? ' dragging' : ''}${edit?.selectedKey === `${a.worker_id}|${date}|${shift}` ? ' chip-selected' : ''}${dnd.dropClass(target, chipKey)}`}
                    onDragStart={(e) => { e.dataTransfer.effectAllowed = 'move'; e.dataTransfer.setData('text/plain', a.worker_id); dnd.setDragging(a) }}
                    onDragEnd={() => { dnd.setDragging(null); dnd.setOver(null) }}
                    {...dnd.dropProps(target, chipKey)}
                    onClick={() => edit.onAssignment(a)}>{badMark}<span className="chip-text">{name}</span></button>
                : <span key={a.worker_id} className={`chip${badClass}${focusClass(a.worker_id)}`} title={bad ? `${name}: ${violationTitle}` : name}>{badMark}<span className="chip-text">{name}</span></span>
            })}
            {missing > 0 && (
              gap?.locked || locked
                ? <span className="chip gap past" title="Uncovered in a shift that already started"><span aria-hidden="true">⚠ </span>past gap ×{missing}</span>
                : editable
                  ? <button className="chip gap chip-btn" title="Show suggestions" onClick={() => edit.onGap({ date, shift, role: r })}><span aria-hidden="true">⚠ </span>gap ×{missing}</button>
                  : <span className="chip gap" title="Uncovered position"><span aria-hidden="true">⚠ </span>gap ×{missing}</span>
            )}
          </div>
        )
      })}
      {problem && (
        <div className="cell-error" role="alert">
          <button className="link" onClick={problem.onDismiss} aria-label="Dismiss">×</button>
          <strong>Not allowed here</strong>
          <ul>{problem.lines.map((l) => <li key={l}>{l}</li>)}</ul>
        </div>
      )}
      {(warnings.length > 0 || (full && cost)) && (
        <div className="shift-meta">
          {warnings.length > 0 && (
            <span className="warn" title={violationTitle}>
              <span aria-hidden="true">⚠</span> {warnings.length} rule {warnings.length === 1 ? 'issue' : 'issues'}
            </span>
          )}
          {full && cost && <span className="shift-cost muted" title="Estimated cost of this shift">{ils(cost.amount_ils)}{cost.unknown_cost_assignments > 0 && ` + ${cost.unknown_cost_assignments} unknown`}</span>}
        </div>
      )}
    </div>
  )
}

function DayHeader({ date, today, anchor, onOpenDay }: { date: string; today: string; anchor: string; onOpenDay: (d: string) => void }) {
  return (
    <button className={`cal-dayhead${date === today ? ' is-today' : ''}${date === anchor ? ' is-selected' : ''}`} onClick={() => onOpenDay(date)}
      aria-label={`Open ${dayLabel(date)}${date === today ? ' (today)' : ''}`}>
      <span className="dow">{weekdayShort(date)}</span>
      <span className="dnum">{Number(date.slice(8))}</span>
      {date.slice(8) === '01' && <span className="dmon">{monthLabel(monthOf(date)).split(' ')[0]}</span>}
    </button>
  )
}

/** One shift of one date in a popup, so the week grid can stay in view behind it. */
function ShiftPopup({ date, shift, ctx, onClose }: { date: string; shift: Shift; ctx: Ctx; onClose: () => void }) {
  const { index, fix } = ctx
  const warnings = index.warningsAt(date, shift)
  const label = `Shift ${shift}, ${dayLabel(date)}`
  return (
    <Modal label={label} onClose={onClose}>
      <div className="modal-head">
        <h3>Shift {shift} <span className="shift-hours">{SHIFT_INFO[shift].name}, {SHIFT_INFO[shift].hours}</span></h3>
        <button className="modal-close" onClick={onClose} aria-label="Close" title="Close">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" aria-hidden="true">
            <path d="M5 5l14 14M19 5L5 19" />
          </svg>
        </button>
      </div>
      <p className="muted shift-popup-date">{dayLabel(date)}</p>
      <section className={`cal-day-shift shift-edge shift-${shift}`} aria-label={label}>
        <ShiftBlock date={date} shift={shift} ctx={ctx} full />
      </section>
      {warnings.length > 0 && (
        <div className="cal-day-warn" role="status">
          <strong><span aria-hidden="true">⚠</span> Rule violations in this shift</strong>
          <ul className="cal-day-violations">
            {warnings.map((v) => {
              const text = explainViolation(v, index.nameOf)
              return fix
                ? <ViolationFix key={violationKey(v)} v={v} fix={fix} text={text} />
                : <li key={violationKey(v)}>{text}</li>
            })}
          </ul>
        </div>
      )}
    </Modal>
  )
}

function WeekView({ ctx }: { ctx: Ctx }) {
  const { anchor, today, shifts, onOpenDay, targetMonth } = ctx
  const days = weekDays(anchor)
  const [open, setOpen] = useState<{ date: string; shift: Shift } | null>(null)
  // Chips and gap buttons keep their own action; a click anywhere else in the cell opens the shift.
  const openFrom = (e: { target: EventTarget }, date: string, shift: Shift) => {
    if ((e.target as HTMLElement).closest('button, a, input, select')) return
    setOpen({ date, shift })
  }
  return (
    <div className="cal-scroll">
      {open && <ShiftPopup date={open.date} shift={open.shift} ctx={ctx} onClose={() => setOpen(null)} />}
      <table className="cal-week" aria-label="Week schedule">
        <thead>
          <tr>
            <th className="corner" scope="col"><span className="sr-only">Shift</span></th>
            {days.map((d) => (
              <th key={d} scope="col" className={`${d === today ? 'col-today' : ''}${monthOf(d) !== targetMonth ? ' col-other' : ''}`}>
                <DayHeader date={d} today={today} anchor={anchor} onOpenDay={onOpenDay} />
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {shifts.map((s) => (
            <tr key={s}>
              <th scope="row" className={`shift-label shift-edge shift-${s}`}>Shift {s}<span className="shift-hours">{SHIFT_INFO[s].name}<br />{SHIFT_INFO[s].hours}</span></th>
              {days.map((d) => (
                <td key={d} className={`cal-cell ${d === today ? 'col-today' : ''}${monthOf(d) !== targetMonth ? ' col-other' : ''}`}
                  tabIndex={0} aria-label={`Open shift ${s}, ${dayLabel(d)}`}
                  onClick={(e) => openFrom(e, d, s)}
                  onKeyDown={(e) => { if ((e.key === 'Enter' || e.key === ' ') && e.target === e.currentTarget) { e.preventDefault(); setOpen({ date: d, shift: s }) } }}>
                  <ShiftBlock date={d} shift={s} ctx={ctx} full={false} />
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function DayView({ ctx }: { ctx: Ctx }) {
  const { anchor, today, shifts, index, fix } = ctx
  const warnings = index.warningsAt(anchor)
  return (
    <div className="cal-day">
      <h3 className="cal-day-title">{dayLabel(anchor)}{anchor === today && <span className="today-pill">Today</span>}</h3>
      {warnings.length > 0 && (
        <div className="cal-day-warn" role="status">
          <strong><span aria-hidden="true">⚠</span> Rule violations on this day</strong>
          <ul className="cal-day-violations">
            {warnings.map((v) => {
              const text = explainViolation(v, index.nameOf)
              return fix
                ? <ViolationFix key={violationKey(v)} v={v} fix={fix} text={text} />
                : <li key={violationKey(v)}>{text}</li>
            })}
          </ul>
        </div>
      )}
      <div className="cal-day-shifts">
        {shifts.map((s) => (
          <section key={s} className={`cal-day-shift shift-edge shift-${s}`} aria-label={`Shift ${s}`}>
            <h4>Shift {s} <span className="shift-hours">{SHIFT_INFO[s].name}, {SHIFT_INFO[s].hours}</span></h4>
            <ShiftBlock date={anchor} shift={s} ctx={ctx} full />
          </section>
        ))}
      </div>
    </div>
  )
}

function MonthView({ ctx }: { ctx: Ctx }) {
  const { anchor, today, shifts, roles, index, onOpenDay, head, focusId, filter = NO_FILTER } = ctx
  const weeks = monthWeeks(anchor)
  const weekdays = weekDays(weeks[0]![0]!)
  return (
    <div className="cal-scroll">
      <div className="cal-month" role="grid" aria-label={`${monthLabel(monthOf(anchor))} overview`}>
        <div className="cal-month-head" role="row">
          {weekdays.map((d) => <div key={d} role="columnheader">{weekdayShort(d)}</div>)}
        </div>
        {weeks.map((week) => (
          <div key={week[0]} className="cal-month-week" role="row">
            {week.map((d) => {
              const status = index.status(monthOf(d))
              const warnings = index.warningsAt(d)
              return (
                <button key={d} role="gridcell" className={`mcell${focusId && shifts.some((s) => roles.some((r) => index.assignmentsAt(d, s, r).some((a) => a.worker_id === focusId))) ? ' mcell-focus' : ''}${d === today ? ' is-today' : ''}${d === anchor ? ' is-selected' : ''}${monthOf(d) !== monthOf(anchor) ? ' mcell-out' : ''}${warnings.length > 0 ? ' mcell-violation' : ''}`}
                  onClick={() => onOpenDay(d)} aria-label={`Open ${dayLabel(d)}`}>
                  <span className="mday">{Number(d.slice(8))}{d.slice(8) === '01' && <span className="dmon"> {monthLabel(monthOf(d)).split(' ')[0]}</span>}</span>
                  {status !== 'ready'
                    ? <span className="muted mnone">{status === 'loading' ? 'Loading…' : status === 'error' ? 'Could not load' : 'No roster'}</span>
                    : (
                      <>
                        {shifts.map((s) => {
                          const shown = roles.filter((r) => slotMatches(filter, s, r))
                          const required = shown.reduce((n, r) => n + head(s, r), 0)
                          const assigned = shown.reduce((n, r) => n + index.assignmentsAt(d, s, r).length, 0)
                          const short = Math.max(0, required - assigned)
                          return (
                            <span key={s} className={`msum${short > 0 ? ' short' : ''}${shown.length === 0 ? ' msum-dim' : ''}`} title={`Shift ${s} (${SHIFT_INFO[s].hours}): ${short > 0 ? `${short} unfilled` : 'fully staffed'}`}>
                              <b className={`sh sh-${s}`}>{s}</b> {assigned}/{required}{short > 0 && <span className="mflag"> ⚠ −{short}</span>}
                            </span>
                          )
                        })}
                        {warnings.length > 0 && <span className="warn" title={[...new Set(warnings.map((v) => violationLabel(v.code)))].join(', ')}><span aria-hidden="true">⚠</span> {warnings.length} rule {warnings.length === 1 ? 'issue' : 'issues'}</span>}
                        {focusId && (() => {
                          const mine = shifts.filter((s) => roles.some((r) => index.assignmentsAt(d, s, r).some((a) => a.worker_id === focusId)))
                          return mine.length > 0 ? <span className="mfocus" title={`${index.nameOf(focusId)} works ${mine.join(', ')}`}>● {mine.join(' · ')}</span> : null
                        })()}
                      </>
                    )}
                </button>
              )
            })}
          </div>
        ))}
      </div>
    </div>
  )
}

export function RosterCalendar(props: Props) {
  const head = (s: Shift, r: Role) => props.demand.find((d) => d.shift === s && d.role === r)?.headcount ?? 0
  const dnd = useDnd({ index: props.index, targetMonth: props.targetMonth, edit: props.edit, head })
  const ctx: Ctx = { ...props, head, dnd }
  return (
    <div className={`cal cal-view-${props.view}${props.edit ? ' cal-editing' : ''}`}>
      {props.view === 'week' && <WeekView ctx={ctx} />}
      {props.view === 'day' && <DayView ctx={ctx} />}
      {props.view === 'month' && <MonthView ctx={ctx} />}
    </div>
  )
}
