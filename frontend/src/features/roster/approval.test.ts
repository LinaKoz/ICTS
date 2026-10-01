import { describe, expect, it } from 'vitest'
import type { ApprovalPreviewOut } from '../../api/schemas'
import { buildApproveBody, canSubmitApproval, describeRef, describeRevocation, openApprovalId, shortageLines } from './approval'

const preview = (over: Partial<ApprovalPreviewOut> = {}): ApprovalPreviewOut => ({
  version: 3, status: 'DRAFT', is_history: false, hard_violations: [], coverage_gaps: [], hour_shortfalls: [],
  warnings_fingerprint: 'fp', requires_acknowledgement: false, can_approve: true, ...over,
})

describe('describeRevocation', () => {
  it('labels every cause and its reference', () => {
    expect(describeRevocation({ revoke_cause: null, revoke_ref: null })).toBeNull()
    expect(describeRevocation({ revoke_cause: 'EDIT', revoke_ref: null })).toBe('roster edited')
    expect(describeRevocation({ revoke_cause: 'CONTRACT_CHANGE', revoke_ref: 'contract_version:92', revoke_ref_label: 'Worker 05, contract v3 from 10/2026' }))
      .toBe('contract change (Worker 05, contract v3 from 10/2026)')
    expect(describeRevocation({ revoke_cause: 'REGENERATE', revoke_ref: null })).toBe('roster regenerated')
    expect(describeRevocation({ revoke_cause: 'CONTRACT_CHANGE', revoke_ref: 'contract_version:12' })).toBe('contract change (contract version 12)')
    expect(describeRevocation({ revoke_cause: 'CONTRACT_CHANGE', revoke_ref: 'import:4' })).toBe('contract change (CSV import 4)')
    expect(describeRevocation({ revoke_cause: 'WORKER_CHANGE', revoke_ref: 'worker:7' })).toBe('worker role/status change (worker 7)')
    expect(describeRevocation({ revoke_cause: 'MANUAL', revoke_ref: null })).toBe('revoked by a manager')
  })
  it('passes an unknown ref through', () => {
    expect(describeRef('other:1')).toBe('other:1')
    expect(describeRef(undefined)).toBeNull()
  })
})

describe('shortageLines', () => {
  it('lists only real shortages, gaps first', () => {
    const lines = shortageLines(
      [
        { date: '2099-01-01', shift: 'A', role: 'GENERAL_GUARD', required: 2, assigned: 2, missing: 0, proven_missing: 0, locked: false },
        { date: '2099-01-01', shift: 'B', role: 'SUPERVISOR', required: 1, assigned: 0, missing: 1, proven_missing: 1, locked: true },
      ],
      [{ worker_id: '5', min_hours: 40, assigned_hours: 16, missing_hours: 24 }],
      (id) => `Worker ${id}`,
    )
    expect(lines).toEqual(['2099-01-01 B supervisor: 0/1 (past)', 'Worker 5: 16/40 h (24 h below minimum)'])
  })
})

describe('canSubmitApproval / buildApproveBody', () => {
  it('a clean roster needs nothing', () => {
    expect(canSubmitApproval(preview(), false, '')).toBe(true)
    expect(buildApproveBody(preview(), false, '')).toEqual({ expected_version: 3, acknowledge_warnings: false, warnings_fingerprint: 'fp' })
  })
  it('shortages need the acknowledgement and a non-blank reason', () => {
    const p = preview({ requires_acknowledgement: true })
    expect(canSubmitApproval(p, false, 'why')).toBe(false)
    expect(canSubmitApproval(p, true, '   ')).toBe(false)
    expect(canSubmitApproval(p, true, ' why ')).toBe(true)
    expect(buildApproveBody(p, true, ' why ')).toEqual({
      expected_version: 3, acknowledge_warnings: true, reason: 'why', warnings_fingerprint: 'fp',
    })
  })
  it('hard violations can never be submitted', () => {
    expect(canSubmitApproval(preview({ can_approve: false, requires_acknowledgement: true }), true, 'why')).toBe(false)
  })
})

describe('openApprovalId', () => {
  it('is the newest unrevoked approval, which a manual revoke is bound to', () => {
    const history = [{ id: 2, revoked_at: null }, { id: 1, revoked_at: '2099-01-02T10:00:00Z' }] // newest first
    expect(openApprovalId({ approval_history: history })).toBe(2)
  })
  it('is null when every approval was revoked', () => {
    expect(openApprovalId({ approval_history: [{ id: 1, revoked_at: '2099-01-02T10:00:00Z' }] })).toBeNull()
    expect(openApprovalId({ approval_history: [] })).toBeNull()
  })
})
