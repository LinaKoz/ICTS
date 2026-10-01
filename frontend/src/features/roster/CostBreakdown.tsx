import { useMemo, useState } from 'react'
import type { CostsOut } from '../../api/schemas'
import { Modal } from '../../components/Modal'
import { costRows, costScale, formatHours, ilsWhole, TOP_N, totalHours, type CostRow } from './costChart'
import { ils } from './names'

interface Props {
  costs: CostsOut
  nameOf: (workerId: string) => string
  onClose: () => void
}

const hoursLabel = (h: number) => `${formatHours(h)} scheduled hour${h === 1 ? '' : 's'}`
const costLabel = (r: CostRow) => r.amount === null ? 'unknown estimated cost' : `${ils(r.amount)} estimated cost`
const detail = (r: CostRow) => `${r.name} · ${hoursLabel(r.hours)} · ${costLabel(r)}`

/** The cost breakdown dialog: a lollipop chart (top 10 by default) and the full table, both from the same rows. */
export function CostBreakdown({ costs, nameOf, onClose }: Props) {
  const [view, setView] = useState<'chart' | 'table'>('chart')
  const rows = useMemo(() => costRows(costs.per_worker, nameOf), [costs.per_worker, nameOf])
  const hours = totalHours(costs.per_worker)
  const unknown = costs.unknown_cost_worker_count

  return (
    <Modal label="Estimated cost per worker" onClose={onClose}>
      <div className="modal-head">
        <h3>Estimated cost per worker</h3>
        <button className="modal-close" onClick={onClose} aria-label="Close" title="Close">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" aria-hidden="true">
            <path d="M5 5l14 14M19 5L5 19" />
          </svg>
        </button>
      </div>
      <dl className="cost-totals">
        <div>
          <dt>Total estimated cost · all workers</dt>
          <dd>{ils(costs.monthly_total_ils)}</dd>
          {unknown > 0 && <dd className="muted">{unknown} worker{unknown === 1 ? '' : 's'} with unknown cost not included</dd>}
        </div>
        <div>
          <dt>Total scheduled hours</dt>
          <dd>{formatHours(hours)}<span className="cost-unit"> h</span></dd>
        </div>
      </dl>
      {rows.length === 0 ? <p className="muted cost-empty">No workers are scheduled this month.</p> : (
        <>
          <div className="cost-view-bar">
            <div className="seg" role="group" aria-label="Cost breakdown view">
              <button aria-pressed={view === 'chart'} className={view === 'chart' ? 'seg-on' : ''} onClick={() => setView('chart')}>Chart</button>
              <button aria-pressed={view === 'table'} className={view === 'table' ? 'seg-on' : ''} onClick={() => setView('table')}>Table</button>
            </div>
          </div>
          {view === 'chart' ? <CostChart rows={rows} /> : <CostTable rows={rows} total={costs.monthly_total_ils} hours={hours} />}
        </>
      )}
    </Modal>
  )
}

function CostChart({ rows }: { rows: CostRow[] }) {
  const [showAll, setShowAll] = useState(false)
  const [hover, setHover] = useState<string | null>(null)
  const [picked, setPicked] = useState<string | null>(null)
  // One scale for every worker, so it does not jump when the list expands.
  const { max, ticks } = useMemo(() => costScale(rows), [rows])
  const visible = showAll ? rows : rows.slice(0, TOP_N)
  const more = rows.length > TOP_N
  const active = rows.find((r) => r.workerId === (hover ?? picked))
  const pct = (amount: number) => `${Math.min(100, (amount / max) * 100)}%`

  return (
    <div className="cost-chart">
      <div className="cost-chart-caption">
        <span id="cost-chart-title">{more && !showAll ? `Top ${TOP_N} by estimated cost` : `All ${rows.length} workers · highest cost first`}</span>
        {more && (
          <button type="button" className="link" aria-expanded={showAll} onClick={() => setShowAll((s) => !s)}>
            {showAll ? `Show top ${TOP_N}` : `Show all ${rows.length}`}
          </button>
        )}
      </div>
      <div className="cost-chart-scroll">
        <ul className="lollipops" aria-labelledby="cost-chart-title" onMouseLeave={() => setHover(null)}>
          {visible.map((r) => {
            const on = active?.workerId === r.workerId
            return (
              <li key={r.workerId}>
                <button
                  type="button" className={`lollipop-row${on ? ' is-active' : ''}`} aria-label={detail(r)} title={r.name}
                  onMouseEnter={() => setHover(r.workerId)} onFocus={() => setPicked(r.workerId)}
                  onClick={() => setPicked(r.workerId)}
                >
                  <span className="lollipop-name">{r.name}</span>
                  <span className="lollipop-track" aria-hidden="true">
                    {r.amount !== null && (
                      <>
                        <span className="lollipop-stem" style={{ width: pct(Number(r.amount)) }} />
                        <span className="lollipop-dot" style={{ left: pct(Number(r.amount)) }} />
                      </>
                    )}
                  </span>
                  <span className={`lollipop-value${r.amount === null ? ' muted' : ''}`} aria-hidden="true">{r.amount === null ? 'unknown' : ils(r.amount)}</span>
                </button>
              </li>
            )
          })}
        </ul>
        <div className="lollipop-axis" aria-hidden="true">
          <span />
          <span className="lollipop-ticks">
            {ticks.map((t) => <span key={t} style={{ left: pct(t) }}>{ilsWhole(t)}</span>)}
          </span>
          <span />
          <span className="lollipop-axis-label">Estimated cost (ILS)</span>
        </div>
      </div>
      <p className="cost-readout" aria-live="polite">
        {active ? detail(active) : <span className="muted">Hover, focus or tap a worker for details.</span>}
      </p>
    </div>
  )
}

function CostTable({ rows, total, hours }: { rows: CostRow[]; total: string; hours: number }) {
  return (
    <div className="table-scroll cost-table">
      <table className="table">
        <thead>
          <tr><th>Worker</th><th className="num">Hours</th><th className="num">Cost</th></tr>
        </thead>
        <tbody>
          <tr className="total-row">
            <td>Total</td>
            <td className="num">{formatHours(hours)} h</td>
            <td className="num">{ils(total)}</td>
          </tr>
          {rows.map((r) => (
            <tr key={r.workerId}>
              <td>{r.name}</td>
              <td className="num">{r.hours} h</td>
              <td className="num">{r.amount ? ils(r.amount) : <span className="muted">unknown</span>}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
