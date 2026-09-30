import type { RosterOut } from '../../api/schemas'
import { daysInMonth, monthLabel } from './calendar'
import { ils } from './names'

interface Props {
  month: string
  demand: { headcount: number }[]
  view: Pick<RosterOut, 'coverage_gaps' | 'violations'> & { costs: RosterOut['costs'] | null }
  /** Opens the full violation list. */
  onShowViolations?: () => void
}

/** Whole-month figures from the roster's own gaps, violations and costs; the scope is stated so it is never read as a week or day. */
export function RosterSummary({ month, demand, view, onShowViolations }: Props) {
  const required = daysInMonth(month) * demand.reduce((n, d) => n + d.headcount, 0)
  const unfilled = view.coverage_gaps.reduce((n, g) => n + g.missing, 0)
  const filled = Math.max(0, required - unfilled)
  const pct = required > 0 ? Math.round((filled / required) * 100) : 100
  const costs = view.costs
  return (
    <section className="cal-summary" aria-label={`Summary for ${monthLabel(month)}, whole month`} title={`Figures for all of ${monthLabel(month)}, not only the visible days`}>
      <dl>
        <div><dt>Coverage</dt><dd>{filled}/{required} positions <span className="muted">({pct}%)</span></dd></div>
        <div className={unfilled > 0 ? 'is-warn' : ''}><dt>Unfilled</dt><dd>{unfilled > 0 && <span aria-hidden="true">⚠ </span>}{unfilled}</dd></div>
        <div className={view.violations.length > 0 ? 'is-bad' : ''}>
          <dt>Rule violations</dt>
          <dd>
            {view.violations.length > 0 && onShowViolations
              ? <button type="button" className="sum-link" onClick={onShowViolations} title="Show all rule violations">
                  <span aria-hidden="true">⚠ </span>{view.violations.length}<span className="sum-link-hint"> · View all</span>
                </button>
              : <>{view.violations.length > 0 && <span aria-hidden="true">⚠ </span>}{view.violations.length}</>}
          </dd>
        </div>
        <div><dt>Estimated cost</dt><dd>{costs ? ils(costs.monthly_total_ils) : 'n/a'}{costs && costs.unknown_cost_worker_count > 0 && <span className="muted"> (+{costs.unknown_cost_worker_count} unknown)</span>}</dd></div>
      </dl>
    </section>
  )
}
