import { afterEach, describe, expect, it, vi } from 'vitest'
import { apiDownload, apiFetch, setUnauthorizedHandler } from './client'
import { ApiError } from '../errors/ApiError'

const json = (status: number, body: unknown) =>
  Promise.resolve(new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }))

afterEach(() => setUnauthorizedHandler(null))

describe('apiFetch', () => {
  it('returns parsed JSON and prefixes /api', async () => {
    const f = vi.fn((_u: string) => json(200, { ok: 1 }))
    expect(await apiFetch('/x', { fetchImpl: f as unknown as typeof fetch })).toEqual({ ok: 1 })
    expect(f.mock.calls[0]![0]).toBe('/api/x')
  })
  it('sends JSON bodies', async () => {
    const f = vi.fn((_u: string, _i: RequestInit) => json(200, {}))
    await apiFetch('/x', { method: 'POST', body: { a: 1 }, fetchImpl: f as unknown as typeof fetch })
    expect(f.mock.calls[0]![1].body).toBe('{"a":1}')
  })
  it('throws ApiError and fires the 401 handler', async () => {
    const h = vi.fn()
    setUnauthorizedHandler(h)
    const f = () => json(401, { error: { code: 'UNAUTHORIZED', message: 'no', details: null } })
    await expect(apiFetch('/x', { fetchImpl: f as unknown as typeof fetch })).rejects.toMatchObject({ status: 401, code: 'UNAUTHORIZED' })
    expect(h).toHaveBeenCalledOnce()
  })
  it('does not fire the 401 handler when skipped', async () => {
    const h = vi.fn()
    setUnauthorizedHandler(h)
    const f = () => json(401, { error: { code: 'UNAUTHORIZED', message: 'no' } })
    await expect(apiFetch('/x', { skipUnauthorizedHandler: true, fetchImpl: f as unknown as typeof fetch })).rejects.toBeInstanceOf(ApiError)
    expect(h).not.toHaveBeenCalled()
  })
  it('maps fetch rejection to a status-0 ApiError', async () => {
    const f = () => Promise.reject(new TypeError('offline'))
    await expect(apiFetch('/x', { fetchImpl: f as unknown as typeof fetch })).rejects.toMatchObject({ status: 0 })
  })
  it('sends a raw body with its own content type instead of JSON', async () => {
    const f = vi.fn((_u: string, _i: RequestInit) => json(200, {}))
    await apiFetch('/imports', { method: 'POST', rawBody: 'a,b\n1,2\n', contentType: 'text/csv', fetchImpl: f as unknown as typeof fetch })
    expect(f.mock.calls[0]![1].body).toBe('a,b\n1,2\n')
    expect(f.mock.calls[0]![1].headers).toEqual({ 'Content-Type': 'text/csv' })
  })
})

describe('apiDownload', () => {
  it('returns the blob and headers', async () => {
    const f = vi.fn((_u: string) => Promise.resolve(new Response('x,y\n', { status: 200, headers: { 'X-Worker-Count': '3' } })))
    const d = await apiDownload('/exports/workers.csv', { fetchImpl: f as unknown as typeof fetch })
    expect(f.mock.calls[0]![0]).toBe('/api/exports/workers.csv')
    expect(await d.blob.text()).toBe('x,y\n')
    expect(d.headers.get('x-worker-count')).toBe('3')
  })
  it('throws the API error shape on failure', async () => {
    const f = () => json(422, { error: { code: 'VALIDATION_ERROR', message: 'bad month', details: null } })
    await expect(apiDownload('/exports/workers.csv?month=x', { fetchImpl: f as unknown as typeof fetch })).rejects.toMatchObject({ status: 422 })
  })
})
