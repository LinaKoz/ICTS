import type { Role, Shift } from '../../api/schemas'
import { isFiltering, NO_FILTER, type RosterFilter } from './filter'
import { SHIFT_INFO } from './names'
import { roleLabel } from '../workers/labels'


interface Props {
  filter: RosterFilter
  roles: Role[]
  shifts: Shift[]
  onChange: (f: RosterFilter) => void
}

/** Role and shift filters. Non-matching slots are dimmed rather than hidden, so the calendar keeps its shape. */
export function FilterBar({ filter, roles, shifts, onChange }: Props) {
  return (
    <div className="filter-bar" role="group" aria-label="Filter the calendar">
      <label className={`filter-pill${filter.role !== 'ALL' ? ' is-on' : ''}`}>
        <span className="sr-only">Role</span>
        <select value={filter.role} onChange={(e) => onChange({ ...filter, role: e.target.value as Role | 'ALL' })}>
          <option value="ALL">All roles</option>
          {roles.map((r) => <option key={r} value={r}>{roleLabel(r)}</option>)}
        </select>
      </label>
      <label className={`filter-pill${filter.shift !== 'ALL' ? ' is-on' : ''}`}>
        <span className="sr-only">Shift</span>
        <select value={filter.shift} onChange={(e) => onChange({ ...filter, shift: e.target.value as Shift | 'ALL' })}>
          <option value="ALL">All shifts</option>
          {shifts.map((s) => <option key={s} value={s}>Shift {s} ({SHIFT_INFO[s].hours})</option>)}
        </select>
      </label>
      {isFiltering(filter) && <button className="filter-reset" onClick={() => onChange(NO_FILTER)} aria-label="Clear filters" title="Clear filters">Clear</button>}
    </div>
  )
}
