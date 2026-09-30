import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { clampDate } from './calendar'
import { DatePicker } from './DatePicker'

const render = (props: Partial<Parameters<typeof DatePicker>[0]> = {}) =>
  renderToStaticMarkup(<DatePicker value="2026-11-07" onChange={() => {}} label="Go to date" {...props} />)
const days = (html: string) => [...html.matchAll(/data-date="([^"]+)"[^>]*?(disabled)?[^>]*>/g)]

describe('clampDate', () => {
  it('limits a date to the bounds and leaves unbounded dates alone', () => {
    expect(clampDate('2099-01-01', '2099-02-01', '2099-02-28')).toBe('2099-02-01')
    expect(clampDate('2099-03-01', '2099-02-01', '2099-02-28')).toBe('2099-02-28')
    expect(clampDate('2099-02-10', '2099-02-01', '2099-02-28')).toBe('2099-02-10')
    expect(clampDate('2099-02-10')).toBe('2099-02-10')
  })
})

describe('DatePicker', () => {
  it('shows the date on the trigger and stays closed until clicked', () => {
    const html = render()
    expect(html).toContain('7 Nov 2026')
    expect(html).toContain('aria-expanded="false"')
    expect(html).not.toContain('role="dialog"')
  })

  it('opens on a Monday-first grid of whole weeks with the value selected', () => {
    const html = render({ defaultOpen: true })
    expect(html).toContain('November 2026')
    expect(html.indexOf('>Mo<')).toBeLessThan(html.indexOf('>Su<'))
    const dates = days(html).map((m) => m[1])
    expect(dates[0]).toBe('2026-10-26') // Monday on or before 1 Nov (a Sunday)
    expect(dates.length % 7).toBe(0)
    expect(html).toMatch(/dp-day dp-sel[^>]*data-date="2026-11-07"|data-date="2026-11-07"[^>]*dp-sel/)
    expect(html.match(/aria-pressed="true"/g)).toHaveLength(1)
  })

  it('disables days outside min and max', () => {
    const html = render({ defaultOpen: true, min: '2026-11-01', max: '2026-11-30' })
    const disabled = (d: string) => new RegExp(`data-date="${d}"[^>]*disabled`).test(html)
    expect(disabled('2026-10-31')).toBe(true)
    expect(disabled('2026-12-01')).toBe(true)
    expect(disabled('2026-11-15')).toBe(false)
  })

  it('opens in the page flow when inline, and floats otherwise', () => {
    expect(render({ defaultOpen: true, inline: true })).toContain('class="dp-pop dp-pop-inline"')
    expect(render({ defaultOpen: true })).toContain('class="dp-pop"')
  })
})
