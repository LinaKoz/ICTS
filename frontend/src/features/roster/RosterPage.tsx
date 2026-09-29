import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { ErrorPanel } from '../../errors/ErrorPanel'
import type { GenerateOutcomeOut, RosterOut } from '../../api/schemas'
import { rosterKey, useAssignmentIds, useGenerate, useMeta, useRoster, useSave } from './api'
import { ApprovalPanel } from './ApprovalPanel'
import { EditPanel, type Selection } from './EditPanel'
import { idLookup } from './edit'
import { describeOutcome } from './outcome'
import { RosterGrid } from './RosterGrid'
import { SidePanel } from './SidePanel'

function currentMonth(): string {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
}

function StatusBadge({ roster }: { roster: RosterOut | null | undefined }) {
  if (!roster) return <span className="badge">No roster</span>
  const label = roster.is_history ? 'History' : roster.status === 'APPROVED' ? 'Approved' : 'Draft'
  return (
    <>
      <span className={`badge badge-${label.toLowerCase()}`}>{label}</span>
      {roster.forbid_adjacent_shifts && <span className="badge">No back-to-back shifts</span>}
    </>
  )
}

const selectionKey = (s: Selection) =>
  s.kind === 'assignment' ? `a${s.id}` : `g${s.slot.date}${s.slot.shift}${s.slot.role}`

export function RosterPage() {
  const qc = useQueryClient()
  const [month, setMonth] = useState(currentMonth)
  const [forbid, setForbid] = useState(false)
  const [preview, setPreview] = useState<GenerateOutcomeOut | null>(null)
  const [confirmReplace, setConfirmReplace] = useState(false)
  const [saved, setSaved] = useState(false)
  const [selection, setSelection] = useState<Selection | null>(null)

  const meta = useMeta()
  const roster = useRoster(month)
  const generate = useGenerate(month)
  const save = useSave(month)

  const existing = roster.data ?? null
  const summary = preview ? describeOutcome(preview) : null
  const previewUsable = preview?.outcome === 'solved' && preview.assignments != null && preview.fingerprint != null
  // Manual edits work on the stored roster only: not on a preview, not on history.
  const canEdit = existing != null && !existing.is_history && !previewUsable
  const ids = useAssignmentIds(month, canEdit)
  const idOf = idLookup(ids.data)
  const editing = canEdit && ids.isSuccess

  function changeMonth(m: string) {
    if (!m) return
    setMonth(m); setPreview(null); setConfirmReplace(false); setSaved(false); setSelection(null)
    generate.reset(); save.reset()
  }

  function runGenerate() {
    setSaved(false); setConfirmReplace(false); save.reset()
    generate.mutate(forbid, { onSuccess: setPreview, onError: () => setPreview(null) })
  }

  function doSave() {
    if (!preview || !previewUsable) return
    save.mutate(
      {
        assignments: preview.assignments!,
        fingerprint: preview.fingerprint!,
        expected_version: existing?.version ?? null,
        replace_existing: existing != null,
        forbid_adjacent_shifts: forbid,
      },
      { onSuccess: () => { setPreview(null); setConfirmReplace(false); setSaved(true) } },
    )
  }

  function reload() {
    setPreview(null); setConfirmReplace(false); save.reset(); generate.reset()
    qc.invalidateQueries({ queryKey: rosterKey(month) })
  }

  // The grid shows the unsaved preview when there is one, otherwise the stored roster.
  const view = previewUsable
    ? {
        assignments: preview!.assignments!, gaps: preview!.coverage_gaps ?? [], shortfalls: preview!.hour_shortfalls ?? [],
        costs: preview!.costs ?? null, workers: preview!.workers ?? null, violations: preview!.preexisting_violations ?? [], freeFrom: existing?.free_from ?? null,
      }
    : existing
      ? {
          assignments: existing.assignments, gaps: existing.coverage_gaps, shortfalls: existing.hour_shortfalls,
          costs: existing.costs, workers: existing.workers, violations: existing.violations, freeFrom: existing.free_from,
        }
      : null

  return (
    <div>
      <div className="toolbar">
        <label>Month <input type="month" value={month} onChange={(e) => changeMonth(e.target.value)} /></label>
        <StatusBadge roster={roster.data} />
        <span className="spacer" />
        <label className="check">
          <input type="checkbox" checked={forbid} onChange={(e) => setForbid(e.target.checked)} />
          Forbid back-to-back shifts (optional rule)
        </label>
        <button className="primary" onClick={runGenerate} disabled={generate.isPending}>
          {generate.isPending ? 'Generating…' : existing ? 'Regenerate' : 'Generate'}
        </button>
      </div>

      {generate.isPending && <div className="panel" role="status"><span className="spinner" /> Generating roster, this can take up to a minute…</div>}
      {generate.isError && <ErrorPanel error={generate.error} onRetry={runGenerate} onReload={reload} />}
      {roster.isError && <ErrorPanel error={roster.error} onRetry={() => roster.refetch()} />}
      {saved && <div className="panel panel-ok" role="status">Saved as draft.</div>}

      {summary && (
        <div className={`panel outcome outcome-${summary.kind}`}>
          <strong>Generation result</strong>
          <ul>{summary.messages.map((m) => <li key={m}>{m}</li>)}</ul>
          {preview?.warnings?.map((w) => <p key={w} className="muted">{w}</p>)}
          {preview?.outcome === 'invalid_input' && preview.errors && <pre>{JSON.stringify(preview.errors, null, 2)}</pre>}
          {previewUsable && (
            <div className="actions">
              {!confirmReplace ? (
                <button className="primary" disabled={save.isPending} onClick={() => (existing ? setConfirmReplace(true) : doSave())}>
                  {save.isPending ? 'Saving…' : 'Save as draft'}
                </button>
              ) : (
                <>
                  <span>
                    This replaces {existing!.assignments.length} assignments in the existing {existing!.status.toLowerCase()} roster
                    (last edited by {existing!.updated_by}, {new Date(existing!.updated_at).toLocaleString('en-GB')})
                    {existing!.status === 'APPROVED' ? ' and revokes its approval' : ''}.
                  </span>
                  <button className="primary" disabled={save.isPending} onClick={doSave}>{save.isPending ? 'Saving…' : 'Replace and save as draft'}</button>
                  <button onClick={() => setConfirmReplace(false)}>Cancel</button>
                </>
              )}
            </div>
          )}
        </div>
      )}
      {save.isError && <ErrorPanel error={save.error} onReload={reload} onRetry={doSave} />}

      {(roster.isPending || meta.isPending) && <div className="skeleton" aria-busy="true" />}
      {meta.isError && <ErrorPanel error={meta.error} onRetry={() => meta.refetch()} />}
      {!roster.isPending && !view && meta.data && <p className="muted">No roster for {month} yet. Generate one to preview it.</p>}
      {view && meta.data && (
        <div className="split">
          <RosterGrid
            month={month} shifts={meta.data.shifts} roles={meta.data.roles} demand={meta.data.demand}
            assignments={view.assignments} gaps={view.gaps} freeFrom={view.freeFrom}
            workers={view.workers} perShiftCosts={view.costs?.per_shift}
            edit={editing ? {
              onAssignment: (a) => { const id = idOf(a); if (id !== undefined) setSelection({ kind: 'assignment', assignment: a, id }) },
              onGap: (slot) => setSelection({ kind: 'gap', slot }),
            } : undefined}
          />
          <div>
            {editing && selection && existing && (
              <EditPanel key={selectionKey(selection)} month={month} roster={existing} selection={selection} onClose={() => setSelection(null)} />
            )}
            {existing && !previewUsable && <ApprovalPanel month={month} roster={existing} />}
            <SidePanel violations={view.violations} gaps={view.gaps} shortfalls={view.shortfalls} costs={view.costs} workers={view.workers} />
          </div>
        </div>
      )}
    </div>
  )
}
