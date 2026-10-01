import { forwardRef, useState } from 'react'
import type { CostsOut, CoverageGapOut, HourOverageOut, HourShortfallOut, ViolationOut, WorkerRefOut } from '../../api/schemas'
import { Modal } from '../../components/Modal'
import { ViolationFix, type FixProps } from './FixPanel'
import { violationKey } from './calendarData'
import { ils, nameLookup, violationLabel } from './names'

interface Props {
  violations: ViolationOut[]
  gaps: CoverageGapOut[]
  shortfalls: HourShortfallOut[]
  /** Hours already worked above the maximum: nothing to fix, so a warning rather than a violation. */
  overages?: HourOverageOut[]
  costs: CostsOut | null
  workers: WorkerRefOut[] | null | undefined
  /** Present only when the stored roster is editable: adds a Fix action to each violation. */
  fix?: FixProps
  /** Jumps the calendar to a violation. */
  onShowViolation?: (v: ViolationOut) => void
  /** Briefly highlights the violations section (after the summary figure was clicked). */
  flashViolations?: boolean
}

/** The violations list: scrolls on its own when long; each entry can jump the calendar to its shift. */
export const SidePanel = forwardRef<HTMLElement, Props>(function SidePanel({ violations, gaps, shortfalls, overages = [], costs, workers, fix, onShowViolation, flashViolations }, violationsRef) {
  const nameOf = nameLookup(workers)
  const [showCosts, setShowCosts] = useState(false)
  const openGaps = gaps.filter((g) => g.missing > 0)
  return (
    <aside className="side">
      <section ref={violationsRef} tabIndex={-1} aria-label="Rule violations" className={`panel violations-panel${violations.length > 0 ? ' has-violations' : ''}${flashViolations ? ' panel-flash' : ''}`}>
        <h3>Violations ({violations.length})</h3>
        {violations.length === 0 ? <p className="muted">None</p> : (
          <ul className="scroll-list violation-list">{violations.map((v) => {
            const show = onShowViolation ? <button type="button" className="link" onClick={() => onShowViolation(v)} title="Show this shift on the calendar">Show</button> : null
            return fix
              ? <ViolationFix key={violationKey(v)} v={v} fix={fix} extra={show} />
              : <li key={violationKey(v)}>{violationLabel(v.code)} (×{v.magnitude}) {v.assignments.map((a) => `${nameOf(a.worker_id)} ${a.date} ${a.shift}`).join('; ')} {show}</li>
          })}</ul>
        )}
      </section>
      <section className="panel">
        <h3>Coverage gaps ({openGaps.length})</h3>
        {openGaps.length === 0 ? <p className="muted">None</p> : (
          <ul className="scroll-list">{openGaps.map((g) => (
            <li key={`${g.date}${g.shift}${g.role}`}>
              {g.date} {g.shift} {g.role.toLowerCase().replace('_', ' ')}: {g.assigned}/{g.required}
              {g.locked ? ' (past)' : g.proven_missing > 0 ? ' (cannot be filled)' : ''}
            </li>
          ))}</ul>
        )}
      </section>
      <section className="panel">
        <h3>Hour shortfalls ({shortfalls.length})</h3>
        {shortfalls.length === 0 ? <p className="muted">None</p> : (
          <ul className="scroll-list shortfall-list">{shortfalls.map((s) => <li key={s.worker_id}>{nameOf(s.worker_id)}: {s.assigned_hours}/{s.min_hours} h ({s.missing_hours} h below minimum)</li>)}</ul>
        )}
      </section>
      {overages.length > 0 && (
        <section className="panel">
          <h3>Worked over maximum ({overages.length})</h3>
          <ul className="scroll-list">{overages.map((o) => (
            <li key={o.worker_id} title="Already worked in shifts that started; nothing left to fix">
              <span aria-hidden="true">⚠ </span>{nameOf(o.worker_id)}: {o.worked_hours}/{o.max_hours} h worked ({o.over_hours} h over maximum)
            </li>
          ))}</ul>
        </section>
      )}
      <section className="panel cost-panel">
        <h3>Estimated cost</h3>
        {!costs ? <p className="muted">Not available</p> : (
          <>
            <p className="cost-total">
              <strong>{ils(costs.monthly_total_ils)}</strong>
              <span className="muted"> total{costs.unknown_cost_worker_count > 0 && ` (${costs.unknown_cost_worker_count} worker${costs.unknown_cost_worker_count === 1 ? '' : 's'} with unknown cost)`}</span>
            </p>
            <button className="btn-outline" onClick={() => setShowCosts(true)}>View cost breakdown <span aria-hidden="true">›</span></button>
            {showCosts && (
              <Modal label="Estimated cost per worker" onClose={() => setShowCosts(false)}>
                <div className="modal-head">
                  <h3>Estimated cost per worker</h3>
                  <button className="modal-close" onClick={() => setShowCosts(false)} aria-label="Close" title="Close">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" aria-hidden="true">
                      <path d="M5 5l14 14M19 5L5 19" />
                    </svg>
                  </button>
                </div>
                <div className="table-scroll cost-table">
                  <table className="table">
                    <thead>
                      <tr><th>Worker</th><th className="num">Hours</th><th className="num">Cost</th></tr>
                    </thead>
                    <tbody>
                      <tr className="total-row">
                        <td>Total</td>
                        <td className="num">{Math.round(costs.per_worker.reduce((s, w) => s + Number(w.hours), 0) * 100) / 100} h</td>
                        <td className="num">{ils(costs.monthly_total_ils)}</td>
                      </tr>
                      {costs.per_worker.map((w) => (
                        <tr key={w.worker_id}>
                          <td>{nameOf(w.worker_id)}</td>
                          <td className="num">{w.hours} h</td>
                          <td className="num">{w.amount_ils ? ils(w.amount_ils) : <span className="muted">unknown</span>}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </Modal>
            )}
          </>
        )}
      </section>
    </aside>
  )
})
