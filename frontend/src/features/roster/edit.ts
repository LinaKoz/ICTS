import type { AssignmentOut, EditableAssignmentOut, MoveAssignmentRequest, Role, Shift, ViolationOut, WorkerRefOut } from '../../api/schemas'
import { ApiError } from '../../errors/ApiError'
import type { Slot } from './api'
import { violationLabel } from './names'


const SHIFT_ORDER: Shift[] = ['A', 'B', 'C']

/** True when (date, shift) is before `freeFrom`, i.e. the shift already started (P3). */
export function isLockedShift(date: string, shift: Shift, freeFrom: [string, Shift] | null | undefined): boolean {
  if (!freeFrom) return false
  if (date !== freeFrom[0]) return date < freeFrom[0]
  return SHIFT_ORDER.indexOf(shift) < SHIFT_ORDER.indexOf(freeFrom[1])
}

const cellKey = (a: { worker_id: string; date: string; shift: string }) => `${a.worker_id}|${a.date}|${a.shift}`

/** Joins the id list (`GET .../assignments`) to roster assignments; (worker, date, shift) is unique. */
export function idLookup(editable: EditableAssignmentOut[] | null | undefined): (a: AssignmentOut) => number | undefined {
  const byKey = new Map((editable ?? []).map((e) => [cellKey(e), e.id]))
  return (a) => byKey.get(cellKey(a))
}

export interface MoveTarget { workerId: string; date: string; shift: Shift }

/** Sends only what changed; role always stays the source's slot role. */
export function buildMoveBody(
  from: AssignmentOut,
  to: MoveTarget,
  expectedVersion: number,
  acknowledge: boolean,
): MoveAssignmentRequest {
  return {
    ...(to.workerId !== from.worker_id ? { worker_id: to.workerId } : {}),
    ...(to.date !== from.date ? { date: to.date } : {}),
    ...(to.shift !== from.shift ? { shift: to.shift } : {}),
    expected_version: expectedVersion,
    acknowledge_approved_edit: acknowledge,
  }
}

export function moveUnchanged(from: AssignmentOut, to: MoveTarget): boolean {
  return to.workerId === from.worker_id && to.date === from.date && to.shift === from.shift
}

/** Active workers of the slot's role: the only valid move/add targets. */
export function workersForRole(workers: WorkerRefOut[] | null | undefined, role: Role): WorkerRefOut[] {
  return (workers ?? []).filter((w) => w.role === role && w.status === 'ACTIVE')
}

/** An approved roster needs an explicit acknowledgement before any edit (P12). */
export function needsApprovalAck(status: string | undefined): boolean {
  return status === 'APPROVED'
}

/** Which assignment's replacements to load: none until the planner picks one, then only that one. */
export function replacementTargets<T extends { id: number }>(fixable: T[], selectedId: number | null): T[] {
  return fixable.filter(({ id }) => id === selectedId)
}

/** Readable lines for a 422 HARD_VIOLATIONS body (`details` is a ViolationOut[]). */
export function violationLines(err: unknown, nameOf: (id: string) => string): string[] {
  if (!(err instanceof ApiError) || err.code !== 'HARD_VIOLATIONS' || !Array.isArray(err.details)) return []
  return (err.details as ViolationOut[]).map((v) => {
    const who = v.assignments.map((a) => `${nameOf(a.worker_id)} ${a.date} ${a.shift}`).join('; ')
    return `${violationLabel(v.code)}${v.magnitude > 1 ? ` (×${v.magnitude})` : ''}${who ? `: ${who}` : ''}`
  })
}

const ROLE_PHRASE: Record<Role, string> = { GENERAL_GUARD: 'general guard', SCREENER: 'screener', SUPERVISOR: 'supervisor' }

/** One plain-language sentence for a violation, phrased around the attempted change. */
export function explainViolation(v: ViolationOut, nameOf: (id: string) => string): string {
  const first = v.assignments[0]
  const who = first ? nameOf(first.worker_id) : 'This worker'
  const when = first ? `${first.date} shift ${first.shift}` : 'this shift'
  switch (v.code) {
    case 'DUPLICATE_ASSIGNMENT': return `${who} is already assigned to ${when}.`
    case 'OVERSTAFFED': return `${when} already has all the ${first ? ROLE_PHRASE[first.role] : ''} positions it needs, so there is no free spot.`
    case 'DAILY_LIMIT': return `${who} would work more than two shifts on ${first?.date ?? 'that day'}.`
    case 'ADJACENT_SHIFTS': return `${who} would work back-to-back shifts (${v.assignments.map((a) => `${a.date} ${a.shift}`).join(' and ')}).`
    case 'UNAVAILABLE': return `${who} is not available for ${when}.`
    case 'WRONG_ROLE': return `${who} is not qualified for the ${first ? ROLE_PHRASE[first.role] : 'requested'} role.`
    case 'INACTIVE_WORKER': return `${who} is inactive and cannot be assigned.`
    case 'UNKNOWN_WORKER': return 'That worker does not exist.'
    case 'OUT_OF_MONTH': return `${first?.date ?? 'That date'} is outside this roster's month.`
    case 'MAX_HOURS': return `${who} would go over their maximum monthly hours.`
    case 'NO_CONTRACT_FOR_MONTH': return `${who} has no contract for this month.`
    default: return violationLabel(v.code)
  }
}

/** Distinct plain-language reasons why the server refused an edit; empty for any other error. */
export function explainEditError(err: unknown, nameOf: (id: string) => string): string[] {
  if (err instanceof ApiError && err.code === 'LOCKED_SHIFT') return ['That shift has already started (or the month is history), so it can no longer be changed.']
  if (!(err instanceof ApiError) || err.code !== 'HARD_VIOLATIONS' || !Array.isArray(err.details)) return []
  return [...new Set((err.details as ViolationOut[]).map((v) => explainViolation(v, nameOf)))]
}

export function isApprovedEditError(err: unknown): boolean {
  return err instanceof ApiError && err.code === 'APPROVED_EDIT_NOT_ACKNOWLEDGED'
}

export type DropTarget = { kind: 'slot'; slot: Slot } | { kind: 'assignment'; assignment: AssignmentOut }

export interface CellRef { date: string; shift: Shift; role: Role }

export type DropAction =
  | { kind: 'move'; date: string; shift: Shift }
  | { kind: 'swap'; other: AssignmentOut }
  | { kind: 'reject'; message: string }

/**
 * What dropping `from` on `target` does: a free slot of the same role moves the worker there, another
 * worker's chip swaps the two (same role, any other day or shift). `null` means "not a drop target".
 * Only the sensible cases are offered; the server still validates every rule.
 */
export function dropAction(
  from: AssignmentOut,
  target: DropTarget,
  freeFrom: [string, Shift] | null | undefined,
): DropAction | null {
  const where = target.kind === 'slot' ? target.slot : target.assignment
  if (isLockedShift(where.date, where.shift, freeFrom)) return null
  if (where.role !== from.role) return null
  if (target.kind === 'slot') {
    return where.date === from.date && where.shift === from.shift ? null : { kind: 'move', date: where.date, shift: where.shift }
  }
  const other = target.assignment
  if (other.worker_id === from.worker_id) return null
  if (other.date === from.date && other.shift === from.shift) return null
  return { kind: 'swap', other }
}
