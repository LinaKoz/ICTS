import { describe, expect, it } from 'vitest'
import { ApiError } from '../../errors/ApiError'
import type { AffectedRosterOut } from '../../api/schemas'
import {
  availabilitySummary, diffPatch, fieldErrors, formFromContract, isStalePreview, isWorkerInUse, lockedViolationWarnings,
  nationalIdError, normalizeAvailability, previewHeadline, rosterEffect, roleStatusChangeLines, toContractInput, toggleToken, validateContractForm, validateWorkerForm,
} from './logic'

const roster = (over: Partial<AffectedRosterOut> = {}): AffectedRosterOut => ({
  month: '2026-09', roster_id: 1, status: 'APPROVED', version: 1, is_history: false, worker_ids: ['1'], assignment_count: 2,
  new_violations: [], locked_violations: [], revokes_approval: false, ...over,
})
const locked = { month: '2026-09', worker_id: '1', worker_name: 'A', date: '2026-09-10', shift: 'A', code: 'UNAVAILABLE', magnitude: 1 } as const

describe('availability', () => {
  it('normalizes to weekday then shift order and drops unknown/duplicate tokens', () => {
    expect(normalizeAvailability(['SUN:B', 'MON:C', 'MON:A', 'MON:A', 'XXX:A', 'TUE:D'])).toEqual(['MON:A', 'MON:C', 'SUN:B'])
  })
  it('toggles a token on and off', () => {
    expect(toggleToken(['MON:A'], 'MON:B')).toEqual(['MON:A', 'MON:B'])
    expect(toggleToken(['MON:A', 'MON:B'], 'MON:A')).toEqual(['MON:B'])
  })
  it('summarises', () => {
    expect(availabilitySummary([])).toBe('none')
    expect(availabilitySummary(['MON:A', 'MON:B', 'FRI:C'])).toBe('Mon AB · Fri C')
    expect(availabilitySummary(normalizeAvailability(['MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT', 'SUN'].flatMap((d) => ['A', 'B', 'C'].map((s) => `${d}:${s}`))))).toBe('all shifts, every day')
  })
})

describe('contract form', () => {
  const ok = { effective_month: '2026-09', hourly_rate_ils: '45.50', min_hours: '0', max_hours: '160', availability: ['MON:A'] }
  it('accepts a valid form and builds the request', () => {
    expect(validateContractForm(ok)).toEqual({})
    expect(toContractInput({ ...ok, availability: ['TUE:A', 'MON:A'] })).toEqual({
      effective_month: '2026-09', hourly_rate_ils: '45.50', min_hours: 0, max_hours: 160, availability: ['MON:A', 'TUE:A'],
    })
  })
  it.each([
    [{ hourly_rate_ils: '0' }, 'hourly_rate_ils'],
    [{ hourly_rate_ils: '1.234' }, 'hourly_rate_ils'],
    [{ hourly_rate_ils: '' }, 'hourly_rate_ils'],
    [{ min_hours: '-1' }, 'min_hours'],
    [{ max_hours: '745' }, 'max_hours'],
    [{ min_hours: '100', max_hours: '50' }, 'max_hours'],
    [{ availability: [] }, 'availability'],
    [{ effective_month: '' }, 'effective_month'],
  ])('rejects %j', (over, field) => {
    expect(Object.keys(validateContractForm({ ...ok, ...over }))).toContain(field)
  })
  it('pre-fills from the version being revised', () => {
    const c = { hourly_rate_ils: '40.00', min_hours: 8, max_hours: 120, availability: ['WED:B', 'MON:A'] } as Parameters<typeof formFromContract>[0]
    expect(formFromContract(c, '2026-10')).toEqual({ effective_month: '2026-10', hourly_rate_ils: '40.00', min_hours: '8', max_hours: '120', availability: ['MON:A', 'WED:B'] })
    expect(formFromContract(null, '2026-10').availability).toEqual([])
  })
})

describe('errors', () => {
  it('extracts inline field errors from a 422', () => {
    const e = new ApiError(422, 'VALIDATION_ERROR', 'bad', [
      { loc: ['body', 'national_id'], message: 'national ID fails the Israeli ID checksum', type: 'national_id' },
      { loc: ['body'], message: 'Value error, min_hours must not exceed max_hours', type: 'value_error' },
      { loc: ['body', 'national_id'], message: 'second one is ignored', type: 'x' },
    ])
    expect(fieldErrors(e)).toEqual({ national_id: 'national ID fails the Israeli ID checksum', body: 'min_hours must not exceed max_hours' })
    expect(fieldErrors(new ApiError(409, 'X', 'm'))).toEqual({})
    expect(fieldErrors(new Error('x'))).toEqual({})
  })
  it('recognises the 409 codes the UI handles specially', () => {
    expect(isWorkerInUse(new ApiError(409, 'WORKER_IN_USE', 'm'))).toBe(true)
    expect(isWorkerInUse(new ApiError(409, 'VERSION_CONFLICT', 'm'))).toBe(false)
    expect(isStalePreview(new ApiError(409, 'STALE_PREVIEW', 'm'))).toBe(true)
    expect(isStalePreview(new ApiError(422, 'STALE_PREVIEW', 'm'))).toBe(false)
  })
})

describe('impact text (P2)', () => {
  it('warns per roster about violations in started shifts, mentioning a revoked approval', () => {
    const w = lockedViolationWarnings([
      roster({ locked_violations: [locked, locked, locked], revokes_approval: true }),
      roster({ month: '2026-10', new_violations: [] }),
    ])
    expect(w).toEqual([
      'Approval of 2026-09 will be revoked. 3 violations fall in shifts that have already started and cannot be fixed by editing assignments. ' +
        'The roster 2026-09 will stay unapproved unless the contract data is corrected.',
    ])
  })
  it('is empty when violations only affect free shifts', () => {
    expect(lockedViolationWarnings([roster({ new_violations: [{} as never], revokes_approval: true })])).toEqual([])
  })
  it('singular wording and no revoke sentence for a draft roster', () => {
    expect(lockedViolationWarnings([roster({ status: 'DRAFT', locked_violations: [locked] })])[0]).toMatch(/^1 violation falls in shifts/)
  })
  it('describes each roster effect', () => {
    expect(rosterEffect(roster({ is_history: true }))).toMatch(/History/)
    expect(rosterEffect(roster())).toBe('No new violations')
    expect(rosterEffect(roster({ new_violations: [{} as never], revokes_approval: true }))).toBe('1 new violation; approval revoked, back to draft')
  })
  it('headlines', () => {
    expect(previewHeadline({ unchanged: true, retroactive: false, affected_rosters: [] })).toMatch(/no new version/)
    expect(previewHeadline({ unchanged: false, retroactive: true, affected_rosters: [roster()] })).toBe('Retroactive change. 1 roster affected.')
    expect(previewHeadline({ unchanged: false, retroactive: false, affected_rosters: [] })).toBe('No roster is affected.')
  })
})

describe('worker edits', () => {
  const w = { national_id: '111111118', full_name: 'Alice', role: 'GENERAL_GUARD', status: 'ACTIVE', row_version: 3 } as const
  it('builds a minimal PATCH with the loaded version, or null when nothing changed', () => {
    expect(diffPatch(w, { ...w })).toBeNull()
    expect(diffPatch(w, { ...w, full_name: ' Alice ' })).toBeNull()
    expect(diffPatch(w, { ...w, status: 'INACTIVE' })).toEqual({ expected_version: 3, status: 'INACTIVE' })
    expect(diffPatch(w, { ...w, full_name: 'Al', role: 'SCREENER' })).toEqual({ expected_version: 3, full_name: 'Al', role: 'SCREENER' })
  })
  it('asks for confirmation only for role/status changes', () => {
    expect(roleStatusChangeLines(w, { full_name: 'x' } as never)).toEqual([])
    expect(roleStatusChangeLines(w, { status: 'INACTIVE' })).toEqual(['Status active to inactive'])
    expect(roleStatusChangeLines(w, { status: 'ACTIVE', role: 'SUPERVISOR' })).toEqual(['Role general guard to supervisor'])
  })
})

describe('nationalIdError', () => {
  it('accepts a valid Israeli ID', () => {
    expect(nationalIdError('000000018')).toBeNull()
    expect(nationalIdError('111111118')).toBeNull()
  })
  it('rejects wrong length and non-digits, hinting at dropped zeros', () => {
    expect(nationalIdError('')).toMatch(/exactly 9 digits/)
    expect(nationalIdError('12345678')).toMatch(/got 8.*leading zeros/)
    expect(nationalIdError('12345678a')).not.toMatch(/leading zeros/)
    expect(nationalIdError('1234567890')).toMatch(/exactly 9 digits/)
  })
  it('rejects a bad checksum', () => {
    expect(nationalIdError('123456789')).toMatch(/checksum/)
  })
})

describe('validateWorkerForm', () => {
  it('returns no errors for a valid form and trims input', () => {
    expect(validateWorkerForm({ national_id: ' 000000018 ', full_name: ' Alice ' })).toEqual({})
  })
  it('flags a bad ID and blank name', () => {
    expect(Object.keys(validateWorkerForm({ national_id: '123', full_name: '  ' })).sort()).toEqual(['full_name', 'national_id'])
  })
})
