import { describe, expect, it } from 'vitest'
import type { AssignmentOut } from '../../api/schemas'
import { NO_FILTER, assignmentMatches, isFiltering, slotMatches } from './filter'

const a = (over: Partial<AssignmentOut> = {}): AssignmentOut => ({ worker_id: '1', date: '2026-10-05', shift: 'A', role: 'SCREENER', ...over })
const nameOf = (id: string) => ({ '1': 'Dana Levi', '2': 'Omer Cohen' })[id] ?? `#${id}`

describe('roster filter', () => {
  it('matches everything by default', () => {
    expect(isFiltering(NO_FILTER)).toBe(false)
    expect(assignmentMatches(NO_FILTER, a(), nameOf)).toBe(true)
  })
  it('matches worker names case-insensitively, ignoring surrounding spaces', () => {
    const f = { ...NO_FILTER, worker: '  levi ' }
    expect(isFiltering(f)).toBe(true)
    expect(assignmentMatches(f, a(), nameOf)).toBe(true)
    expect(assignmentMatches(f, a({ worker_id: '2' }), nameOf)).toBe(false)
  })
  it('combines role and shift with AND', () => {
    const f = { ...NO_FILTER, role: 'SCREENER' as const, shift: 'B' as const }
    expect(assignmentMatches(f, a({ shift: 'B' }), nameOf)).toBe(true)
    expect(assignmentMatches(f, a({ shift: 'A' }), nameOf)).toBe(false)
    expect(assignmentMatches(f, a({ shift: 'B', role: 'SUPERVISOR' }), nameOf)).toBe(false)
  })
  it('slots ignore the worker filter', () => {
    expect(slotMatches({ ...NO_FILTER, worker: 'nobody' }, 'A', 'SCREENER')).toBe(true)
    expect(slotMatches({ ...NO_FILTER, role: 'SUPERVISOR' }, 'A', 'SCREENER')).toBe(false)
  })
})
