/**
 * Roster slice API types (§6 "Rosters").
 *
 * CONTRACT GAP: the roster endpoints are not yet in backend/openapi.json, so these
 * are hand-mirrored from backend/app/api_schemas/{common,rosters}.py. Once the main
 * session exports them, delete this file and re-point imports at `components["schemas"]`.
 */
export type Shift = 'A' | 'B' | 'C'
export type Role = 'GENERAL_GUARD' | 'SCREENER' | 'SUPERVISOR'

export interface AssignmentOut { worker_id: string; date: string; shift: Shift; role: Role }
export interface ViolationOut {
  code: string
  key: unknown[]
  magnitude: number
  assignments: AssignmentOut[]
}
export interface CoverageGapOut {
  date: string; shift: Shift; role: Role
  required: number; assigned: number; missing: number; proven_missing: number; locked: boolean
}
export interface HourShortfallOut { worker_id: string; min_hours: number; assigned_hours: number; missing_hours: number }
export interface CoverageStatusOut { status: 'OPTIMAL' | 'FEASIBLE'; total_uncovered: number; locked_uncovered: number; lower_bound: number }
export interface MinHoursStatusOut { status: 'OPTIMAL' | 'FEASIBLE'; total_shortfall: number }
export interface WorkerCostOut { worker_id: string; hours: number; amount_ils: string | null }
export interface CostsOut { per_worker: WorkerCostOut[]; monthly_total_ils: string; unknown_cost_worker_count: number }

export interface GenerateRequest { forbid_adjacent_shifts: boolean }
export interface GenerateOutcomeOut {
  outcome: 'solved' | 'no_solution_within_limit' | 'invalid_input' | 'engine_error'
  assignments?: AssignmentOut[] | null
  coverage_gaps?: CoverageGapOut[] | null
  hour_shortfalls?: HourShortfallOut[] | null
  coverage?: CoverageStatusOut | null
  min_hours?: MinHoursStatusOut | null
  lexicographically_optimal?: boolean | null
  preexisting_violations?: ViolationOut[] | null
  objective?: { weight: number; s_max: number; value: number; bound: number } | null
  costs?: CostsOut | null
  fingerprint?: string | null
  coverage_lower_bound?: number | null
  errors?: Record<string, unknown>[] | null
  message?: string | null
  warnings: string[]
}

export interface SaveRequest {
  assignments: AssignmentOut[]
  fingerprint: string
  expected_version: number | null
  replace_existing: boolean
  forbid_adjacent_shifts: boolean
}
export interface SaveResponseOut { roster_id: number; version: number; status: 'DRAFT' | 'APPROVED' }

export interface ApprovalEventOut {
  approved_by: string; approved_at: string; reason: string | null; revoked_at: string | null
  revoke_cause: 'EDIT' | 'REGENERATE' | 'CONTRACT_CHANGE' | 'WORKER_CHANGE' | null
}
export interface RosterOut {
  month: string
  status: 'DRAFT' | 'APPROVED'
  version: number
  is_history: boolean
  free_from: [string, Shift]
  forbid_adjacent_shifts: boolean
  assignments: AssignmentOut[]
  violations: ViolationOut[]
  coverage_gaps: CoverageGapOut[]
  hour_shortfalls: HourShortfallOut[]
  costs: CostsOut
  approval_history: ApprovalEventOut[]
}
