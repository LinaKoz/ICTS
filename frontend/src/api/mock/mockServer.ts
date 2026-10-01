/**
 * Tiny in-memory fetch mock, enabled with VITE_API_MOCK=1, used until the live API lands.
 * Mirrors the §6 contract shapes and the error envelope. Demo logins: planner/manager, password "demo".
 */
import type {
  AssignmentOut, CoverageGapOut, GenerateOutcomeOut, HourShortfallOut, Role, RosterOut, SaveRequest, Shift, ShiftCostOut, WorkerRefOut,
} from '../schemas'
import type { components } from '../types'

type User = components['schemas']['UserOut']
const USERS: Record<string, User> = {
  planner: { id: 1, username: 'planner', display_name: 'Demo Planner', app_role: 'PLANNER' },
  manager: { id: 2, username: 'manager', display_name: 'Demo Manager', app_role: 'MANAGER' },
}
const SESSION_KEY = 'mock-session-user'

const META: components['schemas']['MetaOut'] = {
  shifts: ['A', 'B', 'C'],
  roles: ['GENERAL_GUARD', 'SCREENER', 'SUPERVISOR'],
  demand: (['A', 'B', 'C'] as Shift[]).flatMap((shift) => [
    { shift, role: 'GENERAL_GUARD' as Role, headcount: 2 },
    { shift, role: 'SCREENER' as Role, headcount: 2 },
    { shift, role: 'SUPERVISOR' as Role, headcount: 1 },
  ]),
  csv_aliases: { header_aliases: {}, role_aliases: {}, status_aliases: {} },
}

const ROLE_OF_PREFIX: Record<string, Role> = { GG: 'GENERAL_GUARD', SCR: 'SCREENER', SUP: 'SUPERVISOR' }
/** Mock worker ids are the same codes the old grid showed, with a readable name. */
const workerRef = (id: string): WorkerRefOut => ({
  worker_id: id, full_name: `Mock ${id}`, role: ROLE_OF_PREFIX[id.replace(/\d+$/, '')] ?? 'GENERAL_GUARD', status: 'ACTIVE',
})

const saved = new Map<string, RosterOut>()
let nextRosterId = 1

const wait = (ms: number) => new Promise((r) => setTimeout(r, ms))
const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
const err = (status: number, code: string, message: string, details: unknown = null) =>
  json(status, { error: { code, message, details } })

function currentUser(): User | null {
  try {
    const name = sessionStorage.getItem(SESSION_KEY)
    return name ? (USERS[name] ?? null) : null
  } catch {
    return null
  }
}

const pad = (n: number) => String(n).padStart(2, '0')

function buildRoster(month: string, forbidAdjacent: boolean) {
  const [y, m] = month.split('-').map(Number) as [number, number]
  const days = new Date(y, m, 0).getDate()
  const pools: Record<Role, string[]> = {
    GENERAL_GUARD: Array.from({ length: 9 }, (_, i) => `GG${pad(i + 1)}`),
    SCREENER: Array.from({ length: 9 }, (_, i) => `SCR${pad(i + 1)}`),
    SUPERVISOR: Array.from({ length: 5 }, (_, i) => `SUP${pad(i + 1)}`),
  }
  const cursor: Record<Role, number> = { GENERAL_GUARD: 0, SCREENER: 0, SUPERVISOR: 0 }
  const assignments: AssignmentOut[] = []
  const gaps: CoverageGapOut[] = []
  const hours: Record<string, number> = {}
  for (let d = 1; d <= days; d++) {
    const date = `${y}-${pad(m)}-${pad(d)}`
    ;(['A', 'B', 'C'] as Shift[]).forEach((shift, si) => {
      for (const dem of META.demand.filter((x) => x.shift === shift)) {
        const pool = pools[dem.role]
        // Deliberate demo gap: no 2nd supervisor-free night cover on days divisible by 9.
        const unfillable = dem.role === 'SUPERVISOR' && shift === 'C' && d % 9 === 0
        const fill = unfillable ? 0 : dem.headcount
        for (let k = 0; k < fill; k++) {
          const w = pool[(cursor[dem.role] + k + si) % pool.length]!
          assignments.push({ worker_id: w, date, shift, role: dem.role })
          hours[w] = (hours[w] ?? 0) + 8
        }
        cursor[dem.role] = (cursor[dem.role] + fill) % pool.length
        if (unfillable) {
          gaps.push({ date, shift, role: dem.role, required: dem.headcount, assigned: 0, missing: dem.headcount, proven_missing: dem.headcount, locked: false })
        }
      }
    })
  }
  const shortfalls: HourShortfallOut[] = Object.entries(hours)
    .filter(([w]) => w.startsWith('SUP'))
    .map(([worker_id, h]) => ({ worker_id, min_hours: 160, assigned_hours: h, missing_hours: Math.max(0, 160 - h) }))
    .filter((s) => s.missing_hours > 0)
  const per_worker = Object.entries(hours).map(([worker_id, h]) => ({
    worker_id, hours: h, amount_ils: worker_id === 'GG09' ? null : (h * 45).toFixed(2),
  }))
  const perShiftMap = new Map<string, ShiftCostOut>()
  for (const a of assignments) {
    const k = `${a.date}|${a.shift}`
    const cell = perShiftMap.get(k) ?? { date: a.date, shift: a.shift, amount_ils: '0.00', unknown_cost_assignments: 0 }
    if (a.worker_id === 'GG09') cell.unknown_cost_assignments += 1
    else cell.amount_ils = (Number(cell.amount_ils) + 8 * 45).toFixed(2)
    perShiftMap.set(k, cell)
  }
  const workers = Object.keys(hours).sort().map(workerRef)
  const total = per_worker.reduce((s, w) => s + (w.amount_ils ? Number(w.amount_ils) : 0), 0)
  return {
    assignments, gaps, shortfalls, workers,
    costs: { per_shift: [...perShiftMap.values()], per_worker, monthly_total_ils: total.toFixed(2), unknown_cost_worker_count: 1 },
    forbidAdjacent,
  }
}

export async function mockFetch(input: RequestInfo | URL, init: RequestInit = {}): Promise<Response> {
  const url = new URL(String(input), 'http://mock.local')
  const path = url.pathname.replace(/^\/api/, '')
  const method = (init.method ?? 'GET').toUpperCase()
  const body = typeof init.body === 'string' ? JSON.parse(init.body) : undefined
  await wait(120)

  if (path === '/auth/login' && method === 'POST') {
    const u = USERS[body?.username as string]
    if (!u || body?.password !== 'demo') return err(401, 'UNAUTHORIZED', 'Invalid username or password')
    sessionStorage.setItem(SESSION_KEY, u.username)
    return json(200, u)
  }
  if (path === '/auth/logout' && method === 'POST') {
    sessionStorage.removeItem(SESSION_KEY)
    return json(200, { status: 'ok' })
  }
  const user = currentUser()
  if (!user) return err(401, 'UNAUTHORIZED', 'Not authenticated')
  if (path === '/auth/me') return json(200, user)
  if (path === '/meta') return json(200, META)

  const m = path.match(/^\/rosters\/(\d{4}-(?:0[1-9]|1[0-2]))(\/generate|\/save)?$/)
  if (!m) {
    return /^\/rosters\//.test(path)
      ? err(422, 'VALIDATION_ERROR', 'The request is invalid: month must be YYYY-MM')
      : err(404, 'NOT_FOUND', `No mock for ${method} ${path}`)
  }
  const month = m[1]!
  if (!m[2] && method === 'GET') {
    const r = saved.get(month)
    return r ? json(200, r) : err(404, 'NOT_FOUND', 'No roster for this month')
  }
  if (m[2] === '/generate' && method === 'POST') {
    await wait(900)
    const b = buildRoster(month, !!body?.forbid_adjacent_shifts)
    const out: GenerateOutcomeOut = {
      outcome: 'solved',
      assignments: b.assignments,
      coverage_gaps: b.gaps,
      hour_shortfalls: b.shortfalls,
      coverage: { status: 'OPTIMAL', total_uncovered: b.gaps.reduce((s, g) => s + g.missing, 0), locked_uncovered: 0, lower_bound: b.gaps.reduce((s, g) => s + g.proven_missing, 0) },
      min_hours: { status: 'OPTIMAL', total_shortfall: b.shortfalls.reduce((s, x) => s + x.missing_hours, 0) },
      lexicographically_optimal: true,
      preexisting_violations: [],
      costs: b.costs,
      workers: b.workers,
      fingerprint: `mock-${month}-${b.forbidAdjacent}`,
      warnings: [],
    }
    return json(200, out)
  }
  if (m[2] === '/save' && method === 'POST') {
    const req = body as SaveRequest
    const existing = saved.get(month)
    if (existing && (!req.replace_existing || req.expected_version !== existing.version)) {
      return err(409, 'VERSION_CONFLICT', 'The roster changed since it was loaded')
    }
    const b = buildRoster(month, req.forbid_adjacent_shifts)
    const roster: RosterOut = {
      month: `${month}-01`, status: 'DRAFT', version: (existing?.version ?? 0) + 1, is_history: false,
      free_from: [`${month}-01`, 'A'], forbid_adjacent_shifts: req.forbid_adjacent_shifts,
      assignments: req.assignments, violations: [], coverage_gaps: b.gaps, hour_shortfalls: b.shortfalls, hour_overages: [],
      costs: b.costs, workers: b.workers, approval_history: [],
      updated_at: new Date().toISOString(), updated_by: user.display_name,
    }
    saved.set(month, roster)
    return json(200, { roster_id: nextRosterId++, version: roster.version, status: 'DRAFT' })
  }
  return err(404, 'NOT_FOUND', `No mock for ${method} ${path}`)
}
