import { useState } from 'react'
import { useAuth } from '../../auth/authContext'
import { Modal } from '../../components/Modal'
import { ErrorPanel } from '../../errors/ErrorPanel'
import { mapError } from '../../errors/mapError'
import type { ApprovalEventOut, RosterOut } from '../../api/schemas'
import { useApprovalPreview, useApprove, useRevoke } from './api'
import { buildApproveBody, canSubmitApproval, describeRevocation, shortageLines } from './approval'
import { nameLookup, violationLabel } from './names'
import { violationLines } from './edit'

const fmt = (iso: string) => new Date(iso).toLocaleString('en-GB')

function HistoryItem({ ev, nameOf }: { ev: ApprovalEventOut; nameOf: (id: string) => string }) {
  const revocation = describeRevocation(ev)
  const ack = ev.acknowledged_warnings
  const lines = ack ? shortageLines(ack.coverage_gaps, ack.hour_shortfalls, nameOf) : []
  return (
    <li className="approval-event">
      <div>Approved by <strong>{ev.approved_by}</strong> at {fmt(ev.approved_at)} <span className="muted">(roster version {ev.roster_version})</span></div>
      {ev.reason && <div>Reason: {ev.reason}</div>}
      {ack && (
        <details>
          <summary>{lines.length} shortage{lines.length === 1 ? '' : 's'} acknowledged</summary>
          <ul>{lines.map((l) => <li key={l}>{l}</li>)}</ul>
        </details>
      )}
      {ev.revoked_at && (
        <div className="revoked">
          Revoked at {fmt(ev.revoked_at)}{ev.revoked_by ? ` by ${ev.revoked_by}` : ''}: {revocation}
          {ev.revoke_reason && <div className="revoke-reason">Reason: {ev.revoke_reason}</div>}
        </div>
      )}
    </li>
  )
}

/** Approval status, the manager's approve/revoke controls (P11, P12) and the audit trail. */
export function ApprovalPanel({ month, roster }: { month: string; roster: RosterOut }) {
  const { user } = useAuth()
  const isManager = user?.app_role === 'MANAGER'
  const nameOf = nameLookup(roster.workers)
  const draft = roster.status === 'DRAFT' && !roster.is_history
  const preview = useApprovalPreview(month, draft)
  const approve = useApprove(month)
  const revoke = useRevoke(month)
  const [ack, setAck] = useState(false)
  const [reason, setReason] = useState('')
  const [confirmRevoke, setConfirmRevoke] = useState(false)
  const [revokeReason, setRevokeReason] = useState('')

  const p = preview.data
  const lines = p ? shortageLines(p.coverage_gaps, p.hour_shortfalls, nameOf) : []
  // A changed shortage set invalidates a ticked acknowledgement: it must match what is shown.
  const ackKey = p?.warnings_fingerprint ?? ''
  const [ackFor, setAckFor] = useState('')
  const acknowledged = ack && ackFor === ackKey
  const hardLines = approve.error ? violationLines(approve.error, nameOf) : []

  function submit() {
    if (!p) return
    approve.mutate(buildApproveBody(p, acknowledged, reason), { onSuccess: () => { setAck(false); setReason('') } })
  }

  return (
    <section className="panel approval" aria-label="Approval">
      <h3>Approval</h3>
      {roster.is_history && <p className="muted">Past months are read-only history and are not approved.</p>}
      {roster.status === 'APPROVED' && (
        <>
          <p>Approved. Editing or regenerating it returns it to draft.</p>
          {isManager ? (
            <div className="actions">
              <button disabled={revoke.isPending} onClick={() => { revoke.reset(); setRevokeReason(''); setConfirmRevoke(true) }}>Revoke approval</button>
            </div>
          ) : <p className="muted">Only a manager can revoke an approval.</p>}
          {confirmRevoke && (
            <Modal label="Revoke approval" onClose={() => setConfirmRevoke(false)}>
              <h3>Revoke the approval?</h3>
              <p>The roster returns to draft. No assignment changes; the approval stays in the history with your reason.</p>
              <label className="field">Reason (required)
                <textarea rows={3} maxLength={500} autoFocus value={revokeReason} onChange={(e) => setRevokeReason(e.target.value)} placeholder="Why is the approval being withdrawn?" />
              </label>
              {revoke.isError && <ErrorPanel error={revoke.error} onReload={() => { revoke.reset(); setConfirmRevoke(false) }} />}
              <div className="actions">
                <button className="primary" disabled={revoke.isPending || revokeReason.trim() === ''}
                  onClick={() => revoke.mutate({ expected_version: roster.version, reason: revokeReason.trim() }, { onSuccess: () => setConfirmRevoke(false) })}>
                  {revoke.isPending ? 'Revoking…' : 'Revoke approval'}
                </button>
                <button onClick={() => setConfirmRevoke(false)}>Cancel</button>
              </div>
            </Modal>
          )}
        </>
      )}
      {draft && !isManager && <p className="muted">Draft. Only a manager can approve a roster.</p>}
      {draft && isManager && preview.isPending && <p className="muted">Checking the roster…</p>}
      {draft && preview.isError && <ErrorPanel error={preview.error} onRetry={() => preview.refetch()} />}
      {draft && isManager && p && (
        <>
          {p.hard_violations.length > 0 ? (
            <div className="panel panel-error" role="alert">
              <strong>Cannot approve: {p.hard_violations.length} hard violation{p.hard_violations.length === 1 ? '' : 's'}</strong>
              <p className="muted">Hard violations cannot be acknowledged. Fix them first.</p>
              <ul>{p.hard_violations.map((v, i) => (
                <li key={i}>{violationLabel(v.code)}: {v.assignments.map((a) => `${nameOf(a.worker_id)} ${a.date} ${a.shift}`).join('; ')}</li>
              ))}</ul>
            </div>
          ) : p.requires_acknowledgement ? (
            <div className="ack">
              <strong>{lines.length} shortage{lines.length === 1 ? '' : 's'} to acknowledge</strong>
              <ul className="shortages">{lines.map((l) => <li key={l}>{l}</li>)}</ul>
              <label className="check">
                <input type="checkbox" checked={acknowledged} onChange={(e) => { setAck(e.target.checked); setAckFor(ackKey) }} />
                I acknowledge the shortages listed above
              </label>
              <label className="field">Reason
                <textarea rows={2} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Why approve with these shortages?" />
              </label>
            </div>
          ) : <p>No coverage gaps or hour shortfalls.</p>}
          {p.can_approve && (
            <div className="actions">
              <button className="primary" disabled={approve.isPending || !canSubmitApproval(p, acknowledged, reason)} onClick={submit}>
                {approve.isPending ? 'Approving…' : 'Approve roster'}
              </button>
            </div>
          )}
        </>
      )}
      {hardLines.length > 0 ? (
        <div className="panel panel-error" role="alert"><strong>{mapError(approve.error).title}</strong>
          <ul>{hardLines.map((l) => <li key={l}>{l}</li>)}</ul></div>
      ) : approve.isError && <ErrorPanel error={approve.error} onReload={() => { approve.reset(); preview.refetch() }} />}

      <h4>Approval history ({roster.approval_history.length})</h4>
      {roster.approval_history.length === 0
        ? <p className="muted">This roster has never been approved.</p>
        : <ol className="approval-history">{roster.approval_history.map((ev) => <HistoryItem key={ev.id} ev={ev} nameOf={nameOf} />)}</ol>}
    </section>
  )
}
