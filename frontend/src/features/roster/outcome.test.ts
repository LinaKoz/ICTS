import { describe, expect, it } from 'vitest'
import type { GenerateOutcomeOut } from '../../api/schemas'
import { describeOutcome } from './outcome'

const base: GenerateOutcomeOut = { outcome: 'solved', warnings: [] }
const cov = (status: 'OPTIMAL' | 'FEASIBLE', lower_bound: number, locked_uncovered = 0) => ({
  status, lower_bound, locked_uncovered, total_uncovered: lower_bound,
})

describe('describeOutcome', () => {
  it('optimal roster', () => {
    const r = describeOutcome({ ...base, lexicographically_optimal: true, coverage: cov('OPTIMAL', 0) })
    expect(r).toEqual({ kind: 'ok', messages: ['Best possible roster'] })
  })
  it('proven coverage gaps subtract locked ones', () => {
    const r = describeOutcome({ ...base, lexicographically_optimal: true, coverage: cov('OPTIMAL', 5, 2) })
    expect(r.messages).toContain('At least 3 upcoming positions cannot be filled with current contracts')
    expect(r.kind).toBe('warning')
  })
  it('does not report locked-only gaps as upcoming', () => {
    const r = describeOutcome({ ...base, lexicographically_optimal: true, coverage: cov('OPTIMAL', 2, 2) })
    expect(r.messages).toEqual(['Best possible roster'])
  })
  it('feasible coverage omits the bound when L = 0', () => {
    expect(describeOutcome({ ...base, coverage: cov('FEASIBLE', 0) }).messages).toEqual(['Best found within the time limit'])
    expect(describeOutcome({ ...base, coverage: cov('FEASIBLE', 1) }).messages).toEqual([
      'Best found within the time limit; at least 1 upcoming position cannot be filled',
    ])
  })
  it('min hours feasible', () => {
    const r = describeOutcome({ ...base, coverage: cov('OPTIMAL', 0), min_hours: { status: 'FEASIBLE', total_shortfall: 8 } })
    expect(r.messages).toContain('Minimum hours not proven optimal within the time limit')
  })
  it('failure outcomes', () => {
    expect(describeOutcome({ ...base, outcome: 'no_solution_within_limit' }).messages).toEqual([
      'No roster found in time; nothing was changed',
    ])
    expect(describeOutcome({ ...base, outcome: 'engine_error', message: 'x' }).kind).toBe('error')
  })
})
