import { describe, expect, it } from 'vitest'
import type { AssignmentOut, WorkerRefOut } from '../../api/schemas'
import { ApiError } from '../../errors/ApiError'
import { mapError } from '../../errors/mapError'
import { buildMoveBody, idLookup, isApprovedEditError, isLockedShift, moveUnchanged, needsApprovalAck, violationLines, workersForRole } from './edit'

const a: AssignmentOut = { worker_id: '7', date: '2026-03-20', shift: 'A', role: 'GENERAL_GUARD' }

describe('isLockedShift', () => {
  it('compares against free_from by day then shift order', () => {
    const ff: [string, 'A' | 'B' | 'C'] = ['2026-03-10', 'B']
    expect(isLockedShift('2026-03-09', 'C', ff)).toBe(true)
    expect(isLockedShift('2026-03-10', 'A', ff)).toBe(true)
    expect(isLockedShift('2026-03-10', 'B', ff)).toBe(false)
    expect(isLockedShift('2026-03-11', 'A', ff)).toBe(false)
    expect(isLockedShift('2026-03-01', 'A', null)).toBe(false)
  })
})

describe('idLookup', () => {
  it('joins by worker, date and shift', () => {
    const find = idLookup([{ id: 5, worker_id: '7', date: '2026-03-20', shift: 'A', role: 'GENERAL_GUARD' }])
    expect(find(a)).toBe(5)
    expect(find({ ...a, shift: 'B' })).toBeUndefined()
    expect(idLookup(undefined)(a)).toBeUndefined()
  })
})

describe('buildMoveBody', () => {
  it('sends only changed fields plus version and acknowledgement', () => {
    expect(buildMoveBody(a, { workerId: '7', date: '2026-03-21', shift: 'A' }, 4, false)).toEqual({
      date: '2026-03-21', expected_version: 4, acknowledge_approved_edit: false,
    })
    expect(buildMoveBody(a, { workerId: '9', date: '2026-03-20', shift: 'C' }, 2, true)).toEqual({
      worker_id: '9', shift: 'C', expected_version: 2, acknowledge_approved_edit: true,
    })
  })
  it('detects a no-op move', () => {
    expect(moveUnchanged(a, { workerId: '7', date: '2026-03-20', shift: 'A' })).toBe(true)
    expect(moveUnchanged(a, { workerId: '8', date: '2026-03-20', shift: 'A' })).toBe(false)
  })
})

describe('workersForRole / approval', () => {
  const ws: WorkerRefOut[] = [
    { worker_id: '1', full_name: 'A', role: 'SCREENER', status: 'ACTIVE' },
    { worker_id: '2', full_name: 'B', role: 'SCREENER', status: 'INACTIVE' },
    { worker_id: '3', full_name: 'C', role: 'SUPERVISOR', status: 'ACTIVE' },
  ]
  it('keeps active workers of the role', () => {
    expect(workersForRole(ws, 'SCREENER').map((w) => w.worker_id)).toEqual(['1'])
    expect(workersForRole(null, 'SCREENER')).toEqual([])
  })
  it('only approved rosters need the acknowledgement', () => {
    expect(needsApprovalAck('APPROVED')).toBe(true)
    expect(needsApprovalAck('DRAFT')).toBe(false)
  })
})

describe('error helpers', () => {
  it('lists the violations of a HARD_VIOLATIONS error', () => {
    const err = new ApiError(422, 'HARD_VIOLATIONS', 'no', [
      { code: 'MAX_HOURS', key: ['7'], magnitude: 16, assignments: [a] },
      { code: 'ADJACENT_SHIFTS', key: [], magnitude: 1, assignments: [] },
    ])
    expect(violationLines(err, (id) => `Worker ${id}`)).toEqual([
      'Over maximum monthly hours (×16): Worker 7 2026-03-20 A',
      'Back-to-back shifts',
    ])
    expect(violationLines(new ApiError(409, 'X', 'm'), String)).toEqual([])
  })
  it('recognises the approved-edit 409 and maps it without a reload prompt', () => {
    const err = new ApiError(409, 'APPROVED_EDIT_NOT_ACKNOWLEDGED', 'approved')
    expect(isApprovedEditError(err)).toBe(true)
    expect(mapError(err)).toMatchObject({ title: 'Approved roster', action: 'none' })
  })
  it('a version conflict on edit still offers reload', () => {
    expect(mapError(new ApiError(409, 'VERSION_CONFLICT', 'm')).action).toBe('reload')
  })
})
