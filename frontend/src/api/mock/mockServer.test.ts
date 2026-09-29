import { beforeEach, describe, expect, it, vi } from 'vitest'
import { apiFetch } from '../client'
import type { GenerateOutcomeOut } from '../schemas'
import { mockFetch } from './mockServer'

const f = mockFetch as unknown as typeof fetch

beforeEach(() => {
  const store = new Map<string, string>()
  vi.stubGlobal('sessionStorage', {
    getItem: (k: string) => store.get(k) ?? null,
    setItem: (k: string, v: string) => void store.set(k, v),
    removeItem: (k: string) => void store.delete(k),
  })
})

describe('mock API flow', () => {
  it('401 before login, then login, generate and save', async () => {
    await expect(apiFetch('/meta', { fetchImpl: f })).rejects.toMatchObject({ status: 401 })
    await expect(apiFetch('/auth/login', { method: 'POST', body: { username: 'planner', password: 'x' }, fetchImpl: f })).rejects.toMatchObject({ status: 401 })
    await apiFetch('/auth/login', { method: 'POST', body: { username: 'planner', password: 'demo' }, fetchImpl: f })
    await expect(apiFetch('/rosters/2026-10', { fetchImpl: f })).rejects.toMatchObject({ status: 404 })
    const gen = await apiFetch<GenerateOutcomeOut>('/rosters/2026-10/generate', { method: 'POST', body: { forbid_adjacent_shifts: false }, fetchImpl: f })
    expect(gen.outcome).toBe('solved')
    expect(gen.coverage_gaps!.length).toBeGreaterThan(0)
    expect(gen.workers!.length).toBeGreaterThan(0)
    expect(gen.costs!.per_shift!.length).toBeGreaterThan(0)
    await expect(apiFetch('/rosters/2026-3', { fetchImpl: f })).rejects.toMatchObject({ status: 422, code: 'VALIDATION_ERROR' })
    const save = await apiFetch<{ status: string }>('/rosters/2026-10/save', {
      method: 'POST', fetchImpl: f,
      body: { assignments: gen.assignments, fingerprint: gen.fingerprint, expected_version: null, replace_existing: false, forbid_adjacent_shifts: false },
    })
    expect(save.status).toBe('DRAFT')
    const roster = await apiFetch<{ assignments: unknown[]; updated_by: string }>('/rosters/2026-10', { fetchImpl: f })
    expect(roster.assignments.length).toBe(gen.assignments!.length)
    expect(roster.updated_by).toBe('Demo Planner')
  }, 10000)
})
