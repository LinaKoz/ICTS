import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiFetch } from '../../api/client'
import type {
  ContractApplyOut, ContractInput, ContractPreviewOut, ContractsOut, Role, WorkerCreate, WorkerDetailOut, WorkerOut,
  WorkerPatch, WorkerStatus, WorkerUpdateOut,
} from '../../api/schemas'

/** Prefix of `rosterKey(month)`: every cached roster. */
const ROSTER_ROOT = ['roster'] as const

export interface WorkerFilters { q: string; status: WorkerStatus | ''; role: Role | '' }

export const workersKey = ['workers'] as const
export const workerKey = (id: number) => ['worker', id] as const
export const contractsKey = (id: number, month: string) => ['contracts', id, month] as const

export function useWorkers(f: WorkerFilters) {
  const qs = new URLSearchParams()
  if (f.q.trim()) qs.set('q', f.q.trim())
  if (f.status) qs.set('status', f.status)
  if (f.role) qs.set('role', f.role)
  const suffix = qs.size ? `?${qs}` : ''
  return useQuery({ queryKey: [...workersKey, f], queryFn: () => apiFetch<WorkerOut[]>(`/workers${suffix}`) })
}

export function useWorker(id: number) {
  return useQuery({ queryKey: workerKey(id), retry: false, queryFn: () => apiFetch<WorkerDetailOut>(`/workers/${id}`) })
}

export function useContracts(id: number, resolvedFor: string) {
  return useQuery({
    queryKey: contractsKey(id, resolvedFor),
    retry: false,
    queryFn: () => apiFetch<ContractsOut>(`/workers/${id}/contracts?resolved_for=${resolvedFor}`),
  })
}

/** Rosters shown elsewhere may have changed (violations, approval), so drop them along with worker data. */
function useInvalidateAll() {
  const qc = useQueryClient()
  return () => Promise.all([
    qc.invalidateQueries({ queryKey: workersKey }),
    qc.invalidateQueries({ queryKey: ['worker'] }),
    qc.invalidateQueries({ queryKey: ['contracts'] }),
    qc.invalidateQueries({ queryKey: ROSTER_ROOT }),
  ])
}

export function useCreateWorker() {
  const invalidate = useInvalidateAll()
  return useMutation({
    mutationFn: (body: WorkerCreate) => apiFetch<WorkerOut>('/workers', { method: 'POST', body }),
    onSuccess: invalidate,
  })
}

export function useUpdateWorker(id: number) {
  const invalidate = useInvalidateAll()
  return useMutation({
    mutationFn: (body: WorkerPatch) => apiFetch<WorkerUpdateOut>(`/workers/${id}`, { method: 'PATCH', body }),
    onSuccess: invalidate,
  })
}

export function useDeleteWorker() {
  const invalidate = useInvalidateAll()
  return useMutation({
    mutationFn: (id: number) => apiFetch<void>(`/workers/${id}`, { method: 'DELETE' }),
    onSuccess: invalidate,
  })
}

export function usePreviewContract(id: number) {
  return useMutation({
    mutationFn: (body: ContractInput) => apiFetch<ContractPreviewOut>(`/workers/${id}/contracts/preview`, { method: 'POST', body }),
  })
}

export function useApplyContract(id: number) {
  const invalidate = useInvalidateAll()
  return useMutation({
    mutationFn: (body: ContractInput & { fingerprint: string }) =>
      apiFetch<ContractApplyOut>(`/workers/${id}/contracts`, { method: 'POST', body }),
    onSuccess: invalidate,
  })
}
