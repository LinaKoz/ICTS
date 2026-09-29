import { useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { ErrorPanel } from '../../errors/ErrorPanel'
import { ApiError } from '../../errors/ApiError'
import type { Role, WorkerOut, WorkerStatus } from '../../api/schemas'
import { useCreateWorker, useDeleteWorker, useUpdateWorker, useWorkers, type WorkerFilters } from './api'
import { fieldErrors, isWorkerInUse } from './logic'
import { ROLES, roleLabel } from './labels'

function CreateWorkerForm({ onDone }: { onDone: () => void }) {
  const create = useCreateWorker()
  const [form, setForm] = useState({ national_id: '', full_name: '', role: 'GENERAL_GUARD' as Role, status: 'ACTIVE' as WorkerStatus })
  const errors = fieldErrors(create.error)
  const otherError = create.isError && Object.keys(errors).length === 0

  function submit(e: FormEvent) {
    e.preventDefault()
    create.mutate({ ...form, national_id: form.national_id.trim(), full_name: form.full_name.trim() }, { onSuccess: onDone })
  }
  const err = (f: string) => errors[f] && <span className="field-error" role="alert">{errors[f]}</span>

  return (
    <form className="panel form" onSubmit={submit} aria-label="New worker">
      <h3>New worker</h3>
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
      {otherError && <ErrorPanel error={create.error} />}
      <div className="actions">
        <button className="primary" disabled={create.isPending}>{create.isPending ? 'Creating…' : 'Create worker'}</button>
        <button type="button" onClick={onDone}>Cancel</button>
      </div>
      <p className="muted">Contracts are added on the worker page after creating them. Until then they are excluded from generation.</p>
    </form>
  )
}

function WorkerRow({ w, onDelete, deleting }: { w: WorkerOut; onDelete: (w: WorkerOut) => void; deleting: boolean }) {
  const c = w.current_contract
  return (
    <tr>
      <td><Link to={`/workers/${w.id}`}>{w.full_name}</Link></td>
      <td>{w.national_id}</td>
      <td>{roleLabel(w.role)}</td>
      <td><span className={`badge ${w.status === 'ACTIVE' ? 'badge-approved' : ''}`}>{w.status === 'ACTIVE' ? 'Active' : 'Inactive'}</span></td>
      <td>{c ? `₪${c.hourly_rate_ils}/h · ${c.min_hours}-${c.max_hours} h` : <span className="muted">no contract</span>}</td>
      <td className="actions-cell"><button disabled={deleting} onClick={() => onDelete(w)}>Delete</button></td>
    </tr>
  )
}

export function WorkersPage() {
  const [filters, setFilters] = useState<WorkerFilters>({ q: '', status: '', role: '' })
  const [creating, setCreating] = useState(false)
  const [inUse, setInUse] = useState<WorkerOut | null>(null)
  const workers = useWorkers(filters)
  const del = useDeleteWorker()
  const deactivate = useUpdateWorker(inUse?.id ?? 0)

  function remove(w: WorkerOut) {
    setInUse(null)
    del.mutate(w.id, { onError: (e) => { if (isWorkerInUse(e)) setInUse(w) } })
  }

  const deleteFailed = del.isError && !isWorkerInUse(del.error)

  return (
    <div>
      <div className="toolbar">
        <h2 className="page-title">Workers</h2>
        <input placeholder="Search name or ID" aria-label="Search" value={filters.q} onChange={(e) => setFilters({ ...filters, q: e.target.value })} />
        <select aria-label="Status filter" value={filters.status} onChange={(e) => setFilters({ ...filters, status: e.target.value as WorkerStatus | '' })}>
          <option value="">Any status</option><option value="ACTIVE">Active</option><option value="INACTIVE">Inactive</option>
        </select>
        <select aria-label="Role filter" value={filters.role} onChange={(e) => setFilters({ ...filters, role: e.target.value as Role | '' })}>
          <option value="">Any role</option>
          {ROLES.map((r) => <option key={r} value={r}>{roleLabel(r)}</option>)}
        </select>
        <span className="spacer" />
        <button className="primary" onClick={() => setCreating(true)} disabled={creating}>New worker</button>
      </div>

      {creating && <CreateWorkerForm onDone={() => setCreating(false)} />}

      {inUse && (
        <div className="panel panel-warning" role="alert">
          <strong>{inUse.full_name} cannot be deleted</strong>
          <p>This worker has contracts, assignments or history, which are kept. Deactivate them instead: they stay in past rosters and are excluded from new ones.</p>
          <div className="actions">
            {inUse.status === 'ACTIVE' && (
              <button
                className="primary"
                disabled={deactivate.isPending}
                onClick={() => deactivate.mutate({ expected_version: inUse.row_version, status: 'INACTIVE' }, { onSuccess: () => setInUse(null) })}
              >
                {deactivate.isPending ? 'Deactivating…' : 'Deactivate'}
              </button>
            )}
            <button onClick={() => setInUse(null)}>Dismiss</button>
          </div>
          {deactivate.isError && <ErrorPanel error={deactivate.error} onReload={() => { deactivate.reset(); void workers.refetch(); setInUse(null) }} />}
        </div>
      )}
      {deleteFailed && <ErrorPanel error={del.error} onReload={() => { del.reset(); void workers.refetch() }} />}

      {workers.isPending && <div className="skeleton" aria-busy="true" />}
      {workers.isError && <ErrorPanel error={workers.error} onRetry={() => workers.refetch()} />}
      {workers.data && (
        workers.data.length === 0 ? <p className="muted">No workers match.</p> : (
          <table className="table">
            <thead><tr><th>Name</th><th>National ID</th><th>Role</th><th>Status</th><th>Contract (this month)</th><th /></tr></thead>
            <tbody>{workers.data.map((w) => <WorkerRow key={w.id} w={w} onDelete={remove} deleting={del.isPending} />)}</tbody>
          </table>
        )
      )}
      {workers.isFetching && !workers.isPending && <p className="muted" aria-live="polite">Updating…</p>}
      {del.error instanceof ApiError && del.error.status === 404 && <p className="muted">That worker no longer exists.</p>}
    </div>
  )
}
