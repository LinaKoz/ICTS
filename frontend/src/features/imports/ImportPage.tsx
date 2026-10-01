import { useRef, useState } from 'react'
import { ErrorPanel } from '../../errors/ErrorPanel'
import { currentMonth } from '../roster/calendar'
import type { ImportConfirmOut, ImportPreviewOut, ImportRowOut } from '../../api/schemas'
import { lockedViolationWarnings, rosterEffect } from '../workers/logic'
import { roleLabel } from '../workers/labels'
import { useConfirmImport, useExportWorkers, useUploadImport } from './api'
import {
  CLASSIFICATIONS, CLASSIFICATION_TITLE, alreadyConfirmedOf, approvedCount, buildDecisions, confirmSummary, exportCounts,
  exportFilename, exportSummary, fileProblem, formatDiff, groupRows, isActionable, stalePreviewOf, summaryLine,
  uploadErrorMessage, type ExportCounts,
} from './logic'

function RowTable({ kind, rows, skipped, onToggle, disabled }: {
  kind: ImportRowOut['classification']; rows: ImportRowOut[]; skipped: ReadonlySet<string>; onToggle: (id: string) => void; disabled: boolean
}) {
  return (
    <table className="table" aria-label={CLASSIFICATION_TITLE[kind]}>
      <thead>
        <tr>
          {isActionable({ classification: kind }) && <th>Apply</th>}
          <th>Line</th><th>National ID</th><th>Name</th><th>Role</th>
          {kind === 'INVALID' ? <th>Problems</th> : <><th>Effective</th><th>{kind === 'UNCHANGED' ? 'Contract' : 'Changes'}</th></>}
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={`${r.line}-${r.national_id}`}>
            {isActionable(r) && (
              <td>
                <input
                  type="checkbox" aria-label={`Apply ${r.national_id}`} disabled={disabled}
                  checked={!skipped.has(r.national_id)} onChange={() => onToggle(r.national_id)}
                />
              </td>
            )}
            <td>{r.line}</td>
            <td>{r.national_id}</td>
            <td>{r.full_name}{r.export_row && <span className="badge" title="Row from an export file">export</span>}</td>
            <td>{r.role ? roleLabel(r.role) : ''}</td>
            {kind === 'INVALID' ? (
              <td>
                <ul className="row-errors">
                  {r.errors.map((e, i) => <li key={i}><code>{e.code}</code> {e.message}</li>)}
                </ul>
              </td>
            ) : (
              <>
                <td>{r.effective_month ?? <span className="muted">worker only</span>}{r.retroactive && <span className="badge badge-draft">retroactive</span>}</td>
                <td>
                  {r.changes.length === 0
                    ? <span className="muted">{r.contract ? 'same as current' : 'no changes'}</span>
                    : <ul className="row-errors">{r.changes.map((d, i) => <li key={i}>{formatDiff(d)}</li>)}</ul>}
                </td>
              </>
            )}
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function Banners({ p }: { p: ImportPreviewOut }) {
  const warnings = lockedViolationWarnings(p.affected_rosters)
  return (
    <>
      {p.invalidates_approved && (
        <div className="panel panel-error" role="alert" aria-label="Approved roster warning">
          <strong>An approved roster will be invalidated.</strong> Confirming returns it to draft and revokes its approval
          (assignments are kept).
          {warnings.map((w) => <p key={w}>{w}</p>)}
        </div>
      )}
      {!p.invalidates_approved && warnings.length > 0 && (
        <div className="panel panel-error" role="alert">
          <strong>Violations in shifts that have already started</strong>
          {warnings.map((w) => <p key={w}>{w}</p>)}
        </div>
      )}
      {p.locked_violations.length > 0 && (
        <table className="table mini" aria-label="Locked violations">
          <thead><tr><th>Worker</th><th>Date</th><th>Shift</th><th>Problem</th></tr></thead>
          <tbody>
            {p.locked_violations.map((v, i) => <tr key={i}><td>{v.worker_name}</td><td>{v.date}</td><td>{v.shift}</td><td>{v.code}</td></tr>)}
          </tbody>
        </table>
      )}
      {p.unknown_columns.length > 0 && (
        <div className="panel panel-warning" role="status">
          <strong>Ignored columns</strong>: {p.unknown_columns.join(', ')}.
        </div>
      )}
    </>
  )
}

function PreviewView({ preview, onReload, onDone }: {
  preview: ImportPreviewOut; onReload: (p: ImportPreviewOut) => void; onDone: (r: ImportConfirmOut) => void
}) {
  const [skipped, setSkipped] = useState<ReadonlySet<string>>(new Set())
  const [stale, setStale] = useState<ImportPreviewOut | null>(null)
  const confirm = useConfirmImport(preview.id)
  const groups = groupRows(preview.rows)
  const n = approvedCount(preview.rows, skipped)

  function toggle(id: string) {
    setSkipped((s) => { const next = new Set(s); if (!next.delete(id)) next.add(id); return next })
  }
  function run() {
    confirm.mutateAsync(buildDecisions(preview.rows, skipped))
      .then(onDone)
      .catch((e: unknown) => {
        const done = alreadyConfirmedOf(e)
        if (done) return onDone(done)
        setStale(stalePreviewOf(e))
      })
  }

  const affected = preview.affected_rosters
  return (
    <section aria-label="Import preview">
      <h3>Preview: {summaryLine(preview)}</h3>
      <p className="muted">
        Rows without an effective month use {preview.default_effective_month} (the current month). Nothing has been changed yet.
      </p>
      <Banners p={preview} />
      {affected.length > 0 && (
        <table className="table" aria-label="Affected rosters">
          <thead><tr><th>Roster</th><th>Status</th><th>Shifts of changed workers</th><th>Effect</th></tr></thead>
          <tbody>
            {affected.map((r) => (
              <tr key={r.month}><td>{r.month}</td><td>{r.is_history ? 'History' : r.status.toLowerCase()}</td><td>{r.assignment_count}</td><td>{rosterEffect(r)}</td></tr>
            ))}
          </tbody>
        </table>
      )}
      {CLASSIFICATIONS.filter((k) => groups[k].length > 0).map((k) => (
        <div key={k}>
          <h4>{CLASSIFICATION_TITLE[k]} ({groups[k].length})</h4>
          <RowTable kind={k} rows={groups[k]} skipped={skipped} onToggle={toggle} disabled={confirm.isPending} />
        </div>
      ))}
      {stale && (
        <div className="panel panel-warning" role="alert">
          <strong>Data changed since the preview</strong>
          <p>Nothing was applied. Reload the preview to see the current differences.</p>
          <button onClick={() => onReload(stale)}>Reload preview</button>
        </div>
      )}
      {confirm.isError && !stale && <ErrorPanel error={confirm.error} onRetry={run} />}
      <div className="actions">
        <button className="primary" onClick={run} disabled={confirm.isPending || n === 0}>
          {confirm.isPending ? 'Applying…' : `Confirm import (${n} ${n === 1 ? 'row' : 'rows'})`}
        </button>
      </div>
    </section>
  )
}

function ResultView({ done }: { done: ImportConfirmOut }) {
  const s = confirmSummary(done)
  return (
    <section className="panel panel-ok" role="status" aria-label="Import result">
      <h3>Import confirmed</h3>
      <ul>{s.lines.map((l) => <li key={l}>{l}</li>)}</ul>
      {s.revoked.length > 0 && (
        <p><strong>Approval revoked for {s.revoked.join(', ')}.</strong> The {s.revoked.length > 1 ? 'rosters are' : 'roster is'} back in draft; assignments were kept.</p>
      )}
      {lockedViolationWarnings(done.affected_rosters).map((w) => <p key={w}>{w}</p>)}
    </section>
  )
}

function UploadSection({ onPreview }: { onPreview: (p: ImportPreviewOut) => void }) {
  const input = useRef<HTMLInputElement>(null)
  const [problem, setProblem] = useState<string | null>(null)
  const upload = useUploadImport()

  function submit() {
    const file = input.current?.files?.[0] ?? null
    const p = fileProblem(file)
    setProblem(p)
    if (p || !file) return
    upload.mutate(file, { onSuccess: onPreview })
  }
  const friendly = upload.isError ? uploadErrorMessage(upload.error) : null
  return (
    <section className="panel form" aria-label="Upload">
      <h3>Import workers and contracts</h3>
      <p className="muted">
        CSV with a header row (UTF-8; comma, semicolon or tab separated): national_id, full_name and role are required; status, effective_month and the contract columns are optional.
        Up to 1 MB and 5,000 rows.
      </p>
      <label>CSV file <input ref={input} type="file" accept=".csv,text/csv" onChange={() => { setProblem(null); upload.reset() }} /></label>
      {problem && <span className="field-error" role="alert">{problem}</span>}
      {friendly && <div className="panel panel-error" role="alert"><strong>Import rejected</strong><p>{friendly}</p></div>}
      {upload.isError && !friendly && <ErrorPanel error={upload.error} />}
      <div className="actions">
        <button className="primary" onClick={submit} disabled={upload.isPending}>{upload.isPending ? 'Reading file…' : 'Preview import'}</button>
      </div>
    </section>
  )
}

function ExportSection() {
  const [month, setMonth] = useState(currentMonth)
  const [counts, setCounts] = useState<ExportCounts | null>(null)
  const exp = useExportWorkers()

  function download() {
    exp.mutate(month, {
      onSuccess: ({ blob, headers }) => {
        setCounts(exportCounts(headers))
        const url = URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url
        a.download = exportFilename(month)
        document.body.appendChild(a)
        a.click()
        a.remove()
        URL.revokeObjectURL(url)
      },
    })
  }
  return (
    <section className="panel form" aria-label="Export">
      <h3>Export workers</h3>
      <p className="muted">One row per worker with the contract in force for the month (otherwise the next future version). Re-importing an unmodified export changes nothing.</p>
      <label>Month <input type="month" aria-label="Export month" value={month} onChange={(e) => e.target.value && setMonth(e.target.value)} /></label>
      {exp.isError && <ErrorPanel error={exp.error} onRetry={download} />}
      {counts && <p role="status">{exportSummary(counts)}</p>}
      <div className="actions"><button onClick={download} disabled={exp.isPending}>{exp.isPending ? 'Preparing…' : 'Download CSV'}</button></div>
    </section>
  )
}

export function ImportPage() {
  const [preview, setPreview] = useState<ImportPreviewOut | null>(null)
  const [done, setDone] = useState<ImportConfirmOut | null>(null)

  return (
    <div className="import-page">
      <div className="toolbar"><h2 className="page-title">Import and export</h2></div>
      {done ? (
        <>
          <ResultView done={done} />
          <div className="actions"><button onClick={() => { setDone(null); setPreview(null) }}>Import another file</button></div>
        </>
      ) : (
        <>
          <UploadSection onPreview={(p) => setPreview(p)} />
          {preview && <PreviewView key={preview.id} preview={preview} onReload={setPreview} onDone={setDone} />}
        </>
      )}
      <ExportSection />
    </div>
  )
}
