import type { ApprovalEventOut, ApprovalPreviewOut, ApproveRequest, CoverageGapOut, HourShortfallOut } from '../../api/schemas'
import { roleLabel } from '../workers/labels'

type Cause = NonNullable<ApprovalEventOut['revoke_cause']>

/** Exhaustive on purpose: a new backend cause fails the typecheck until it gets a label. */
const CAUSE_LABEL: Record<Cause, string> = {
  EDIT: 'roster edited',
  REGENERATE: 'roster regenerated',
  CONTRACT_CHANGE: 'contract change',
  WORKER_CHANGE: 'worker role/status change',
  MANUAL: 'revoked by a manager',
}

/** "roster edited", "contract change (Alice Guard, contract v3 from 10/2026)". The server's
 * `revoke_ref_label` wins; the raw ref (`contract_version:{id}`, `worker:{id}`, `import:{id}`) is the fallback. */
export function describeRevocation(ev: Pick<ApprovalEventOut, 'revoke_cause' | 'revoke_ref' | 'revoke_ref_label'>): string | null {
  if (!ev.revoke_cause) return null
  const label = CAUSE_LABEL[ev.revoke_cause] ?? ev.revoke_cause
  const ref = ev.revoke_ref_label ?? describeRef(ev.revoke_ref)
  return ref ? `${label} (${ref})` : label
}

export function describeRef(ref: string | null | undefined): string | null {
  if (!ref) return null
  const [kind, id] = ref.split(':')
  if (kind === 'contract_version') return `contract version ${id}`
  if (kind === 'worker') return `worker ${id}`
  if (kind === 'import') return `CSV import ${id}`
  return ref
}

/** One human line per soft shortage, in the order shown to (and fingerprinted for) the manager. */
export function shortageLines(
  gaps: CoverageGapOut[],
  shortfalls: HourShortfallOut[],
  nameOf: (id: string) => string,
): string[] {
  const gapLines = gaps
    .filter((g) => g.missing > 0)
    .map((g) => `${g.date} ${g.shift} ${roleLabel(g.role).toLowerCase()}: ${g.assigned}/${g.required}${g.locked ? ' (past)' : ''}`)
  const hourLines = shortfalls
    .filter((s) => s.missing_hours > 0)
    .map((s) => `${nameOf(s.worker_id)}: ${s.assigned_hours}/${s.min_hours} h (${s.missing_hours} h below minimum)`)
  return [...gapLines, ...hourLines]
}

/** Whether the Approve button may be pressed. Hard violations can never be acknowledged (P11). */
export function canSubmitApproval(preview: ApprovalPreviewOut, acknowledged: boolean, reason: string): boolean {
  if (!preview.can_approve) return false
  if (!preview.requires_acknowledgement) return true
  return acknowledged && reason.trim().length > 0
}

/** Request body: acknowledgement fields only when shortages exist; the fingerprint is the one shown. */
export function buildApproveBody(preview: ApprovalPreviewOut, acknowledged: boolean, reason: string): ApproveRequest {
  if (!preview.requires_acknowledgement) {
    return { expected_version: preview.version, acknowledge_warnings: false, warnings_fingerprint: preview.warnings_fingerprint }
  }
  return {
    expected_version: preview.version,
    acknowledge_warnings: acknowledged,
    reason: reason.trim(),
    warnings_fingerprint: preview.warnings_fingerprint,
  }
}

/** Id of the roster's current (unrevoked) approval, the one a manual revoke targets; history is oldest first. */
export function openApprovalId(roster: { approval_history: Pick<ApprovalEventOut, 'id' | 'revoked_at'>[] }): number | null {
  return roster.approval_history.findLast((ev) => ev.revoked_at == null)?.id ?? null
}
