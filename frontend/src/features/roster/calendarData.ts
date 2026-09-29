import type { AssignmentOut, CostsOut, CoverageGapOut, Role, Shift, ShiftCostOut, ViolationOut, WorkerRefOut } from '../../api/schemas'
import { monthOf } from './calendar'
import { nameLookup } from './names'

/** `none` = the month has no roster; `loading`/`error` = we do not know yet, so never call it a shortage. */
export type MonthStatus = 'loading' | 'none' | 'ready' | 'error'

export interface MonthData {
  assignments: AssignmentOut[]
  gaps: CoverageGapOut[]
  costs: CostsOut | null
  workers: WorkerRefOut[] | null | undefined
  violations: ViolationOut[]
  freeFrom: [string, Shift] | null
}

export interface MonthSource { month: string; status: MonthStatus; data: MonthData | null }

export interface CalendarIndex {
  status: (month: string) => MonthStatus
  assignmentsAt: (date: string, shift: Shift, role: Role) => AssignmentOut[]
  gapAt: (date: string, shift: Shift, role: Role) => CoverageGapOut | undefined
  costAt: (date: string, shift: Shift) => ShiftCostOut | undefined
  warningsAt: (date: string, shift?: Shift) => ViolationOut[]
  freeFrom: (month: string) => [string, Shift] | null
  nameOf: (workerId: string) => string
}

const cell = (date: string, shift: string, role?: string) => (role ? `${date}|${shift}|${role}` : `${date}|${shift}`)

/** Merges the rosters of every month the visible range touches into date-addressed lookups. */
export function buildIndex(sources: MonthSource[]): CalendarIndex {
  const statusByMonth = new Map(sources.map((s) => [s.month, s.status]))
  const freeFromByMonth = new Map(sources.map((s) => [s.month, s.data?.freeFrom ?? null]))
  const assignments = new Map<string, AssignmentOut[]>()
  const gaps = new Map<string, CoverageGapOut>()
  const costs = new Map<string, ShiftCostOut>()
  const warnings = new Map<string, ViolationOut[]>()
  const workers: WorkerRefOut[] = []
  for (const { data } of sources) {
    if (!data) continue
    for (const a of data.assignments) assignments.set(cell(a.date, a.shift, a.role), [...(assignments.get(cell(a.date, a.shift, a.role)) ?? []), a])
    for (const g of data.gaps) gaps.set(cell(g.date, g.shift, g.role), g)
    for (const c of data.costs?.per_shift ?? []) costs.set(cell(c.date, c.shift), c)
    for (const v of data.violations) {
      const keys = new Set(v.assignments.map((a) => cell(a.date, a.shift)))
      for (const k of keys) warnings.set(k, [...(warnings.get(k) ?? []), v])
    }
    workers.push(...(data.workers ?? []))
  }
  const nameOf = nameLookup(workers)
  const SHIFTS: Shift[] = ['A', 'B', 'C']
  return {
    status: (month) => statusByMonth.get(month) ?? 'loading',
    assignmentsAt: (date, shift, role) => assignments.get(cell(date, shift, role)) ?? [],
    gapAt: (date, shift, role) => gaps.get(cell(date, shift, role)),
    costAt: (date, shift) => costs.get(cell(date, shift)),
    warningsAt: (date, shift) => (shift ? warnings.get(cell(date, shift)) ?? [] : [...new Set(SHIFTS.flatMap((s) => warnings.get(cell(date, s)) ?? []))]),
    freeFrom: (month) => freeFromByMonth.get(month) ?? null,
    nameOf,
  }
}

export const isEditableMonth = (date: string, targetMonth: string) => monthOf(date) === targetMonth

/** Every shift the worker has on the given dates, in date order. */
export function shiftsOfWorker(
  index: CalendarIndex, workerId: string, dates: string[], shifts: Shift[], roles: Role[],
): { date: string; shift: Shift; role: Role }[] {
  const out: { date: string; shift: Shift; role: Role }[] = []
  for (const date of dates) for (const shift of shifts) for (const role of roles) {
    if (index.assignmentsAt(date, shift, role).some((a) => a.worker_id === workerId)) out.push({ date, shift, role })
  }
  return out
}
