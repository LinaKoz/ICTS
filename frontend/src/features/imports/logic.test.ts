import { describe, expect, it } from 'vitest'
import { ApiError } from '../../errors/ApiError'
import type { ImportConfirmOut, ImportRowOut } from '../../api/schemas'
import {
  MAX_FILE_BYTES, alreadyConfirmedOf, approvedCount, buildDecisions, confirmSummary, exportCounts, exportFilename, exportSummary,
  fileProblem, formatDiff, groupRows, stalePreviewOf, summaryLine, uploadErrorMessage,
} from './logic'

const row = (over: Partial<ImportRowOut> = {}): ImportRowOut => ({
  line: 2, national_id: '012345674', full_name: 'A', role: 'GENERAL_GUARD', status: 'ACTIVE', effective_month: '2026-09', contract: null,
  classification: 'NEW', contract_action: 'NONE', retroactive: false, changes: [], errors: [], export_row: false, worker_id: null, ...over,
})

describe('fileProblem', () => {
  it('requires a non-empty file within 1 MB', () => {
    expect(fileProblem(null)).toMatch(/choose/i)
    expect(fileProblem({ name: 'a.csv', size: 0 })).toMatch(/empty/i)
    expect(fileProblem({ name: 'a.csv', size: MAX_FILE_BYTES })).toBeNull()
    expect(fileProblem({ name: 'a.csv', size: MAX_FILE_BYTES + 1 })).toMatch(/1,048,576/)
  })
})

describe('grouping and decisions', () => {
  const rows = [
    row({ national_id: '1', classification: 'NEW' }),
    row({ national_id: '2', classification: 'CHANGED' }),
    row({ national_id: '3', classification: 'UNCHANGED' }),
    row({ national_id: '4', classification: 'INVALID' }),
    row({ national_id: '5', classification: 'NEW' }),
  ]
  it('groups by classification', () => {
    const g = groupRows(rows)
    expect(g.NEW.map((r) => r.national_id)).toEqual(['1', '5'])
    expect(g.CHANGED).toHaveLength(1)
    expect(g.UNCHANGED).toHaveLength(1)
    expect(g.INVALID).toHaveLength(1)
  })
  it('decides every actionable row and never unchanged or invalid ones', () => {
    expect(buildDecisions(rows, new Set())).toEqual({ '1': 'APPROVE', '2': 'APPROVE', '5': 'APPROVE' })
    expect(buildDecisions(rows, new Set(['2', '3']))).toEqual({ '1': 'APPROVE', '2': 'SKIP', '5': 'APPROVE' })
  })
  it('counts approved rows', () => {
    expect(approvedCount(rows, new Set())).toBe(3)
    expect(approvedCount(rows, new Set(['1', '2', '5']))).toBe(0)
  })
})

describe('text', () => {
  it('formats diffs with and without an old value', () => {
    expect(formatDiff({ field: 'full_name', old: 'Alice', new: 'Alicia' })).toBe('Name: Alice → Alicia')
    expect(formatDiff({ field: 'hourly_rate_ils', old: null, new: '40.00' })).toBe('Hourly rate: 40.00')
    expect(formatDiff({ field: 'weird', old: 'a', new: 'b' })).toBe('weird: a → b')
  })
  it('summarises counts', () => {
    expect(summaryLine({ counts: { new: 1, changed: 2, unchanged: 3, invalid: 4 } })).toBe('1 new worker, 2 changed, 3 unchanged, 4 invalid')
  })
  it('summarises a confirm result including revoked rosters', () => {
    const done = {
      import_id: 1, status: 'CONFIRMED', affected_rosters: [], invalidates_approved: true, locked_violations: [],
      result: { created_workers: 1, updated_workers: 0, contract_versions_created: 2, unchanged: 5, invalid: 1, skipped: 2, revoked_rosters: ['2026-09'] },
    } as ImportConfirmOut
    const s = confirmSummary(done)
    expect(s.lines).toEqual([
      '1 worker created', '0 workers updated', '2 contract versions created', '5 unchanged', '2 skipped by you', '1 invalid, not applied',
    ])
    expect(s.revoked).toEqual(['2026-09'])
  })
})

describe('errors', () => {
  const err = (status: number, code: string, details: unknown = null) => new ApiError(status, code, 'm', details)
  it('extracts the fresh preview of a stale confirm', () => {
    const preview = { id: 9 }
    expect(stalePreviewOf(err(409, 'STALE_PREVIEW', { reasons: ['x'], preview }))).toBe(preview)
    expect(stalePreviewOf(err(409, 'STALE_PREVIEW', null))).toBeNull()
    expect(stalePreviewOf(err(409, 'ALREADY_CONFIRMED', { preview }))).toBeNull()
    expect(stalePreviewOf(new Error('x'))).toBeNull()
  })
  it('extracts the stored result of a repeated confirm', () => {
    const stored = { import_id: 1, result: {} }
    expect(alreadyConfirmedOf(err(409, 'ALREADY_CONFIRMED', stored))).toBe(stored)
    expect(alreadyConfirmedOf(err(409, 'ALREADY_CONFIRMED', null))).toBeNull()
    expect(alreadyConfirmedOf(err(409, 'STALE_PREVIEW', stored))).toBeNull()
  })
  it('explains upload rejections', () => {
    expect(uploadErrorMessage(err(413, 'FILE_TOO_LARGE'))).toMatch(/1 MB/)
    expect(uploadErrorMessage(err(413, 'TOO_MANY_ROWS'))).toMatch(/5,000/)
    expect(uploadErrorMessage(err(400, 'MISSING_COLUMNS', { missing: ['full_name', 'role'] }))).toMatch(/full_name, role/)
    expect(uploadErrorMessage(err(400, 'DUPLICATE_COLUMN', { columns: ['role'] }))).toMatch(/role/)
    expect(uploadErrorMessage(err(400, 'INVALID_ENCODING'))).toMatch(/UTF-8/)
    expect(uploadErrorMessage(err(500, 'OTHER'))).toBeNull()
    expect(uploadErrorMessage('x')).toBeNull()
  })
})

describe('export', () => {
  it('reads counts from the response headers', () => {
    const h = new Headers({ 'X-Worker-Count': '23', 'X-No-Contract-Count': '2' })
    expect(exportCounts(h)).toEqual({ workers: 23, noContract: 2 })
    expect(exportCounts(new Headers())).toBeNull()
    expect(exportSummary({ workers: 23, noContract: 2 })).toMatch(/23 workers exported; 2 without a contract/)
    expect(exportSummary({ workers: 1, noContract: 0 })).toBe('1 worker exported.')
    expect(exportFilename('2026-09')).toBe('workers-2026-09.csv')
  })
})
