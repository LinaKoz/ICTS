import { ApiError } from '../../errors/ApiError'
import type {
  FieldDiffOut, ImportConfirmOut, ImportConfirmRequest, ImportPreviewOut, ImportResultOut, ImportRowOut,
} from '../../api/schemas'

/** P14 limits, mirrored from the backend so an oversized file is caught before uploading. */
export const MAX_FILE_BYTES = 1_048_576
export const MAX_ROWS = 5_000

export type Classification = ImportRowOut['classification']
export type Decision = ImportConfirmRequest['decisions'][string]

export const CLASSIFICATIONS: readonly Classification[] = ['NEW', 'CHANGED', 'UNCHANGED', 'INVALID']
export const CLASSIFICATION_TITLE: Record<Classification, string> = {
  NEW: 'New workers', CHANGED: 'Changed', UNCHANGED: 'Unchanged', INVALID: 'Invalid rows (not applied)',
}

/** A message when the file cannot be uploaded at all, else null. */
export function fileProblem(file: { name: string; size: number } | null): string | null {
  if (!file) return 'Choose a CSV file first.'
  if (file.size === 0) return 'The file is empty.'
  if (file.size > MAX_FILE_BYTES) return `The file is ${file.size.toLocaleString('en-US')} bytes; the limit is ${MAX_FILE_BYTES.toLocaleString('en-US')} bytes (1 MB).`
  return null
}

export function groupRows(rows: readonly ImportRowOut[]): Record<Classification, ImportRowOut[]> {
  const out: Record<Classification, ImportRowOut[]> = { NEW: [], CHANGED: [], UNCHANGED: [], INVALID: [] }
  for (const r of rows) out[r.classification].push(r)
  return out
}

/** Rows a decision applies to: only NEW and CHANGED rows can be applied. */
export const isActionable = (r: Pick<ImportRowOut, 'classification'>): boolean => r.classification === 'NEW' || r.classification === 'CHANGED'

/** The confirm body: an explicit decision for every actionable row (skipped ones are SKIP, the rest APPROVE). */
export function buildDecisions(rows: readonly ImportRowOut[], skipped: ReadonlySet<string>): Record<string, Decision> {
  const out: Record<string, Decision> = {}
  for (const r of rows) if (isActionable(r)) out[r.national_id] = skipped.has(r.national_id) ? 'SKIP' : 'APPROVE'
  return out
}

export const approvedCount = (rows: readonly ImportRowOut[], skipped: ReadonlySet<string>): number =>
  rows.filter((r) => isActionable(r) && !skipped.has(r.national_id)).length

const FIELD_LABEL: Record<string, string> = {
  full_name: 'Name', role: 'Role', status: 'Status', hourly_rate_ils: 'Hourly rate', min_monthly_hours: 'Min hours',
  max_monthly_hours: 'Max hours', availability: 'Availability',
}
export const fieldLabel = (f: string): string => FIELD_LABEL[f] ?? f

/** "Name: Alice -> Alicia"; a first value (new worker, first contract) has no arrow. */
export function formatDiff(d: FieldDiffOut): string {
  return d.old == null ? `${fieldLabel(d.field)}: ${d.new ?? ''}` : `${fieldLabel(d.field)}: ${d.old} → ${d.new ?? ''}`
}

const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`

export function summaryLine(p: Pick<ImportPreviewOut, 'counts'>): string {
  const c = p.counts
  return `${plural(c.new, 'new worker')}, ${c.changed} changed, ${c.unchanged} unchanged, ${c.invalid} invalid`
}

export interface ConfirmSummary { lines: string[]; revoked: string[] }

export function resultLines(r: ImportResultOut): string[] {
  const lines = [
    `${plural(r.created_workers, 'worker')} created`,
    `${plural(r.updated_workers, 'worker')} updated`,
    `${plural(r.contract_versions_created, 'contract version')} created`,
    `${r.unchanged} unchanged`,
  ]
  if (r.skipped > 0) lines.push(`${r.skipped} skipped by you`)
  if (r.invalid > 0) lines.push(`${r.invalid} invalid, not applied`)
  return lines
}

export function confirmSummary(c: ImportConfirmOut): ConfirmSummary {
  return { lines: resultLines(c.result), revoked: c.result.revoked_rosters }
}

// --- errors -------------------------------------------------------------------

const isErr = (err: unknown, status: number, code?: string): err is ApiError =>
  err instanceof ApiError && err.status === status && (code === undefined || err.code === code)

/** 409 STALE_PREVIEW on confirm: details carry a freshly computed preview (stored as a new import). */
export function stalePreviewOf(err: unknown): ImportPreviewOut | null {
  if (!isErr(err, 409, 'STALE_PREVIEW')) return null
  const d = err.details as { preview?: ImportPreviewOut } | null
  return d && typeof d === 'object' && d.preview ? d.preview : null
}

/** 409 ALREADY_CONFIRMED: details are the stored confirm result. */
export function alreadyConfirmedOf(err: unknown): ImportConfirmOut | null {
  if (!isErr(err, 409, 'ALREADY_CONFIRMED')) return null
  const d = err.details as ImportConfirmOut | null
  return d && typeof d === 'object' && 'result' in d ? d : null
}

/** Plain-language text for the upload errors of `POST /imports` (P14 limits and header checks). */
export function uploadErrorMessage(err: unknown): string | null {
  if (!(err instanceof ApiError)) return null
  const list = (k: string) => {
    const v = (err.details as Record<string, unknown> | null)?.[k]
    return Array.isArray(v) ? v.join(', ') : ''
  }
  switch (err.code) {
    case 'FILE_TOO_LARGE': return 'The file is larger than 1 MB. Split it and import it in parts.'
    case 'TOO_MANY_ROWS': return `The file has more than ${MAX_ROWS.toLocaleString('en-US')} data rows. Nothing was stored; split the file.`
    case 'MISSING_COLUMNS': return `Required columns are missing: ${list('missing')}. Required: national_id, full_name, role.`
    case 'DUPLICATE_COLUMN': return `Two headers mean the same column: ${list('columns')}.`
    case 'INVALID_ENCODING': return 'The file is not valid UTF-8. In Excel choose "CSV UTF-8" when saving.'
    case 'EMPTY_FILE': return 'The file has no header row.'
    case 'UNSUPPORTED_MEDIA_TYPE': return 'Only CSV files can be imported.'
    default: return null
  }
}

// --- export -------------------------------------------------------------------

export interface ExportCounts { workers: number; noContract: number }

export function exportCounts(h: Pick<Headers, 'get'>): ExportCounts | null {
  const w = Number(h.get('x-worker-count'))
  const n = Number(h.get('x-no-contract-count'))
  return h.get('x-worker-count') != null && Number.isFinite(w) && Number.isFinite(n) ? { workers: w, noContract: n } : null
}

export function exportSummary(c: ExportCounts): string {
  const base = plural(c.workers, 'worker') + ' exported'
  return c.noContract > 0 ? `${base}; ${c.noContract} without a contract for that month (contract columns are empty).` : `${base}.`
}

export const exportFilename = (month: string): string => `workers-${month}.csv`
