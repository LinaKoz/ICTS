import type { CostsOut, CoverageGapOut, HourShortfallOut, ViolationOut } from '../../api/rosterContract'

interface Props {
  violations: ViolationOut[]
  gaps: CoverageGapOut[]
  shortfalls: HourShortfallOut[]
  costs: CostsOut | null
}

const ils = (v: string) => `₪${Number(v).toLocaleString('en-IL', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`

export function SidePanel({ violations, gaps, shortfalls, costs }: Props) {
  const openGaps = gaps.filter((g) => g.missing > 0)
  return (
    <aside className="side">
      <section className="panel">
        <h3>Violations ({violations.length})</h3>
        {violations.length === 0 ? <p className="muted">None</p> : (
          <ul>{violations.map((v, i) => <li key={i}>{v.code} (×{v.magnitude}) {v.assignments.map((a) => `${a.worker_id} ${a.date} ${a.shift}`).join('; ')}</li>)}</ul>
        )}
      </section>
      <section className="panel">
        <h3>Coverage gaps ({openGaps.length})</h3>
        {openGaps.length === 0 ? <p className="muted">None</p> : (
          <ul>{openGaps.map((g) => (
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
          <ul>{shortfalls.map((s) => <li key={s.worker_id}>{s.worker_id}: {s.assigned_hours}/{s.min_hours} h ({s.missing_hours} h below minimum)</li>)}</ul>
        )}
      </section>
      <section className="panel">
        <h3>Estimated cost</h3>
        {!costs ? <p className="muted">Not available</p> : (
          <>
            <p><strong>{ils(costs.monthly_total_ils)}</strong> total{costs.unknown_cost_worker_count > 0 && <span className="muted"> ({costs.unknown_cost_worker_count} worker{costs.unknown_cost_worker_count === 1 ? '' : 's'} with unknown cost)</span>}</p>
            <table className="mini">
              <tbody>
                {costs.per_worker.map((w) => (
                  <tr key={w.worker_id}><td>{w.worker_id}</td><td>{w.hours} h</td><td>{w.amount_ils ? ils(w.amount_ils) : 'cost unknown'}</td></tr>
                ))}
              </tbody>
            </table>
          </>
        )}
      </section>
    </aside>
  )
}
