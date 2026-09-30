import { useEffect, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { ErrorPanel } from '../../errors/ErrorPanel'
import type { AssignmentOut, GenerateOutcomeOut, RosterOut } from '../../api/schemas'
import { Modal } from '../../components/Modal'
import { WorkerDetail } from '../workers/WorkerDetailPage'
import { rosterKey, useAssignmentIds, useGenerate, useMeta, useMoveAssignment, useRoster, useRosters, useSave, useSwapAssignment } from './api'
import { ApprovalPanel } from './ApprovalPanel'
import { EditErrors, EditPanel, type Selection } from './EditPanel'
import { buildMoveBody, explainEditError, idLookup, needsApprovalAck, type CellRef, type DropAction } from './edit'
import { nameLookup } from './names'
import { describeOutcome } from './outcome'
import { FilterBar } from './FilterBar'
import { NO_FILTER, type RosterFilter } from './filter'
import { RosterCalendar } from './RosterCalendar'
import { CalendarToolbar } from './CalendarToolbar'
import { RosterSummary } from './RosterSummary'
import { buildIndex, shiftsOfWorker, type MonthSource } from './calendarData'
import { WorkerFocusCard, WorkerSearch } from './WorkerFocus'
import { daysInMonth, monthLabel, monthOf, todayIso, visibleDates, visibleMonths, type CalendarView } from './calendar'
import { SidePanel } from './SidePanel'

function StatusBadge({ roster }: { roster: RosterOut | null | undefined }) {
  if (!roster) return <span className="badge">No roster</span>
  const label = roster.is_history ? 'History' : roster.status === 'APPROVED' ? 'Approved' : 'Draft'
  return <span className={`badge badge-${label.toLowerCase()}`}>{label}</span>
}

const selectionKey = (s: Selection) =>
  s.kind === 'assignment' ? `a${s.id}` : `g${s.slot.date}${s.slot.shift}${s.slot.role}`

export function RosterPage() {
  const qc = useQueryClient()
  const [today, setToday] = useState(todayIso)
  useEffect(() => {
    const id = setInterval(() => setToday(todayIso()), 60_000)
    return () => clearInterval(id)
  }, [])
  const [anchor, setAnchor] = useState(today)
  const [view, setView] = useState<CalendarView>('week')
  const month = monthOf(anchor)
  const [forbid, setForbid] = useState(false)
  const [preview, setPreview] = useState<GenerateOutcomeOut | null>(null)
  const [confirmReplace, setConfirmReplace] = useState(false)
  const [saved, setSaved] = useState(false)
  const [selection, setSelection] = useState<Selection | null>(null)

  const meta = useMeta()
  const roster = useRoster(month)
  const generate = useGenerate(month)
  const save = useSave(month)
  const move = useMoveAssignment(month)
  const swap = useSwapAssignment(month)
  const [dropMessage, setDropMessage] = useState<string | null>(null)
  const [attempt, setAttempt] = useState<CellRef | null>(null)
  const [editMode, setEditMode] = useState(false)
  const [focusId, setFocusId] = useState<string | null>(null)
  const [filter, setFilter] = useState<RosterFilter>(NO_FILTER)

  const existing = roster.data ?? null
  const summary = preview ? describeOutcome(preview) : null
  const previewUsable = preview?.outcome === 'solved' && preview.assignments != null && preview.fingerprint != null
  // Manual edits work on the stored roster only: not on a preview, not on history.
  const canEdit = existing != null && !existing.is_history && !previewUsable
  const ids = useAssignmentIds(month, canEdit)
  const idOf = idLookup(ids.data)
  const editing = canEdit && editMode && ids.isSuccess

  /** Moves the visible date. Anything tied to the month (preview, edits, dialogs) resets only when the month changes. */
  function goTo(date: string) {
    if (!date) return
    if (monthOf(date) !== month && preview && !saved && !window.confirm('Leave this month? The generated roster has not been saved and will be discarded.')) return
    setAnchor(date)
    if (monthOf(date) === month) return
    setPreview(null); setConfirmReplace(false); setSaved(false); setSelection(null); setEditMode(false)
    generate.reset(); save.reset(); move.reset(); swap.reset(); setDropMessage(null); setAttempt(null)
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

  /** A chip was dropped: move to a free slot, or swap with another worker. */
  function applyDrop(from: AssignmentOut, action: DropAction, where: CellRef) {
    move.reset(); swap.reset(); setDropMessage(null); setAttempt(where)
    if (action.kind === 'reject') { setDropMessage(action.message); return }
    const id = idOf(from)
    if (!existing || id === undefined) return
    const approved = needsApprovalAck(existing.status)
    if (approved && !window.confirm('This roster is approved. Editing returns it to draft and revokes the approval. Continue?')) return
    const common = { expected_version: existing.version, acknowledge_approved_edit: approved }
    if (action.kind === 'move') {
      move.mutate({ id, ...buildMoveBody(from, { workerId: from.worker_id, date: action.date, shift: action.shift }, existing.version, approved) })
    } else {
      const otherId = idOf(action.other)
      if (otherId !== undefined) swap.mutate({ id, other_assignment_id: otherId, ...common })
    }
  }

  function finishEditing() {
    setEditMode(false); setSelection(null); move.reset(); swap.reset(); setDropMessage(null); setAttempt(null)
  }

  function reload() {
    setPreview(null); setConfirmReplace(false); save.reset(); generate.reset()
    qc.invalidateQueries({ queryKey: rosterKey(month) })
  }

  const dropError = move.error ?? swap.error
  const dropLines = dropMessage ? [dropMessage] : explainEditError(dropError, nameLookup(existing?.workers))
  const clearDrop = () => { move.reset(); swap.reset(); setDropMessage(null); setAttempt(null) }
  const problem = attempt && dropLines.length > 0 ? { cell: attempt, lines: dropLines, onDismiss: clearDrop } : null

  // The calendar shows the unsaved preview when there is one, otherwise the stored roster.
  const shown = previewUsable
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

  // Every month the visible range touches: the target month from `shown`, the others from their stored rosters.
  const months = visibleMonths(view, anchor)
  const otherMonths = months.filter((m) => m !== month)
  const queries = useRosters(months)
  const sources: MonthSource[] = months.map((m, i) => {
    if (m === month) {
      return {
        month: m,
        status: shown ? 'ready' : roster.isPending ? 'loading' : roster.isError ? 'error' : 'none',
        data: shown && { assignments: shown.assignments, gaps: shown.gaps, costs: shown.costs, workers: shown.workers, violations: shown.violations, freeFrom: shown.freeFrom },
      }
    }
    const q = queries[i]!
    const r = q.data
    return {
      month: m,
      status: q.isPending ? 'loading' : q.isError ? 'error' : r ? 'ready' : 'none',
      data: r ? { assignments: r.assignments, gaps: r.coverage_gaps, costs: r.costs, workers: r.workers, violations: r.violations, freeFrom: r.free_from } : null,
    }
  })
  const index = buildIndex(sources)
  const focusWorker = shown?.workers?.find((w) => w.worker_id === focusId) ?? null
  const monthDates = Array.from({ length: daysInMonth(month) }, (_, i) => `${month}-${String(i + 1).padStart(2, '0')}`)
  const focusShifts = focusWorker && meta.data ? shiftsOfWorker(index, focusWorker.worker_id, monthDates, meta.data.shifts, meta.data.roles) : []
  const approvedEvent = existing?.status === 'APPROVED' ? [...existing.approval_history].reverse().find((e) => !e.revoked_at) : undefined
  const openDay = (date: string) => { setView('day'); goTo(date) }
  const selectedKey = selection?.kind === 'assignment' ? `${selection.assignment.worker_id}|${selection.assignment.date}|${selection.assignment.shift}` : null
  const ruleText = (on: boolean) => (on ? 'no back-to-back shifts' : 'back-to-back shifts allowed')

  return (
    <div className="roster-page">
      <div className={`cal-header${editing ? ' cal-header-editing' : ''}`}>
      <CalendarToolbar view={view} anchor={anchor} today={today} onView={setView} onAnchor={goTo}
        extra={<>
          {meta.data && <FilterBar filter={filter} roles={meta.data.roles} shifts={meta.data.shifts} onChange={setFilter} />}
          <WorkerSearch workers={shown?.workers ?? []} focusId={focusId} onFocus={setFocusId} />
        </>} />

      <section className="cal-actions" aria-label={`Roster actions for ${monthLabel(month)}`}>
        <div className="cal-actions-row">
          <div className="cal-scope">
            <div className="cal-status" title={`Generate, save, approve and edit apply to ${monthLabel(month)}`}>
              <StatusBadge roster={roster.data} />
              {approvedEvent && <span className="muted">by {approvedEvent.approved_by} · {new Date(approvedEvent.approved_at).toLocaleDateString('en-GB')}</span>}
              {editing && <span className="badge badge-editing">Editing</span>}
            </div>
          </div>
          <span className="spacer" />
          <div className="cal-buttons">
            <details className="gen-settings">
              <summary><span aria-hidden="true">⚙</span> Generation settings</summary>
              <div className="gen-pop">
                <label className="check">
                  <input type="checkbox" checked={forbid} onChange={(e) => setForbid(e.target.checked)} />
                  Forbid back-to-back shifts
                </label>
                <p className="muted">Applies to the next generation for {monthLabel(month)}.{existing && ` The current roster uses: ${ruleText(existing.forbid_adjacent_shifts)}.`}</p>
              </div>
            </details>
            {existing && <button onClick={runGenerate} disabled={generate.isPending} title="Creates a new proposal to review before saving">{generate.isPending ? 'Generating…' : 'Regenerate'}</button>}
            {!existing && <button className="primary" onClick={runGenerate} disabled={generate.isPending}>{generate.isPending ? 'Generating…' : 'Generate roster'}</button>}
            {existing && canEdit && (editMode
              ? <button className="primary" onClick={finishEditing}>Done editing</button>
              : <button className="primary" onClick={() => setEditMode(true)} disabled={!ids.isSuccess}>Edit roster</button>)}
          </div>
        </div>
        {(editMode && canEdit || otherMonths.length > 0) && (
          <p className="muted cal-scope-note">
            {editMode && canEdit ? 'Editing: click a worker to change, or drag to move or swap. ' : ''}
            {otherMonths.length > 0 && `Actions apply to ${monthLabel(month)}. This view also shows ${otherMonths.map(monthLabel).join(' and ')} (view only): open one of its days to work on it.`}
          </p>
        )}
      </section>
      </div>
      {focusWorker && shown && (
        <WorkerFocusCard worker={focusWorker} month={month} costs={shown.costs} today={today} monthShifts={focusShifts} visibleDates={visibleDates(view, anchor)}
          onOpenDay={(d) => { setView('day'); goTo(d) }} onClear={() => setFocusId(null)} />
      )}

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

      {meta.isPending && <div className="skeleton" aria-busy="true" />}
      {meta.isError && <ErrorPanel error={meta.error} onRetry={() => meta.refetch()} />}
      {!roster.isPending && !shown && meta.data && <p className="muted">No roster for {monthLabel(month)} yet. Generate one to preview it.</p>}
      {shown && meta.data && <RosterSummary month={month} demand={meta.data.demand} view={{ coverage_gaps: shown.gaps, violations: shown.violations, costs: shown.costs }} />}
      {meta.data && (
        <>
          {!problem && (dropMessage || move.isError || swap.isError) && (
            <div className="panel panel-error" role="alert">
              {dropMessage && <p>{dropMessage}</p>}
              <EditErrors error={move.error ?? swap.error} nameOf={nameLookup(existing?.workers)} onReload={() => { move.reset(); swap.reset(); reload() }} />
              <button onClick={clearDrop}>Dismiss</button>
            </div>
          )}
          <RosterCalendar
            view={view} anchor={anchor} today={today} targetMonth={month}
            shifts={meta.data.shifts} roles={meta.data.roles} demand={meta.data.demand} index={index}
            onOpenDay={openDay} focusId={focusId} filter={filter}
            fix={canEdit && ids.isSuccess && existing ? { month, roster: existing, idOf } : undefined}
            edit={editing && view !== 'month' ? {
              onAssignment: (a) => { const id = idOf(a); if (id !== undefined) setSelection({ kind: 'assignment', assignment: a, id }) },
              onGap: (slot) => setSelection({ kind: 'gap', slot }),
              onDrop: applyDrop,
              problem,
              selectedKey,
            } : undefined}
          />
          <div className="cal-aside" aria-label={`Details for ${monthLabel(month)}`}>
            {existing && !previewUsable && <ApprovalPanel month={month} roster={existing} />}
            {shown && (
              <SidePanel violations={shown.violations} gaps={shown.gaps} shortfalls={shown.shortfalls} costs={shown.costs} workers={shown.workers}
                fix={editing && existing ? { month, roster: existing, idOf } : undefined} />
            )}
          </div>
        </>
      )}
      {editing && selection?.kind === 'gap' && existing && (
        <Modal label="Suggestions" onClose={() => setSelection(null)}>
          <EditPanel key={selectionKey(selection)} month={month} roster={existing} selection={selection} onClose={() => setSelection(null)} />
        </Modal>
      )}
      {editing && selection?.kind === 'assignment' && existing && (
        <Modal label="Worker" onClose={() => setSelection(null)}>
          <EditPanel key={selectionKey(selection)} month={month} roster={existing} selection={selection} onClose={() => setSelection(null)} />
          <h3>Worker details</h3>
          <WorkerDetail id={Number(selection.assignment.worker_id)} embedded />
        </Modal>
      )}
    </div>
  )
}
