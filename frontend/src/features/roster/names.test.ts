import { describe, expect, it } from 'vitest'
import { ils, nameLookup, shiftCostLookup, violationLabel } from './names'

describe('roster display helpers', () => {
  it('resolves worker names and falls back to the id', () => {
    const name = nameLookup([{ worker_id: '7', full_name: 'Dana Levi', role: 'SCREENER', status: 'ACTIVE' }])
    expect(name('7')).toBe('Dana Levi')
    expect(name('99')).toBe('#99')
    expect(nameLookup(null)('1')).toBe('#1')
  })
  it('finds per-shift costs by cell', () => {
    const cost = shiftCostLookup([{ date: '2026-10-03', shift: 'B', amount_ils: '480.00', unknown_cost_assignments: 1 }])
    expect(cost('2026-10-03', 'B')?.amount_ils).toBe('480.00')
    expect(cost('2026-10-03', 'A')).toBeUndefined()
  })
  it('labels the new no-contract violation code', () => {
    expect(violationLabel('NO_CONTRACT_FOR_MONTH')).toBe('No contract for this month')
  })
  it('formats shekels', () => {
    expect(ils('1234.5')).toBe('₪1,234.50')
  })
})
