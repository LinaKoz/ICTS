import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import type { CostsOut } from '../../api/schemas'
import { CostBreakdown } from './CostBreakdown'
import { costRows, costScale, ilsWhole, totalHours } from './costChart'

const nameOf = (id: string) => `Worker ${id.padStart(2, '0')}`
const w = (id: string, hours: number, amount: string | null) => ({ worker_id: id, hours, amount_ils: amount })

// 12 workers: ties on 10,000 and 8,280, a zero, and an unknown rate; hours deliberately not proportional to cost.
const perWorker = [
  w('3', 64, '3200.00'), w('13', 160, '10000.00'), w('9', 120, '10000.00'), w('5', 168, '8400.00'),
  w('2', 184, '9200.00'), w('7', 144, '8280.00'), w('6', 144, '8280.00'), w('4', 152, '6840.00'),
  w('8', 96, '4800.00'), w('10', 40, null), w('11', 0, '0.00'), w('12', 80, '2400.00'),
]
const costs: CostsOut = { per_shift: [], per_worker: perWorker, monthly_total_ils: '71400.00', unknown_cost_worker_count: 1 }

describe('cost rows', () => {
  it('sorts by cost descending, ties by name then id, unknown last', () => {
    expect(costRows(perWorker, nameOf).map((r) => r.workerId)).toEqual(['9', '13', '2', '5', '6', '7', '4', '8', '3', '12', '11', '10'])
  })
  it('breaks a same-name tie by id so the order is stable', () => {
    const rows = costRows([w('2', 8, '100.00'), w('1', 8, '100.00')], () => 'Same Name')
    expect(rows.map((r) => r.workerId)).toEqual(['1', '2'])
  })
  it('keeps the backend amounts as sent rather than deriving them from hours', () => {
    const rows = costRows(perWorker, nameOf)
    expect(rows.find((r) => r.workerId === '2')).toEqual({ workerId: '2', name: 'Worker 02', hours: 184, amount: '9200.00' })
  })
  it('totals hours across every worker, as the table always has', () => {
    expect(totalHours(perWorker)).toBe(1352)
    expect(totalHours([w('1', 0.1, '1'), w('2', 0.2, '1')])).toBe(0.3)
  })
})

describe('cost scale', () => {
  it('starts at zero and covers the largest cost with round ticks', () => {
    expect(costScale(costRows(perWorker, nameOf))).toEqual({ max: 10000, ticks: [0, 2500, 5000, 7500, 10000] })
    expect(costScale(costRows([w('1', 1, '3200.00')], nameOf))).toEqual({ max: 4000, ticks: [0, 1000, 2000, 3000, 4000] })
    expect(costScale(costRows([w('1', 1, '9600.00')], nameOf)).max).toBe(10000)
    expect(costScale(costRows([w('1', 1, '11160.00')], nameOf))).toEqual({ max: 15000, ticks: [0, 5000, 10000, 15000] })
  })
  it('stays finite when every cost is zero or unknown', () => {
    expect(costScale(costRows([w('1', 0, '0.00'), w('2', 8, null)], nameOf))).toEqual({ max: 1, ticks: [0] })
  })
  it('labels ticks in whole shekels', () => {
    expect(ilsWhole(5000)).toBe('₪5,000')
  })
})

describe('cost breakdown dialog', () => {
  const html = renderToStaticMarkup(<CostBreakdown costs={costs} nameOf={nameOf} onClose={() => {}} />)
  const chartRows = (s: string) => s.match(/class="lollipop-row/g) ?? []

  it('opens on the chart, showing the top 10 with a way to see all', () => {
    expect(html).toMatch(/aria-pressed="true" class="seg-on">Chart/)
    expect(html).toContain('Top 10 by estimated cost')
    expect(chartRows(html)).toHaveLength(10)
    expect(html).toContain('Show all 12')
    expect(html).not.toContain('Worker 11') // 11th by cost (₪0) is past the cut
  })
  it('shows totals for every worker, not just the visible ten', () => {
    expect(html).toContain('₪71,400.00')
    expect(html).toContain('1,352<span class="cost-unit"> h</span>')
    expect(html).toContain('1 worker with unknown cost not included')
  })
  it('gives each row the full name, hours and exact cost for screen readers and truncation', () => {
    expect(html).toContain('aria-label="Worker 02 · 184 scheduled hours · ₪9,200.00 estimated cost" title="Worker 02"')
    expect(html).toContain('Estimated cost (ILS)')
  })
  it('places the largest cost at the end of the axis', () => {
    expect(html).toContain('class="lollipop-dot" style="left:100%"')
    expect(html).toContain('class="lollipop-dot" style="left:32%"') // ₪3,200 of ₪10,000
  })
  it('hides the show-all control at 10 workers or fewer', () => {
    const few = { ...costs, per_worker: perWorker.slice(0, 3) }
    const small = renderToStaticMarkup(<CostBreakdown costs={few} nameOf={nameOf} onClose={() => {}} />)
    expect(small).toContain('All 3 workers · highest cost first')
    expect(small).not.toContain('Show all')
    expect(chartRows(small)).toHaveLength(3)
  })
  it('says so when nobody is scheduled', () => {
    const empty = renderToStaticMarkup(<CostBreakdown costs={{ ...costs, per_worker: [], monthly_total_ils: '0.00', unknown_cost_worker_count: 0 }} nameOf={nameOf} onClose={() => {}} />)
    expect(empty).toContain('No workers are scheduled this month.')
    expect(empty).not.toContain('lollipop')
  })
})
