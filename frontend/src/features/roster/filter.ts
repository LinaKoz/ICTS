import type { AssignmentOut, Role, Shift } from '../../api/schemas'

export interface RosterFilter {
  /** Case-insensitive substring of the worker's name; empty matches everyone. */
  worker: string
  role: Role | 'ALL'
  shift: Shift | 'ALL'
}

export const NO_FILTER: RosterFilter = { worker: '', role: 'ALL', shift: 'ALL' }

export const isFiltering = (f: RosterFilter): boolean => f.worker.trim() !== '' || f.role !== 'ALL' || f.shift !== 'ALL'

/** Is a role or shift filter set? Only then do matching slots get emphasised (a name search emphasises chips instead). */
export const isSlotFiltering = (f: RosterFilter): boolean => f.role !== 'ALL' || f.shift !== 'ALL'

/** Does a shift/role slot pass the role and shift filters? Gaps use this, they have no worker. */
export function slotMatches(f: RosterFilter, shift: Shift, role: Role): boolean {
  return (f.shift === 'ALL' || f.shift === shift) && (f.role === 'ALL' || f.role === role)
}

export function assignmentMatches(f: RosterFilter, a: AssignmentOut, nameOf: (workerId: string) => string): boolean {
  if (!slotMatches(f, a.shift, a.role)) return false
  const needle = f.worker.trim().toLowerCase()
  return needle === '' || nameOf(a.worker_id).toLowerCase().includes(needle)
}
