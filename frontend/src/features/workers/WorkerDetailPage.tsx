import { useState, type FormEvent } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ErrorPanel } from '../../errors/ErrorPanel'
import type { ContractOut, Role, WorkerDetailOut, WorkerStatus, WorkerUpdateOut } from '../../api/schemas'
import { useUpdateWorker, useWorker } from './api'
import { ContractsSection } from './ContractsSection'
import { diffPatch, fieldErrors, roleStatusChangeLines, validateWorkerForm } from './logic'
import { ROLES, roleLabel } from './labels'

function UpdateResult({ result }: { result: WorkerUpdateOut }) {
  if (!result.changed) return <div className="panel" role="status">Nothing changed.</div>
  const revoked = result.affected_rosters.filter((r) => r.revokes_approval)
  return (
    <div className="panel panel-ok" role="status">
      <strong>Saved.</strong>
      {result.affected_rosters.length > 0 && (
        <ul>
          {result.affected_rosters.map((r) => (
            <li key={r.month}>
              {r.month}: {r.new_violations.length === 0 ? 'no new violations' : `${r.new_violations.length} new violation(s)`}
              {r.revokes_approval ? '; approval revoked, roster back to draft' : ''}
            </li>
          ))}
        </ul>
      )}
      {revoked.length > 0 && <p>Assignments were not changed. Open the roster to fix the violations, then approve it again.</p>}
    </div>
  )
}

function DetailsForm({ worker, onResult }: { worker: WorkerDetailOut; onResult: (r: WorkerUpdateOut) => void }) {
  const update = useUpdateWorker(worker.id)
  const [form, setForm] = useState({ national_id: worker.national_id, full_name: worker.full_name, role: worker.role as Role, status: worker.status as WorkerStatus })
  const [confirming, setConfirming] = useState<string[] | null>(null)
  const patch = diffPatch(worker, form)
  const [showErrors, setShowErrors] = useState(false)
  const serverErrors = fieldErrors(update.error)
  const clientErrors = validateWorkerForm(form)
  const errors = { ...serverErrors, ...(showErrors ? clientErrors : {}) }
  const otherError = update.isError && Object.keys(serverErrors).length === 0

  function save() {
    if (!patch) return
    // mutateAsync: the saved worker refetches with a new row_version, which remounts this (version-keyed) form.
    update.mutateAsync(patch).then(onResult).catch(() => setConfirming(null))
  }

  function submit(e: FormEvent) {
    e.preventDefault()
    if (!patch) return
    setShowErrors(true)
    if (Object.keys(clientErrors).length > 0) return
    const lines = roleStatusChangeLines(worker, patch)
    if (lines.length > 0) setConfirming(lines)
    else save()
  }
  const err = (f: string) => errors[f] && <span className="field-error" role="alert">{errors[f]}</span>

  return (
    <form className="panel form" onSubmit={submit} aria-label="Worker details">
      <h3>Details</h3>
      <label>National ID <input value={form.national_id} inputMode="numeric" onChange={(e) => setForm({ ...form, national_id: e.target.value })} />{err('national_id')}</label>
      <label>Full name <input value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} />{err('full_name')}</label>
      <label>Role
        <select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value as Role })}>
          {ROLES.map((r) => <option key={r} value={r}>{roleLabel(r)}</option>)}
        </select>
      </label>
      <label>Status
        <select value={form.status} onChange={(e) => setForm({ ...form, status: e.target.value as WorkerStatus })}>
          <option value="ACTIVE">Active</option><option value="INACTIVE">Inactive</option>
        </select>
      </label>
      {confirming ? (
        <div className="panel panel-warning" role="alertdialog" aria-label="Confirm change">
          <strong>Confirm: {confirming.join('; ')}</strong>
          <p>
            Current and upcoming rosters that contain this worker are revalidated. Assignments are kept, but an approved roster that
            becomes invalid returns to draft and loses its approval. Shifts that have already started are judged by the worker's status
            and role when they started.
          </p>
          <div className="actions">
            <button type="button" className="primary" disabled={update.isPending} onClick={save}>{update.isPending ? 'Saving…' : 'Confirm and save'}</button>
            <button type="button" onClick={() => setConfirming(null)}>Cancel</button>
          </div>
        </div>
      ) : (
        <div className="actions">
          <button className="primary" disabled={!patch || update.isPending}>{update.isPending ? 'Saving…' : 'Save'}</button>
          {patch && <button type="button" onClick={() => setForm({ national_id: worker.national_id, full_name: worker.full_name, role: worker.role, status: worker.status })}>Reset</button>}
        </div>
      )}
      {otherError && <ErrorPanel error={update.error} onReload={() => { update.reset(); window.location.reload() }} />}
    </form>
  )
}

function History({ worker }: { worker: WorkerDetailOut }) {
  if (worker.field_history.length === 0) return null
  return (
    <section className="panel">
      <h3>Status and role history</h3>
      <table className="table">
        <thead><tr><th>When</th><th>Field</th><th>Change</th><th>By</th></tr></thead>
        <tbody>
          {worker.field_history.map((h, i) => (
            <tr key={i}>
              <td>{new Date(h.effective_at).toLocaleString('en-GB')}</td>
              <td>{h.field === 'STATUS' ? 'Status' : 'Role'}</td>
              <td>{h.old_value.toLowerCase()} to {h.new_value.toLowerCase()}</td>
              <td>{h.changed_by}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  )
}

/** The worker's details, status/role history and contracts. Used as a page and inside the roster's worker dialog. */
export function WorkerDetail({ id, embedded = false }: { id: number; embedded?: boolean }) {
  const worker = useWorker(id)
  const [result, setResult] = useState<WorkerUpdateOut | null>(null)
  return (
    <div>
      {worker.isPending && <div className="skeleton" aria-busy="true" />}
      {worker.isError && <ErrorPanel error={worker.error} onRetry={() => worker.refetch()} />}
      {worker.data && (
        <>
          {!embedded && <h2 className="page-title">{worker.data.full_name} <span className={`badge ${worker.data.status === 'ACTIVE' ? 'badge-approved' : ''}`}>{worker.data.status === 'ACTIVE' ? 'Active' : 'Inactive'}</span></h2>}
          {/* keyed by version so a reload after a conflict resets the form to the stored values */}
          <DetailsForm key={worker.data.row_version} worker={worker.data} onResult={setResult} />
          {result && <UpdateResult result={result} />}
          <History worker={worker.data} />
          <ContractsSection workerId={id} currentContract={worker.data.current_contract as ContractOut | null} />
        </>
      )}
    </div>
  )
}

export function WorkerDetailPage() {
  const id = Number(useParams().id)
  if (!Number.isInteger(id)) return <p>Unknown worker.</p>
  return (
    <div>
      <p><Link to="/workers">Back to workers</Link></p>
      <WorkerDetail id={id} />
    </div>
  )
}
