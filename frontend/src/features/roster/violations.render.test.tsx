import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import type { AssignmentOut, ViolationOut } from '../../api/schemas'
import { buildIndex } from './calendarData'
import { RosterCalendar } from './RosterCalendar'

const bad: AssignmentOut = { worker_id: '8', date: '2026-11-10', shift: 'A', role: 'GENERAL_GUARD' }
const ok: AssignmentOut = { worker_id: '9', date: '2026-11-10', shift: 'A', role: 'GENERAL_GUARD' }
const unavailable: ViolationOut = { code: 'UNAVAILABLE', key: ['8', '2026-11-10', 'A'], magnitude: 1, assignments: [bad] }

const render = () => renderToStaticMarkup(
  <RosterCalendar
    view="week" anchor="2026-11-10" today="2026-09-30" targetMonth="2026-11"
    shifts={['A', 'B', 'C']} roles={['GENERAL_GUARD']} demand={[{ shift: 'A', role: 'GENERAL_GUARD', headcount: 2 }]}
    index={buildIndex([{ month: '2026-11', status: 'ready', data: {
      assignments: [bad, ok], gaps: [], costs: null, violations: [unavailable], freeFrom: null,
      workers: [{ worker_id: '8', full_name: 'Worker 02', role: 'GENERAL_GUARD', status: 'ACTIVE' }, { worker_id: '9', full_name: 'Ben Guard', role: 'GENERAL_GUARD', status: 'ACTIVE' }],
    } }])}
    onOpenDay={() => {}}
  />,
)

describe('violation markers', () => {
  it('marks only the violating chip, and says so to screen readers', () => {
    const html = render()
    expect(html.match(/class="chip chip-violation/g)).toHaveLength(1)
    expect(html).toContain('<span class="sr-only">Rule violation: </span><span class="chip-text">Worker 02</span>')
    expect(html).not.toMatch(/sr-only">Rule violation: <\/span><span class="chip-text">Ben Guard/)
  })

  it('announces the count on a view-only cell instead of a label screen readers ignore', () => {
    const html = render()
    expect(html).toContain('<span class="sr-only">1 rule issue</span>')
    expect(html).not.toContain('aria-label="Rule violation"')
  })
})
