import type { ReactNode } from 'react'
import type { Role, Shift } from '../../api/schemas'
import { type RosterFilter } from './filter'
import { SHIFT_INFO } from './names'
import { roleLabel } from '../workers/labels'


interface Props {
  filter: RosterFilter
  roles: Role[]
  shifts: Shift[]
  onChange: (f: RosterFilter) => void
}

/** One filter select; while it is set, a small × inside the pill (as in the worker search) clears just that filter. */
function FilterPill({ label, on, onClear, children }: { label: string; on: boolean; onClear: () => void; children: ReactNode }) {
  return (
    <div className={`filter-pill${on ? ' is-on' : ''}`}>
      <label>
        <span className="sr-only">{label}</span>
        {children}
      </label>
      {on && (
        <button type="button" className="filter-clear" onClick={onClear} aria-label={`Clear the ${label.toLowerCase()} filter`} title="Clear">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18" /></svg>
        </button>
      )}
    </div>
  )
}

/** Role and shift filters. Non-matching slots are dimmed rather than hidden, so the calendar keeps its shape. */
export function FilterBar({ filter, roles, shifts, onChange }: Props) {
  return (
    <div className="filter-bar" role="group" aria-label="Filter the calendar">
      <FilterPill label="Role" on={filter.role !== 'ALL'} onClear={() => onChange({ ...filter, role: 'ALL' })}>
        <select value={filter.role} onChange={(e) => onChange({ ...filter, role: e.target.value as Role | 'ALL' })}>
          <option value="ALL">All roles</option>
          {roles.map((r) => <option key={r} value={r}>{roleLabel(r)}</option>)}
        </select>
      </FilterPill>
      <FilterPill label="Shift" on={filter.shift !== 'ALL'} onClear={() => onChange({ ...filter, shift: 'ALL' })}>
        <select value={filter.shift} onChange={(e) => onChange({ ...filter, shift: e.target.value as Shift | 'ALL' })}>
          <option value="ALL">All shifts</option>
          {shifts.map((s) => <option key={s} value={s}>Shift {s} ({SHIFT_INFO[s].hours})</option>)}
        </select>
      </FilterPill>
    </div>
  )
}
