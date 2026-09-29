import { useMutation, useQueryClient } from '@tanstack/react-query'
import { apiDownload, apiFetch } from '../../api/client'
import type { ImportConfirmOut, ImportPreviewOut } from '../../api/schemas'
import type { Decision } from './logic'

/** Worker data, contracts and rosters may all change when an import is confirmed. */
function useInvalidateAll() {
  const qc = useQueryClient()
  return () => Promise.all(
    [['workers'], ['worker'], ['contracts'], ['roster']].map((queryKey) => qc.invalidateQueries({ queryKey })),
  )
}

/** Uploads the file as a raw `text/csv` body and returns the preview (nothing is applied yet). */
export function useUploadImport() {
  return useMutation({
    mutationFn: (file: File) =>
      apiFetch<ImportPreviewOut>('/imports', { method: 'POST', rawBody: file, contentType: 'text/csv' }),
  })
}

export function useConfirmImport(importId: number) {
  const invalidate = useInvalidateAll()
  return useMutation({
    mutationFn: (decisions: Record<string, Decision>) =>
      apiFetch<ImportConfirmOut>(`/imports/${importId}/confirm`, { method: 'POST', body: { decisions } }),
    onSuccess: invalidate,
  })
}

export function useExportWorkers() {
  return useMutation({ mutationFn: (month: string) => apiDownload(`/exports/workers.csv?month=${month}`) })
}
