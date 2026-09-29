import { ApiError, parseErrorBody } from '../errors/ApiError'
import { mockFetch } from './mock/mockServer'

/** VITE_API_MOCK=1 serves responses from the in-browser mock instead of the live API. */
export const USE_MOCK = import.meta.env.VITE_API_MOCK === '1'

type UnauthorizedHandler = () => void
let onUnauthorized: UnauthorizedHandler | null = null

/** Registered by the auth provider; called on every 401 from a non-auth-probe request. */
export function setUnauthorizedHandler(h: UnauthorizedHandler | null): void {
  onUnauthorized = h
}

export interface RequestOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'
  body?: unknown
  /** Skip the global 401 handler (used by the /auth/me probe and login). */
  skipUnauthorizedHandler?: boolean
  fetchImpl?: typeof fetch
}

export async function apiFetch<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const init: RequestInit = {
    method: opts.method ?? 'GET',
    credentials: 'same-origin',
    headers: opts.body !== undefined ? { 'Content-Type': 'application/json' } : undefined,
    body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
  }
  const doFetch = opts.fetchImpl ?? (USE_MOCK ? mockFetch : fetch)
  let res: Response
  try {
    res = await doFetch(`/api${path}`, init)
  } catch {
    throw new ApiError(0, 'NETWORK_ERROR', 'Network request failed')
  }
  if (res.status === 204) return undefined as T
  let body: unknown = null
  try {
    body = await res.json()
  } catch {
    body = null
  }
  if (!res.ok) {
    const err = parseErrorBody(res.status, body)
    if (res.status === 401 && !opts.skipUnauthorizedHandler) onUnauthorized?.()
    throw err
  }
  return body as T
}
