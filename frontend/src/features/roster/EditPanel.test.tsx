import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'
import type { RosterOut } from '../../api/schemas'
import { ApiError } from '../../errors/ApiError'
import { EditPanel } from './EditPanel'

// Mutation state as the panel sees it after the requests settled; nothing is fetched.
const state = vi.hoisted(() => ({ removeError: null as unknown, moveError: null as unknown }))
const mutation = (error: unknown) => ({ error, isPending: false, reset: () => {}, mutate: () => {}, variables: undefined })

vi.mock('./api', () => ({
  useAddAssignment: () => mutation(null),
  useRemoveAssignment: () => mutation(state.removeError),
  useMoveAssignment: () => mutation(state.moveError),
  useSuggestions: () => ({ isPending: false, isError: false, data: undefined }),
}))

const roster = {
  month: '2099-02-01', status: 'DRAFT', version: 3, is_history: false,
  workers: [{ worker_id: '100000001', full_name: 'Dana Levi', role: 'GENERAL_GUARD' }],
} as unknown as RosterOut
const selection = { kind: 'assignment' as const, id: 7, assignment: { worker_id: '100000001', date: '2099-02-10', shift: 'B' as const, role: 'GENERAL_GUARD' as const } }
const render = () => renderToStaticMarkup(<EditPanel month="2099-02" roster={roster} selection={selection} onClose={() => {}} />)
const count = (html: string, text: string) => html.split(text).length - 1

describe('EditPanel errors', () => {
  it('shows a failed removal once, under a removal heading', () => {
    state.moveError = null
    state.removeError = new ApiError(422, 'LOCKED_SHIFT', 'shift started')
    const html = render()
    expect(count(html, 'role="alert"')).toBe(1)
    expect(count(html, 'That shift has already started')).toBe(1)
    expect(html).toContain("Can&#x27;t remove Dana Levi from 2099-02-10 shift B")
    expect(html).not.toContain('Can&#x27;t do that')
  })

  it('keeps the reload action for a removal conflict, shown once', () => {
    state.moveError = null
    state.removeError = new ApiError(409, 'VERSION_CONFLICT', 'stale')
    const html = render()
    expect(count(html, 'role="alert"')).toBe(1)
    expect(count(html, 'Reload data')).toBe(1)
  })

  it('still shows a failed move once, under the move-target heading', () => {
    state.removeError = null
    state.moveError = new ApiError(422, 'LOCKED_SHIFT', 'shift started')
    const html = render()
    expect(count(html, 'role="alert"')).toBe(1)
    expect(html).toContain('Can&#x27;t do that: Dana Levi on 2099-02-10 shift B')
  })
})
