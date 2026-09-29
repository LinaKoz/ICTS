import type { AssignmentOut, CoverageGapOut, Role, Shift, ShiftCostOut, WorkerRefOut } from '../../api/schemas'
import { ils, nameLookup, shiftCostLookup } from './names'

const ROLE_LABEL: Record<Role, string> = { GENERAL_GUARD: 'GG', SCREENER: 'SCR', SUPERVISOR: 'SUP' }
const SHIFT_ORDER: Shift[] = ['A', 'B', 'C']

interface Props {
  month: string
  shifts: Shift[]
  roles: Role[]
  demand: { shift: Shift; role: Role; headcount: number }[]
  assignments: AssignmentOut[]
  gaps: CoverageGapOut[]
  freeFrom: [string, Shift] | null
  workers: WorkerRefOut[] | null | undefined
  perShiftCosts: ShiftCostOut[] | null | undefined
}

function isLocked(date: string, shift: Shift, freeFrom: [string, Shift] | null): boolean {
  if (!freeFrom) return false
  if (date !== freeFrom[0]) return date < freeFrom[0]
  return SHIFT_ORDER.indexOf(shift) < SHIFT_ORDER.indexOf(freeFrom[1])
}

export function RosterGrid({ month, shifts, roles, demand, assignments, gaps, freeFrom, workers, perShiftCosts }: Props) {
  const nameOf = nameLookup(workers)
  const costOf = shiftCostLookup(perShiftCosts)
  const [y, m] = month.split('-').map(Number) as [number, number]
  const days = Array.from({ length: new Date(y, m, 0).getDate() }, (_, i) => `${month}-${String(i + 1).padStart(2, '0')}`)
  const byCell = new Map<string, AssignmentOut[]>()
  for (const a of assignments) {
    const k = `${a.date}|${a.shift}|${a.role}`
    byCell.set(k, [...(byCell.get(k) ?? []), a])
  }
  const gapByCell = new Map(gaps.map((g) => [`${g.date}|${g.shift}|${g.role}`, g]))
  const head = (s: Shift, r: Role) => demand.find((d) => d.shift === s && d.role === r)?.headcount ?? 0

  return (
    <div className="grid-wrap">
      <table className="roster-grid">
        <thead>
          <tr>
            <th>Day</th>
            {shifts.map((s) => <th key={s}>Shift {s}</th>)}
          </tr>
        </thead>
        <tbody>
          {days.map((date) => {
            const dow = new Date(`${date}T00:00:00`).toLocaleDateString('en-GB', { weekday: 'short' })
            return (
              <tr key={date}>
                <th scope="row">{date.slice(8)} <span className="muted">{dow}</span></th>
                {shifts.map((s) => {
                  const locked = isLocked(date, s, freeFrom)
                  return (
                    <td key={s} className={locked ? 'cell locked' : 'cell'}>
                      {locked && <span className="lock" title="Shift already started">locked</span>}
                      {roles.map((r) => {
                        const names = byCell.get(`${date}|${s}|${r}`) ?? []
                        const gap = gapByCell.get(`${date}|${s}|${r}`)
                        const missing = gap?.missing ?? Math.max(0, head(s, r) - names.length)
                        return (
                          <div key={r} className="slot">
                            <span className="role">{ROLE_LABEL[r]}</span>
                            {names.map((a) => <span key={a.worker_id} className="chip" title={`Worker #${a.worker_id}`}>{nameOf(a.worker_id)}</span>)}
                            {missing > 0 && (
                              gap?.locked || locked
                                ? <span className="chip gap past" title="Uncovered in a shift that already started">past gap ×{missing}</span>
                                : <span className="chip gap" title="Uncovered position">gap ×{missing}</span>
                            )}
                          </div>
                        )
                      })}
                      {(() => {
                        const c = costOf(date, s)
                        if (!c) return null
                        return (
                          <div className="shift-cost muted" title="Estimated cost of this shift">
                            {ils(c.amount_ils)}
                            {c.unknown_cost_assignments > 0 && ` + ${c.unknown_cost_assignments} unknown`}
                          </div>
                        )
                      })()}
                    </td>
                  )
                })}
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
