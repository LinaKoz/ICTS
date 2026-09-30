import { type QueryClient, useMutation, useQueries, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiFetch } from '../../api/client'
import type { components } from '../../api/types'
import type {
  AddAssignmentRequest, ApprovalPreviewOut, ApprovalResultOut, ApproveRequest, EditableAssignmentOut, EditResultOut, GenerateOutcomeOut, MoveAssignmentRequest, RemoveAssignmentRequest,
  Role, RosterOut, SaveRequest, SaveResponseOut, Shift, SuggestionsOut, SwapAssignmentRequest,
} from '../../api/schemas'
import { ApiError } from '../../errors/ApiError'
import { addMonths } from './calendar'

/** Month is YYYY-MM in the URL path (assumption: not yet in OpenAPI). */
export const rosterKey = (month: string) => ['roster', month] as const

export function useMeta() {
  return useQuery({ queryKey: ['meta'], staleTime: Infinity, queryFn: () => apiFetch<components['schemas']['MetaOut']>('/meta') })
}

/** Resolves to null when no roster exists for the month (404). */
async function fetchRoster(month: string): Promise<RosterOut | null> {
  try {
    return await apiFetch<RosterOut>(`/rosters/${month}`)
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) return null
    throw e
  }
}

export function useRoster(month: string) {
  return useQuery({ queryKey: rosterKey(month), retry: false, queryFn: () => fetchRoster(month) })
}

/** One roster query per month a calendar view touches; shares the cache with `useRoster`. */
export function useRosters(months: string[]) {
  return useQueries({ queries: months.map((month) => ({ queryKey: rosterKey(month), retry: false, queryFn: () => fetchRoster(month) })) })
}

export function useGenerate(month: string) {
  return useMutation({
    // A fresh seed per click, so Regenerate can produce a different roster from the same data.
    mutationFn: (forbid_adjacent_shifts: boolean) =>
      apiFetch<GenerateOutcomeOut>(`/rosters/${month}/generate`, {
        method: 'POST',
        body: { forbid_adjacent_shifts, random_seed: Math.floor(Math.random() * 2 ** 31) },
      }),
  })
}

export function useSave(month: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (req: SaveRequest) => apiFetch<SaveResponseOut>(`/rosters/${month}/save`, { method: 'POST', body: req }),
    onSuccess: () => invalidateAfterEdit(qc, month),
  })
}

export const assignmentsKey = (month: string) => ['roster-assignments', month] as const

export interface AssignmentIds { version: number; assignments: EditableAssignmentOut[] }

/** Stored assignments with ids (the edit endpoints address them by id), fetched for exactly the roster
 * version on screen: the server refuses a list of another version (409), so ids joined to the shown
 * roster never point at a row that has moved since. While the next version loads, the previous list
 * stays as placeholder data and callers must compare `version` before using it. */
export function useAssignmentIds(month: string, version: number | undefined, enabled: boolean) {
  const qc = useQueryClient()
  return useQuery({
    queryKey: [...assignmentsKey(month), version],
    enabled: enabled && version !== undefined,
    retry: false,
    placeholderData: (prev) => prev,
    queryFn: async (): Promise<AssignmentIds> => {
      try {
        const assignments = await apiFetch<EditableAssignmentOut[]>(`/rosters/${month}/assignments?version=${version}`)
        return { version: version!, assignments }
      } catch (e) {
        // The roster moved on: refetch it, which re-keys this query to the new version.
        if (e instanceof ApiError && e.status === 409) void qc.invalidateQueries({ queryKey: rosterKey(month) })
        throw e
      }
    },
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

/** Up to five workers who could take over an assignment: the fix options for a violation. */
export function useReplacements(month: string, assignmentId: number, enabled: boolean) {
  return useQuery({
    queryKey: ['roster-suggestions', month, 'replacements', assignmentId],
    enabled,
    retry: false,
    queryFn: () => apiFetch<SuggestionsOut>(`/rosters/${month}/assignments/${assignmentId}/replacements`),
  })
}

/** The months before and after `month` (YYYY-MM), across year boundaries. */
export const adjacentMonths = (month: string): [string, string] =>
  [addMonths(`${month}-01`, -1).slice(0, 7), addMonths(`${month}-01`, 1).slice(0, 7)]

/** Every edit changes the roster's version, so refetch the roster, ids and suggestions. A boundary
 * assignment also changes the neighbouring months' adjacency violations, so those are refetched too;
 * `invalidateQueries` only refetches queries that are on screen, the rest are just marked stale. */
export function invalidateAfterEdit(qc: QueryClient, month: string) {
  return Promise.all([month, ...adjacentMonths(month)].flatMap((m) => [
    qc.invalidateQueries({ queryKey: rosterKey(m) }),
    qc.invalidateQueries({ queryKey: assignmentsKey(m) }),
    qc.invalidateQueries({ queryKey: ['roster-suggestions', m] }),
  ]))
}

function useEditInvalidation(month: string) {
  const qc = useQueryClient()
  return () => invalidateAfterEdit(qc, month)
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

export function useSwapAssignment(month: string) {
  const invalidate = useEditInvalidation(month)
  return useMutation({
    mutationFn: ({ id, ...body }: SwapAssignmentRequest & { id: number }) =>
      apiFetch<EditResultOut>(`/rosters/${month}/assignments/${id}/swap`, { method: 'POST', body }),
    onSuccess: invalidate,
  })
}

/** Under the roster key so every roster invalidation (edits, save, approve) refreshes the preview too. */
export const approvalPreviewKey = (month: string) => [...rosterKey(month), 'approval-preview'] as const

export function useApprovalPreview(month: string, enabled: boolean) {
  return useQuery({
    queryKey: approvalPreviewKey(month),
    enabled,
    retry: false,
    queryFn: () => apiFetch<ApprovalPreviewOut>(`/rosters/${month}/approval-preview`),
  })
}

export function useApprove(month: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (req: ApproveRequest) => apiFetch<ApprovalResultOut>(`/rosters/${month}/approve`, { method: 'POST', body: req }),
    onSettled: () => qc.invalidateQueries({ queryKey: rosterKey(month) }),
  })
}

export function useRevoke(month: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (req: { expected_version: number; approval_id: number; reason: string }) =>
      apiFetch<ApprovalResultOut>(`/rosters/${month}/revoke`, { method: 'POST', body: req }),
    onSettled: () => qc.invalidateQueries({ queryKey: rosterKey(month) }),
  })
}
