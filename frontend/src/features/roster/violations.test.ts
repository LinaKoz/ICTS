import { describe, expect, it } from 'vitest'
import type { ViolationOut } from '../../api/schemas'
import { violatingWorkers, violationTarget } from './calendarData'

const v = (assignments: { worker_id: string; date: string; shift: 'A' | 'B' | 'C' }[]): ViolationOut =>
  ({ code: 'ADJACENT_SHIFTS', key: [], magnitude: 1, assignments: assignments.map((a) => ({ ...a, role: 'GENERAL_GUARD' })) }) as ViolationOut

describe('violatingWorkers', () => {
  it('marks only the workers whose assignment in this shift is part of a violation', () => {
    const warnings = [
      v([{ worker_id: '8', date: '2026-11-30', shift: 'C' }, { worker_id: '8', date: '2026-12-01', shift: 'A' }]),
      v([{ worker_id: '3', date: '2026-11-30', shift: 'C' }]),
    ]
    expect([...violatingWorkers(warnings, '2026-11-30', 'C')].sort()).toEqual(['3', '8'])
    expect([...violatingWorkers(warnings, '2026-12-01', 'A')]).toEqual(['8'])
    expect(violatingWorkers(warnings, '2026-11-30', 'B').size).toBe(0)
  })
})

describe('violationTarget', () => {
  it('goes to the earliest assignment, preferring the roster month', () => {
    const cross = v([{ worker_id: '8', date: '2026-12-01', shift: 'A' }, { worker_id: '8', date: '2026-11-30', shift: 'C' }])
    expect(violationTarget(cross, '2026-11')).toEqual({ date: '2026-11-30', shift: 'C' })
    expect(violationTarget(cross, '2026-12')).toEqual({ date: '2026-12-01', shift: 'A' })
    const sameDay = v([{ worker_id: '3', date: '2026-11-10', shift: 'C' }, { worker_id: '3', date: '2026-11-10', shift: 'A' }])
    expect(violationTarget(sameDay, '2026-11')).toEqual({ date: '2026-11-10', shift: 'A' })
    expect(violationTarget(v([]), '2026-11')).toBeNull()
  })
})
