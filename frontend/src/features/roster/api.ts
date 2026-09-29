import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiFetch } from '../../api/client'
import type { components } from '../../api/types'
import type { GenerateOutcomeOut, RosterOut, SaveRequest, SaveResponseOut } from '../../api/rosterContract'
import { ApiError } from '../../errors/ApiError'

/** Month is YYYY-MM in the URL path (assumption: not yet in OpenAPI). */
export const rosterKey = (month: string) => ['roster', month] as const

export function useMeta() {
  return useQuery({ queryKey: ['meta'], staleTime: Infinity, queryFn: () => apiFetch<components['schemas']['MetaOut']>('/meta') })
}

/** Resolves to null when no roster exists for the month (404). */
export function useRoster(month: string) {
  return useQuery({
    queryKey: rosterKey(month),
    retry: false,
    queryFn: async () => {
      try {
        return await apiFetch<RosterOut>(`/rosters/${month}`)
      } catch (e) {
        if (e instanceof ApiError && e.status === 404) return null
        throw e
      }
    },
  })
}

export function useGenerate(month: string) {
  return useMutation({
    mutationFn: (forbid_adjacent_shifts: boolean) =>
      apiFetch<GenerateOutcomeOut>(`/rosters/${month}/generate`, { method: 'POST', body: { forbid_adjacent_shifts } }),
  })
}

export function useSave(month: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (req: SaveRequest) => apiFetch<SaveResponseOut>(`/rosters/${month}/save`, { method: 'POST', body: req }),
    onSuccess: () => qc.invalidateQueries({ queryKey: rosterKey(month) }),
  })
}
