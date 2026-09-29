import { useState } from 'react'
import { ErrorPanel } from '../../errors/ErrorPanel'
import type { AssignmentOut, RosterOut, ViolationOut } from '../../api/schemas'
import { useMoveAssignment, useRemoveAssignment, useReplacements } from './api'
import { EditErrors } from './EditPanel'
import { isLockedShift, needsApprovalAck } from './edit'
import { nameLookup, violationLabel } from './names'

interface FixProps {
  month: string
  roster: RosterOut
  idOf: (a: AssignmentOut) => number | undefined
}

function AssignmentFixes({ month, roster, assignment, id, ack, onDone }: {
  month: string; roster: RosterOut; assignment: AssignmentOut; id: number; ack: boolean; onDone: () => void
}) {
  const nameOf = nameLookup(roster.workers)
  const options = useReplacements(month, id, true)
  const move = useMoveAssignment(month)
  const remove = useRemoveAssignment(month)
  const pending = move.isPending || remove.isPending
  const ackNeeded = needsApprovalAck(roster.status) && !ack
  const common = { expected_version: roster.version, acknowledge_approved_edit: ack }

  return (
    <div className="fix-options">
      <p className="muted">{nameOf(assignment.worker_id)}, {assignment.date} shift {assignment.shift}</p>
      {options.isPending && <p><span className="spinner" /> Loading…</p>}
      {options.isError && <ErrorPanel error={options.error} onRetry={() => options.refetch()} />}
      {options.data?.candidates.length === 0 && (
        <p className="muted">No worker can take this slot without breaking a rule.</p>
      )}
      {options.data?.candidates.map((c) => (
        <div key={c.worker_id} className="suggestion">
          <strong>Replace with {c.full_name}</strong>
          <span className="reasons">{c.reasons.join(' · ')}</span>
          <button className="primary" disabled={pending || ackNeeded}
            onClick={() => move.mutate({ id, worker_id: c.worker_id, ...common }, { onSuccess: onDone })}>
            Replace
          </button>
        </div>
      ))}
      <div className="suggestion">
        <strong>Remove the assignment</strong>
        <span className="reasons">Leaves a coverage gap to fill later</span>
        <button disabled={pending || ackNeeded} onClick={() => remove.mutate({ id, ...common }, { onSuccess: onDone })}>Remove</button>
      </div>
      <EditErrors error={move.error ?? remove.error} nameOf={nameOf} onReload={() => { move.reset(); remove.reset(); onDone() }} />
    </div>
  )
}

/** One violation with a "Fix" toggle that lists up to five replacements (and removal) per involved assignment. */
export function ViolationFix({ v, fix, text, defaultOpen = false }: { v: ViolationOut; fix: FixProps; text?: string; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen)
  const [ack, setAck] = useState(false)
  const nameOf = nameLookup(fix.roster.workers)
  const fixable = v.assignments.flatMap((a) => {
    const id = fix.idOf(a)
    return id !== undefined && !isLockedShift(a.date, a.shift, fix.roster.free_from) ? [{ a, id }] : []
  })

  return (
    <li>
      {text ?? `${violationLabel(v.code)} (×${v.magnitude}) ${v.assignments.map((a) => `${nameOf(a.worker_id)} ${a.date} ${a.shift}`).join('; ')}`}
      {fixable.length > 0 && (
        <button className="link" aria-expanded={open} onClick={() => setOpen(!open)}>{open ? 'Hide fixes' : 'Fix'}</button>
      )}
      {open && (
        <>
          {needsApprovalAck(fix.roster.status) && (
            <label className="check ack">
              <input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} />
              This roster is approved. Editing returns it to draft and revokes the approval.
            </label>
          )}
          {fixable.map(({ a, id }) => (
            <AssignmentFixes key={id} month={fix.month} roster={fix.roster} assignment={a} id={id} ack={ack} onDone={() => setOpen(false)} />
          ))}
        </>
      )}
    </li>
  )
}

export type { FixProps }
