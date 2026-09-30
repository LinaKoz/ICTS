import { useState } from 'react'
import { ErrorPanel } from '../../errors/ErrorPanel'
import { mapError } from '../../errors/mapError'
import type { AssignmentOut, Role, RosterOut, Shift } from '../../api/schemas'
import { useAddAssignment, useMoveAssignment, useRemoveAssignment, useSuggestions, type Slot } from './api'
import { buildMoveBody, explainEditError, isApprovedEditError, moveUnchanged, needsApprovalAck, workersForRole } from './edit'
import { daysInMonth } from './calendar'
import { DatePicker } from './DatePicker'
import { nameLookup } from './names'

export type Selection =
  | { kind: 'assignment'; assignment: AssignmentOut; id: number }
  | { kind: 'gap'; slot: Slot }

const ROLE_NAME: Record<Role, string> = { GENERAL_GUARD: 'general guard', SCREENER: 'screener', SUPERVISOR: 'supervisor' }

interface Props {
  month: string
  roster: RosterOut
  selection: Selection
  onClose: () => void
}

export function EditErrors({ error, nameOf, onReload, heading }: { error: unknown; nameOf: (id: string) => string; onReload: () => void; heading?: string }) {
  if (!error) return null
  const lines = explainEditError(error, nameOf)
  if (lines.length > 0) {
    return (
      <div className="panel panel-error" role="alert">
        <strong>{heading ?? mapError(error).title}</strong>
        <ul>{lines.map((l) => <li key={l}>{l}</li>)}</ul>
      </div>
    )
  }
  // The approved-edit 409 is answered by the acknowledgement checkbox, not by a reload prompt.
  return <ErrorPanel error={error} onReload={onReload} />
}

export function EditPanel({ month, roster, selection, onClose }: Props) {
  const nameOf = nameLookup(roster.workers)
  const [ack, setAck] = useState(false)
  const approved = needsApprovalAck(roster.status)
  const add = useAddAssignment(month)
  const remove = useRemoveAssignment(month)
  const move = useMoveAssignment(month)
  const [target, setTarget] = useState(
    selection.kind === 'assignment'
      ? { workerId: selection.assignment.worker_id, date: selection.assignment.date, shift: selection.assignment.shift as Shift }
      : null,
  )
  const suggestions = useSuggestions(month, selection.kind === 'gap' ? selection.slot : null)

  const error = add.error ?? remove.error ?? move.error
  const pending = add.isPending || remove.isPending || move.isPending
  const ackNeeded = approved && !ack
  const reset = () => { add.reset(); remove.reset(); move.reset() }
  const done = { onSuccess: onClose }
  const common = { expected_version: roster.version, acknowledge_approved_edit: ack }

  const ackBox = approved && (
    <label className={`check ack${isApprovedEditError(error) ? ' ack-required' : ''}`}>
      <input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} />
      This roster is approved. Editing returns it to draft and revokes the approval.
    </label>
  )

  return (
    <section className="panel edit-panel" aria-label="Edit roster">
      {selection.kind === 'assignment' ? (
        <>
          <h3>
            {nameOf(selection.assignment.worker_id)}
            <button onClick={onClose} aria-label="Close">×</button>
          </h3>
          <p className="muted">{selection.assignment.date} shift {selection.assignment.shift}, {ROLE_NAME[selection.assignment.role]}</p>
          {target && (
            <>
              <label>Worker
                <select value={target.workerId} onChange={(e) => { reset(); setTarget({ ...target, workerId: e.target.value }) }}>
                  {workersForRole(roster.workers, selection.assignment.role).map((w) => <option key={w.worker_id} value={w.worker_id}>{w.full_name}</option>)}
                </select>
              </label>
              <div className="field">Date
                <DatePicker inline label="Date" value={target.date} min={`${month}-01`} max={`${month}-${String(daysInMonth(month)).padStart(2, '0')}`}
                  onChange={(date) => { reset(); setTarget({ ...target, date }) }} />
              </div>
              <label>Shift
                <select value={target.shift} onChange={(e) => { reset(); setTarget({ ...target, shift: e.target.value as Shift }) }}>
                  {(['A', 'B', 'C'] as Shift[]).map((s) => <option key={s}>{s}</option>)}
                </select>
              </label>
            </>
          )}
          {ackBox}
          <EditErrors error={move.error} nameOf={nameOf} onReload={() => { reset(); onClose() }}
            heading={target ? `Can't do that: ${nameOf(target.workerId)} on ${target.date} shift ${target.shift}` : undefined} />
          <div className="actions">
            <button className="primary" disabled={pending || ackNeeded || !target || moveUnchanged(selection.assignment, target)}
              onClick={() => target && move.mutate({ id: selection.id, ...buildMoveBody(selection.assignment, target, roster.version, ack) }, done)}>
              Move
            </button>
            <button disabled={pending || ackNeeded} onClick={() => remove.mutate({ id: selection.id, ...common }, done)}>Remove</button>
          </div>
        </>
      ) : (
        <>
          <h3>
            Suggestions
            <button onClick={onClose} aria-label="Close">×</button>
          </h3>
          <p className="muted">{selection.slot.date} shift {selection.slot.shift}, {ROLE_NAME[selection.slot.role]}</p>
          {suggestions.isPending && <p><span className="spinner" /> Loading…</p>}
          {suggestions.isError && <ErrorPanel error={suggestions.error} onRetry={() => suggestions.refetch()} />}
          {suggestions.data && suggestions.data.candidates.length === 0 && (
            <p className="muted">
              {suggestions.data.slot_state === 'OPEN' ? 'No eligible worker: everyone of this role is unavailable, at a limit, or would break a rule.' : 'This position is not open for filling.'}
            </p>
          )}
          {ackBox}
          {suggestions.data?.candidates.map((c) => (
            <div key={c.worker_id} className="suggestion">
              <strong>{c.full_name}</strong>
              <span className="reasons">{c.reasons.join(' · ')}</span>
              <button className="primary" disabled={pending || ackNeeded}
                onClick={() => add.mutate({ worker_id: c.worker_id, date: selection.slot.date, shift: selection.slot.shift, role: selection.slot.role, ...common }, done)}>
                Assign
              </button>
              {add.error && add.variables?.worker_id === c.worker_id && (
                <EditErrors error={add.error} nameOf={nameOf} onReload={() => { reset(); onClose() }}
                  heading={`Can't assign ${c.full_name} here`} />
              )}
            </div>
          ))}
        </>
      )}
      {selection.kind === 'assignment' && (
        <EditErrors error={remove.error} nameOf={nameOf} onReload={() => { reset(); onClose() }}
          heading={`Can't remove ${nameOf(selection.assignment.worker_id)} from ${selection.assignment.date} shift ${selection.assignment.shift}`} />
      )}
    </section>
  )
}
