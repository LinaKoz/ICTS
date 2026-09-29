import { useState } from 'react'
import { ErrorPanel } from '../../errors/ErrorPanel'
import type { ContractApplyOut, ContractOut, ContractPreviewOut } from '../../api/schemas'
import { ApiError } from '../../errors/ApiError'
import { useApplyContract, useContracts, usePreviewContract } from './api'
import {
  DAYS, SHIFTS, availabilitySummary, dayLabel, fieldErrors, formFromContract, isStalePreview, lockedViolationWarnings,
  previewHeadline, rosterEffect, toContractInput, toggleToken, validateContractForm, type ContractForm,
} from './logic'

function currentMonth(): string {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
}

function ContractRow({ c, resolved }: { c: ContractOut; resolved: boolean }) {
  return (
    <tr className={resolved ? 'row-current' : undefined}>
      <td>v{c.version_no}{resolved && <span className="badge badge-approved">in force</span>}</td>
      <td>{c.effective_month}</td>
      <td>₪{c.hourly_rate_ils}/h</td>
      <td>{c.min_hours}-{c.max_hours} h</td>
      <td>{availabilitySummary(c.availability)}</td>
      <td>{c.source} · {c.created_by} · {new Date(c.created_at).toLocaleDateString('en-GB')}</td>
    </tr>
  )
}

function AvailabilityGrid({ value, onChange }: { value: string[]; onChange: (v: string[]) => void }) {
  return (
    <table className="mini availability" aria-label="Availability">
      <thead><tr><th />{SHIFTS.map((s) => <th key={s}>{s}</th>)}</tr></thead>
      <tbody>
        {DAYS.map((d) => (
          <tr key={d}>
            <th>{dayLabel(d)}</th>
            {SHIFTS.map((s) => {
              const token = `${d}:${s}`
              return (
                <td key={s}>
                  <input type="checkbox" aria-label={`${dayLabel(d)} ${s}`} checked={value.includes(token)} onChange={() => onChange(toggleToken(value, token))} />
                </td>
              )
            })}
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function ImpactPreview({ p }: { p: ContractPreviewOut }) {
  const warnings = lockedViolationWarnings(p.affected_rosters)
  return (
    <div className="preview" aria-label="Impact preview">
      <p><strong>{previewHeadline(p)}</strong></p>
      {p.invalidates_approved && (
        <div className="panel panel-error" role="alert">
          <strong>An approved roster will be invalidated.</strong> Its approval is revoked and it returns to draft. Assignments are kept.
        </div>
      )}
      {warnings.length > 0 && (
        <div className="panel panel-error" role="alert">
          <strong>Violations in shifts that have already started</strong>
          {warnings.map((w) => <p key={w}>{w}</p>)}
          <table className="mini">
            <thead><tr><th>Worker</th><th>Date</th><th>Shift</th><th>Problem</th></tr></thead>
            <tbody>
              {p.locked_violations.map((v, i) => <tr key={i}><td>{v.worker_name}</td><td>{v.date}</td><td>{v.shift}</td><td>{v.code}</td></tr>)}
            </tbody>
          </table>
        </div>
      )}
      {p.affected_rosters.length > 0 && (
        <table className="table">
          <thead><tr><th>Roster</th><th>Status</th><th>Shifts of this worker</th><th>Effect</th></tr></thead>
          <tbody>
            {p.affected_rosters.map((r) => (
              <tr key={r.month}>
                <td>{r.month}</td><td>{r.is_history ? 'History' : r.status.toLowerCase()}</td>
                <td>{r.assignment_count}</td><td>{rosterEffect(r)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

function NewVersionForm({ workerId, base, onApplied }: { workerId: number; base: ContractOut | null; onApplied: (r: ContractApplyOut) => void }) {
  const [form, setForm] = useState<ContractForm>(() => formFromContract(base, currentMonth()))
  const [preview, setPreview] = useState<ContractPreviewOut | null>(null)
  const [stale, setStale] = useState(false)
  const previewMut = usePreviewContract(workerId)
  const applyMut = useApplyContract(workerId)
  const clientErrors = validateContractForm(form)
  const [showErrors, setShowErrors] = useState(false)
  const serverErrors = fieldErrors(previewMut.error ?? applyMut.error)
  const errors = { ...serverErrors, ...(showErrors ? clientErrors : {}) }

  function edit(next: ContractForm) {
    setForm(next); setPreview(null); setStale(false); previewMut.reset(); applyMut.reset()
  }

  function runPreview() {
    setShowErrors(true)
    if (Object.keys(clientErrors).length > 0) return
    setStale(false); applyMut.reset()
    previewMut.mutate(toContractInput(form), { onSuccess: setPreview })
  }

  function apply() {
    if (!preview) return
    // mutateAsync, not mutate() callbacks: a successful apply refetches the versions, which remounts this form.
    applyMut
      .mutateAsync({ ...toContractInput(form), fingerprint: preview.fingerprint })
      .then((r) => { setPreview(null); onApplied(r) })
      .catch((e: unknown) => { if (isStalePreview(e)) { setStale(true); setPreview(null) } })
  }

  const err = (f: string) => errors[f] && <span className="field-error" role="alert">{errors[f]}</span>
  const apiError = (previewMut.error ?? applyMut.error) as unknown
  const showApiError = Boolean(apiError) && Object.keys(serverErrors).length === 0 && !isStalePreview(apiError)

  return (
    <section className="panel form" aria-label="New contract version">
      <h3>New contract version</h3>
      <p className="muted">Versions are never edited. A change is a new version from the chosen month; a second version for the same month supersedes the first and both are kept.</p>
      <label>Effective from <input type="month" value={form.effective_month} onChange={(e) => edit({ ...form, effective_month: e.target.value })} />{err('effective_month')}</label>
      <label>Hourly rate (ILS) <input inputMode="decimal" value={form.hourly_rate_ils} onChange={(e) => edit({ ...form, hourly_rate_ils: e.target.value })} />{err('hourly_rate_ils')}</label>
      <label>Minimum hours per month <input inputMode="numeric" value={form.min_hours} onChange={(e) => edit({ ...form, min_hours: e.target.value })} />{err('min_hours')}</label>
      <label>Maximum hours per month <input inputMode="numeric" value={form.max_hours} onChange={(e) => edit({ ...form, max_hours: e.target.value })} />{err('max_hours')}</label>
      <div>
        <span>Available shifts</span>
        <AvailabilityGrid value={form.availability} onChange={(v) => edit({ ...form, availability: v })} />
        {err('availability')}
      </div>
      {stale && (
        <div className="panel panel-warning" role="alert">
          <strong>Data changed since the preview</strong>
          <p>Nothing was applied. Review the new preview before confirming.</p>
          <button onClick={runPreview}>Reload preview</button>
        </div>
      )}
      {showApiError && <ErrorPanel error={apiError} onReload={runPreview} />}
      {preview && <ImpactPreview p={preview} />}
      <div className="actions">
        {!preview ? (
          <button className="primary" onClick={runPreview} disabled={previewMut.isPending}>{previewMut.isPending ? 'Checking impact…' : 'Preview impact'}</button>
        ) : (
          <>
            <button className="primary" onClick={apply} disabled={applyMut.isPending || preview.unchanged}>
              {applyMut.isPending ? 'Applying…' : 'Confirm and apply'}
            </button>
            <button onClick={() => setPreview(null)}>Cancel</button>
          </>
        )}
      </div>
    </section>
  )
}

export function ContractsSection({ workerId, currentContract }: { workerId: number; currentContract: ContractOut | null }) {
  const [month, setMonth] = useState(currentMonth)
  const [applied, setApplied] = useState<ContractApplyOut | null>(null)
  const contracts = useContracts(workerId, month)
  const base = contracts.data?.resolved ?? currentContract

  return (
    <section>
      <h3>Contract versions</h3>
      <div className="toolbar">
        <label>Show the contract in force for <input type="month" aria-label="Resolved for month" value={month} onChange={(e) => e.target.value && setMonth(e.target.value)} /></label>
        {contracts.data && (
          <span>
            {contracts.data.resolved
              ? <>v{contracts.data.resolved.version_no}: ₪{contracts.data.resolved.hourly_rate_ils}/h, {contracts.data.resolved.min_hours}-{contracts.data.resolved.max_hours} h</>
              : <span className="muted">No contract applies to {contracts.data.resolved_for}</span>}
          </span>
        )}
      </div>
      {contracts.isPending && <div className="skeleton" aria-busy="true" />}
      {contracts.isError && <ErrorPanel error={contracts.error} onRetry={() => contracts.refetch()} />}
      {contracts.data && (contracts.data.versions.length === 0 ? <p className="muted">No contract versions yet. This worker is excluded from generation until one exists.</p> : (
        <table className="table">
          <thead><tr><th>Version</th><th>Effective</th><th>Rate</th><th>Hours</th><th>Availability</th><th>Created</th></tr></thead>
          <tbody>{contracts.data.versions.map((c) => <ContractRow key={c.id} c={c} resolved={c.id === contracts.data!.resolved?.id} />)}</tbody>
        </table>
      ))}
      {applied && (
        <div className="panel panel-ok" role="status">
          {applied.created
            ? <>Version {applied.contract?.version_no} created.{applied.revoked_rosters.length > 0 && ` Approval revoked for ${applied.revoked_rosters.join(', ')}; the roster${applied.revoked_rosters.length > 1 ? 's are' : ' is'} back in draft.`}</>
            : 'Nothing to apply: the contract is unchanged.'}
          {lockedViolationWarnings(applied.affected_rosters).map((w) => <p key={w}>{w}</p>)}
        </div>
      )}
      {contracts.error instanceof ApiError && contracts.error.status === 404 && <p>This worker no longer exists.</p>}
      {contracts.data && <NewVersionForm key={contracts.data.versions.length} workerId={workerId} base={base} onApplied={setApplied} />}
    </section>
  )
}
