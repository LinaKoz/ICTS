import type { AssignmentOut, EditableAssignmentOut, MoveAssignmentRequest, Role, Shift, ViolationOut, WorkerRefOut } from '../../api/schemas'
import { ApiError } from '../../errors/ApiError'
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

/** Readable lines for a 422 HARD_VIOLATIONS body (`details` is a ViolationOut[]). */
export function violationLines(err: unknown, nameOf: (id: string) => string): string[] {
  if (!(err instanceof ApiError) || err.code !== 'HARD_VIOLATIONS' || !Array.isArray(err.details)) return []
  return (err.details as ViolationOut[]).map((v) => {
    const who = v.assignments.map((a) => `${nameOf(a.worker_id)} ${a.date} ${a.shift}`).join('; ')
    return `${violationLabel(v.code)}${v.magnitude > 1 ? ` (×${v.magnitude})` : ''}${who ? `: ${who}` : ''}`
  })
}

export function isApprovedEditError(err: unknown): boolean {
  return err instanceof ApiError && err.code === 'APPROVED_EDIT_NOT_ACKNOWLEDGED'
}
