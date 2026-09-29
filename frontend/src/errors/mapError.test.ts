import { describe, expect, it } from 'vitest'
import { ApiError, parseErrorBody } from './ApiError'
import { mapError } from './mapError'

describe('parseErrorBody', () => {
  it('parses the §6 error shape', () => {
    const e = parseErrorBody(409, { error: { code: 'STALE_PREVIEW', message: 'stale', details: { a: 1 } } })
    expect(e).toMatchObject({ status: 409, code: 'STALE_PREVIEW', message: 'stale', details: { a: 1 } })
  })
  it('falls back for unknown bodies and FastAPI validation detail', () => {
    expect(parseErrorBody(502, 'x').code).toBe('HTTP_502')
    expect(parseErrorBody(422, { detail: [1] }).code).toBe('VALIDATION_ERROR')
  })
})

describe('mapError', () => {
  const api = (status: number, code = 'X') => new ApiError(status, code, 'msg')
  it('401 redirects to login', () => {
    expect(mapError(api(401))).toMatchObject({ presentation: 'redirect', action: 'login' })
  })
  it('403 shows a message panel', () => {
    expect(mapError(api(403))).toMatchObject({ title: 'Not allowed', presentation: 'panel' })
  })
  it('409 offers reload', () => {
    expect(mapError(api(409, 'STALE_PREVIEW'))).toMatchObject({ action: 'reload' })
  })
  it('network error is a toast with retry', () => {
    expect(mapError(api(0, 'NETWORK_ERROR'))).toMatchObject({ presentation: 'toast', action: 'retry' })
  })
  it('429 generation in progress', () => {
    expect(mapError(api(429, 'GENERATION_IN_PROGRESS')).title).toBe('Generation in progress')
  })
  it('500 ENGINE_ERROR says nothing was changed', () => {
    const m = mapError(api(500, 'ENGINE_ERROR'))
    expect(m.title).toBe('Scheduling engine error')
    expect(m.message).toContain('Nothing was changed')
  })
  it('non-ApiError values become a toast', () => {
    expect(mapError(new Error('boom'))).toMatchObject({ message: 'boom', presentation: 'toast' })
    expect(mapError('weird').message).toBe('Something went wrong.')
  })
})
