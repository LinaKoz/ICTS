import { QueryClient } from '@tanstack/react-query'
import { describe, expect, it } from 'vitest'
import type { AssignmentOut, ViolationOut } from '../../api/schemas'
import { adjacentMonths, assignmentsKey, invalidateAfterEdit, rosterKey } from './api'
import { buildIndex, violationKey, type MonthData } from './calendarData'
import { replacementTargets } from './edit'

const asg = (worker_id: string, date: string, shift: 'A' | 'B' | 'C'): AssignmentOut => ({ worker_id, date, shift, role: 'GENERAL_GUARD' })
const monthData = (violations: ViolationOut[]): MonthData => ({ assignments: [], gaps: [], costs: null, workers: [], violations, freeFrom: null })

describe('fix panel replacement targets', () => {
  const fixable = [{ id: 1 }, { id: 2 }, { id: 3 }]
  it('loads no replacements until an assignment is picked', () => {
    expect(replacementTargets(fixable, null)).toEqual([])
  })
  it('loads replacements for the picked assignment only', () => {
    expect(replacementTargets(fixable, 2)).toEqual([{ id: 2 }])
  })
})

describe('cross-month violations', () => {
  const last = asg('7', '2026-10-31', 'C')
  const first = asg('7', '2026-11-01', 'A')
  const adjacency = (assignments: AssignmentOut[]): ViolationOut => ({ code: 'ADJACENT_SHIFTS', key: ['7', '2026-10-31', 'C'], magnitude: 1, assignments })

  it('shows a boundary violation once when both months report it, in either order', () => {
    const index = buildIndex([
      { month: '2026-10', status: 'ready', data: monthData([adjacency([last, first])]) },
      { month: '2026-11', status: 'ready', data: monthData([adjacency([first, last])]) },
    ])
    expect(index.warningsAt('2026-10-31', 'C')).toHaveLength(1)
    expect(index.warningsAt('2026-11-01', 'A')).toHaveLength(1)
    expect(index.warningsAt('2026-10-31')).toHaveLength(1)
  })

  it('keeps distinct violations on the same cell', () => {
    const maxHours: ViolationOut = { code: 'MAX_HOURS', key: ['7'], magnitude: 8, assignments: [last] }
    const index = buildIndex([
      { month: '2026-10', status: 'ready', data: monthData([adjacency([last, first]), maxHours]) },
      { month: '2026-11', status: 'ready', data: monthData([adjacency([first, last])]) },
    ])
    const keys = index.warningsAt('2026-10-31', 'C').map(violationKey)
    expect(keys).toHaveLength(2)
    expect(new Set(keys).size).toBe(2)
  })
})

describe('edit invalidation', () => {
  it('finds neighbouring months across year boundaries', () => {
    expect(adjacentMonths('2026-10')).toEqual(['2026-09', '2026-11'])
    expect(adjacentMonths('2026-12')).toEqual(['2026-11', '2027-01'])
    expect(adjacentMonths('2027-01')).toEqual(['2026-12', '2027-02'])
  })

  it('marks the edited month and both neighbours stale, and leaves other months alone', async () => {
    const qc = new QueryClient()
    for (const m of ['2026-11', '2026-12', '2027-01', '2027-02']) {
      qc.setQueryData(rosterKey(m), null)
      qc.setQueryData(assignmentsKey(m), [])
    }
    await invalidateAfterEdit(qc, '2026-12')
    const stale = (key: readonly unknown[]) => qc.getQueryState(key)?.isInvalidated
    for (const m of ['2026-11', '2026-12', '2027-01']) {
      expect(stale(rosterKey(m))).toBe(true)
      expect(stale(assignmentsKey(m))).toBe(true)
    }
    expect(stale(rosterKey('2027-02'))).toBe(false)
  })
})
