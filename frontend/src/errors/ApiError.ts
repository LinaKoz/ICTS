/** Error thrown by the API client. `status` 0 means a network failure. */
export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly details: unknown

  constructor(status: number, code: string, message: string, details: unknown = null) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.details = details
  }
}

/** Parse the §6 error body `{"error": {code, message, details}}`; tolerates other shapes. */
export function parseErrorBody(status: number, body: unknown): ApiError {
  if (body && typeof body === 'object') {
    const err = (body as { error?: unknown }).error
    if (err && typeof err === 'object') {
      const e = err as { code?: unknown; message?: unknown; details?: unknown }
      return new ApiError(
        status,
        typeof e.code === 'string' ? e.code : `HTTP_${status}`,
        typeof e.message === 'string' ? e.message : `Request failed (${status})`,
        e.details ?? null,
      )
    }
    // FastAPI's default validation shape: {"detail": [...]}
    if ('detail' in body) {
      return new ApiError(status, 'VALIDATION_ERROR', 'Request validation failed', (body as { detail: unknown }).detail)
    }
  }
  return new ApiError(status, `HTTP_${status}`, `Request failed (${status})`)
}
