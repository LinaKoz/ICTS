import type { Role, Shift } from '../../api/schemas'
import { isFiltering, NO_FILTER, type RosterFilter } from './filter'
import { SHIFT_INFO } from './names'

const ROLE_NAME: Record<Role, string> = { GENERAL_GUARD: 'General guard', SCREENER: 'Screener', SUPERVISOR: 'Supervisor' }

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
      <label>
        <span className="sr-only">Role</span>
        <select value={filter.role} onChange={(e) => onChange({ ...filter, role: e.target.value as Role | 'ALL' })}>
          <option value="ALL">All roles</option>
          {roles.map((r) => <option key={r} value={r}>{ROLE_NAME[r]}</option>)}
        </select>
      </label>
      <label>
        <span className="sr-only">Shift</span>
        <select value={filter.shift} onChange={(e) => onChange({ ...filter, shift: e.target.value as Shift | 'ALL' })}>
          <option value="ALL">All shifts</option>
          {shifts.map((s) => <option key={s} value={s}>Shift {s} ({SHIFT_INFO[s].hours})</option>)}
        </select>
      </label>
      {isFiltering(filter) && <button onClick={() => onChange(NO_FILTER)}>Reset</button>}
    </div>
  )
}
