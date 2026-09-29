import type { ShiftCostOut, ViolationCode, WorkerRefOut } from '../../api/schemas'

/** Worker id -> display name. Falls back to the id so a missing lookup never blanks the grid. */
export function nameLookup(workers: WorkerRefOut[] | null | undefined): (workerId: string) => string {
  const byId = new Map((workers ?? []).map((w) => [w.worker_id, w.full_name]))
  return (id) => byId.get(id) ?? `#${id}`
}

export function shiftCostLookup(perShift: ShiftCostOut[] | null | undefined): (date: string, shift: string) => ShiftCostOut | undefined {
  const byCell = new Map((perShift ?? []).map((c) => [`${c.date}|${c.shift}`, c]))
  return (date, shift) => byCell.get(`${date}|${shift}`)
}

/** Exhaustive on purpose: a new backend violation code fails the typecheck until it gets a label. */
const VIOLATION_LABEL: Record<ViolationCode, string> = {
  INACTIVE_WORKER: 'Inactive worker assigned',
  UNKNOWN_WORKER: 'Unknown worker',
  WRONG_ROLE: 'Worker in the wrong role',
  UNAVAILABLE: 'Worker not available',
  OUT_OF_MONTH: 'Assignment outside the month',
  DUPLICATE_ASSIGNMENT: 'Duplicate assignment',
  DAILY_LIMIT: 'More than one shift in a day',
  ADJACENT_SHIFTS: 'Back-to-back shifts',
  MAX_HOURS: 'Over maximum monthly hours',
  OVERSTAFFED: 'Overstaffed shift',
  NO_CONTRACT_FOR_MONTH: 'No contract for this month',
}

export function violationLabel(code: ViolationCode): string {
  return VIOLATION_LABEL[code] ?? code
}

const ilsFmt = new Intl.NumberFormat('en-IL', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
export const ils = (amount: string): string => `₪${ilsFmt.format(Number(amount))}`
