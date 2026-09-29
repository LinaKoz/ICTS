import { ApiError } from '../../errors/ApiError'
import type { AffectedRosterOut, ContractInput, ContractOut, ContractPreviewOut, WorkerOut, WorkerPatch } from '../../api/schemas'

export const DAYS = ['MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT', 'SUN'] as const
export const SHIFTS = ['A', 'B', 'C'] as const

const DAY_LABEL: Record<string, string> = { MON: 'Mon', TUE: 'Tue', WED: 'Wed', THU: 'Thu', FRI: 'Fri', SAT: 'Sat', SUN: 'Sun' }
export const dayLabel = (d: string): string => DAY_LABEL[d] ?? d

/** Weekday order (MON..SUN), then shift: the backend's stored order. Drops duplicates and unknown tokens. */
export function normalizeAvailability(tokens: readonly string[]): string[] {
  const keep = new Set(tokens)
  return DAYS.flatMap((d) => SHIFTS.map((s) => `${d}:${s}`)).filter((t) => keep.has(t))
}

export function toggleToken(tokens: readonly string[], token: string): string[] {
  return normalizeAvailability(tokens.includes(token) ? tokens.filter((t) => t !== token) : [...tokens, token])
}

/** "Mon ABC · Tue AB": readable availability for the version timeline. */
export function availabilitySummary(tokens: readonly string[]): string {
  const by = new Map<string, string>()
  for (const t of normalizeAvailability(tokens)) {
    const [d, s] = t.split(':') as [string, string]
    by.set(d, (by.get(d) ?? '') + s)
  }
  if (by.size === 0) return 'none'
  if (by.size === 7 && [...by.values()].every((v) => v === 'ABC')) return 'all shifts, every day'
  return DAYS.filter((d) => by.has(d)).map((d) => `${dayLabel(d)} ${by.get(d)}`).join(' · ')
}

// --- contract form -------------------------------------------------------------

export interface ContractForm {
  effective_month: string
  hourly_rate_ils: string
  min_hours: string
  max_hours: string
  availability: string[]
}

/** A new-version form pre-filled from the version being revised (or empty for a first contract). */
export function formFromContract(c: ContractOut | null, month: string): ContractForm {
  return {
    effective_month: month,
    hourly_rate_ils: c?.hourly_rate_ils ?? '',
    min_hours: c ? String(c.min_hours) : '0',
    max_hours: c ? String(c.max_hours) : '',
    availability: c ? normalizeAvailability(c.availability) : [],
  }
}

const RATE = /^\d{1,8}(\.\d{1,2})?$/
const INT = /^\d+$/

/** Client-side checks that mirror the API's 422s so the form can show them inline before a round trip. */
export function validateContractForm(f: ContractForm): Record<string, string> {
  const errors: Record<string, string> = {}
  if (!/^\d{4}-(0[1-9]|1[0-2])$/.test(f.effective_month)) errors.effective_month = 'Choose a month'
  if (!RATE.test(f.hourly_rate_ils) || Number(f.hourly_rate_ils) <= 0) errors.hourly_rate_ils = 'Enter a positive rate with at most 2 decimals'
  const min = INT.test(f.min_hours) ? Number(f.min_hours) : NaN
  const max = INT.test(f.max_hours) ? Number(f.max_hours) : NaN
  if (Number.isNaN(min) || min > 744) errors.min_hours = 'Whole hours, 0 to 744'
  if (Number.isNaN(max) || max > 744) errors.max_hours = 'Whole hours, 0 to 744'
  if (!errors.min_hours && !errors.max_hours && min > max) errors.max_hours = 'Maximum must not be below the minimum'
  if (f.availability.length === 0) errors.availability = 'Select at least one available shift'
  return errors
}

export function toContractInput(f: ContractForm): ContractInput {
  return {
    effective_month: f.effective_month,
    hourly_rate_ils: f.hourly_rate_ils,
    min_hours: Number(f.min_hours),
    max_hours: Number(f.max_hours),
    availability: normalizeAvailability(f.availability),
  }
}

// --- errors --------------------------------------------------------------------

/** Field -> message from a 422 `details` list (`[{loc: ['body', field], message}]`), for inline display. */
export function fieldErrors(err: unknown): Record<string, string> {
  if (!(err instanceof ApiError) || err.status !== 422 || !Array.isArray(err.details)) return {}
  const out: Record<string, string> = {}
  for (const d of err.details as Array<{ loc?: unknown; message?: unknown }>) {
    if (!Array.isArray(d.loc) || typeof d.message !== 'string') continue
    const field = String(d.loc[d.loc.length - 1])
    out[field] ??= d.message.replace(/^Value error, /, '')
  }
  return out
}

/** 409 WORKER_IN_USE (P6): the UI offers "deactivate" instead. */
export const isWorkerInUse = (err: unknown): boolean => err instanceof ApiError && err.status === 409 && err.code === 'WORKER_IN_USE'
/** 409 STALE_PREVIEW: the base changed between preview and apply. */
export const isStalePreview = (err: unknown): boolean => err instanceof ApiError && err.status === 409 && err.code === 'STALE_PREVIEW'

// --- impact text ---------------------------------------------------------------

const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`

/**
 * The P2 locked-violation warning, one message per affected roster that has
 * violations in already-started shifts (which editing cannot fix).
 */
export function lockedViolationWarnings(rosters: readonly AffectedRosterOut[]): string[] {
  return rosters
    .filter((r) => r.locked_violations.length > 0)
    .map((r) => {
      const n = r.locked_violations.length
      const revoke = r.revokes_approval ? `Approval of ${r.month} will be revoked. ` : ''
      return (
        `${revoke}${plural(n, 'violation')} ${n === 1 ? 'falls' : 'fall'} in shifts that have already started ` +
        'and cannot be fixed by editing assignments. ' +
        `The roster ${r.month} will stay unapproved unless the contract data is corrected.`
      )
    })
}

/** What one affected roster will do, for the impact table. */
export function rosterEffect(r: AffectedRosterOut): string {
  if (r.is_history) return 'History: read-only, not revalidated'
  if (r.new_violations.length === 0) return 'No new violations'
  const base = plural(r.new_violations.length, 'new violation')
  return r.revokes_approval ? `${base}; approval revoked, back to draft` : base
}

export function previewHeadline(p: Pick<ContractPreviewOut, 'unchanged' | 'retroactive' | 'affected_rosters'>): string {
  if (p.unchanged) return 'Identical to the contract already in force for that month: no new version will be created.'
  const n = p.affected_rosters.length
  const rosters = n === 0 ? 'No roster is affected' : `${plural(n, 'roster')} affected`
  return p.retroactive ? `Retroactive change. ${rosters}.` : `${rosters}.`
}

// --- worker role/status change -------------------------------------------------

/** Lines for the plain confirmation before a role/status change (P7); empty when nothing risky changes. */
export function roleStatusChangeLines(w: Pick<WorkerOut, 'role' | 'status'>, next: Pick<WorkerPatch, 'role' | 'status'>): string[] {
  const lines: string[] = []
  if (next.status && next.status !== w.status) lines.push(`Status ${w.status.toLowerCase()} to ${next.status.toLowerCase()}`)
  if (next.role && next.role !== w.role) lines.push(`Role ${w.role.replace('_', ' ').toLowerCase()} to ${next.role.replace('_', ' ').toLowerCase()}`)
  return lines
}

/** Only the fields that differ, as a PATCH body (with the version the form was loaded at). */
export function diffPatch(
  w: Pick<WorkerOut, 'national_id' | 'full_name' | 'role' | 'status' | 'row_version'>,
  form: { national_id: string; full_name: string; role: WorkerOut['role']; status: WorkerOut['status'] },
): WorkerPatch | null {
  const patch: WorkerPatch = { expected_version: w.row_version }
  let dirty = false
  if (form.national_id.trim() !== w.national_id) { patch.national_id = form.national_id.trim(); dirty = true }
  if (form.full_name.trim() !== w.full_name) { patch.full_name = form.full_name.trim(); dirty = true }
  if (form.role !== w.role) { patch.role = form.role; dirty = true }
  if (form.status !== w.status) { patch.status = form.status; dirty = true }
  return dirty ? patch : null
}

/** Mirrors backend app/workers/national_id.py: 9 ASCII digits plus the Israeli ID checksum. */
export function nationalIdError(id: string): string | null {
  if (!/^[0-9]{9}$/.test(id)) {
    const hint = /^[0-9]+$/.test(id) && id.length < 9 ? ` (got ${id.length}); spreadsheets often drop leading zeros` : ''
    return `National ID must be exactly 9 digits${hint}`
  }
  let total = 0
  for (let i = 0; i < 9; i++) {
    const n = Number(id[i]) * (1 + (i % 2))
    total += n > 9 ? n - 9 : n
  }
  return total % 10 === 0 ? null : 'National ID fails the Israeli ID checksum'
}

/** Client-side check of the worker details form; the server stays authoritative. */
export function validateWorkerForm(f: { national_id: string; full_name: string }): Record<string, string> {
  const errors: Record<string, string> = {}
  const idError = nationalIdError(f.national_id.trim())
  if (idError) errors.national_id = idError
  if (f.full_name.trim() === '') errors.full_name = 'Enter the full name'
  return errors
}
