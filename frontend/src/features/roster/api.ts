import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiFetch } from '../../api/client'
import type { components } from '../../api/types'
import type {
  AddAssignmentRequest, EditableAssignmentOut, EditResultOut, GenerateOutcomeOut, MoveAssignmentRequest, RemoveAssignmentRequest,
  Role, RosterOut, SaveRequest, SaveResponseOut, Shift, SuggestionsOut,
} from '../../api/schemas'
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

export const assignmentsKey = (month: string) => ['roster-assignments', month] as const

/** Stored assignments with ids (the edit endpoints address them by id). */
export function useAssignmentIds(month: string, enabled: boolean) {
  return useQuery({
    queryKey: assignmentsKey(month),
    enabled,
    retry: false,
    queryFn: () => apiFetch<EditableAssignmentOut[]>(`/rosters/${month}/assignments`),
  })
}

export interface Slot { date: string; shift: Shift; role: Role }

export function useSuggestions(month: string, slot: Slot | null) {
  return useQuery({
    queryKey: ['roster-suggestions', month, slot],
    enabled: slot != null,
    retry: false,
    queryFn: () => apiFetch<SuggestionsOut>(`/rosters/${month}/suggestions?date=${slot!.date}&shift=${slot!.shift}&role=${slot!.role}`),
  })
}

/** Every edit changes the roster's version, so refetch the roster, ids and suggestions. */
function useEditInvalidation(month: string) {
  const qc = useQueryClient()
  return () =>
    Promise.all([
      qc.invalidateQueries({ queryKey: rosterKey(month) }),
      qc.invalidateQueries({ queryKey: assignmentsKey(month) }),
      qc.invalidateQueries({ queryKey: ['roster-suggestions', month] }),
    ])
}

export function useAddAssignment(month: string) {
  const invalidate = useEditInvalidation(month)
  return useMutation({
    mutationFn: (req: AddAssignmentRequest) =>
      apiFetch<EditResultOut>(`/rosters/${month}/assignments`, { method: 'POST', body: req }),
    onSuccess: invalidate,
  })
}

export function useRemoveAssignment(month: string) {
  const invalidate = useEditInvalidation(month)
  return useMutation({
    mutationFn: ({ id, ...body }: RemoveAssignmentRequest & { id: number }) =>
      apiFetch<EditResultOut>(`/rosters/${month}/assignments/${id}`, { method: 'DELETE', body }),
    onSuccess: invalidate,
  })
}

export function useMoveAssignment(month: string) {
  const invalidate = useEditInvalidation(month)
  return useMutation({
    mutationFn: ({ id, ...body }: MoveAssignmentRequest & { id: number }) =>
      apiFetch<EditResultOut>(`/rosters/${month}/assignments/${id}/move`, { method: 'POST', body }),
    onSuccess: invalidate,
  })
}
