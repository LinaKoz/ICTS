import { describe, expect, it } from 'vitest'
import { addDays, addMonths, currentMonth, monthWeeks, rangeLabel, shiftAnchor, startOfWeek, todayIso, visibleMonths, weekDays } from './calendar'

describe('calendar dates', () => {
  it('starts weeks on Monday', () => {
    expect(startOfWeek('2026-10-08')).toBe('2026-10-05') // Thursday
    expect(startOfWeek('2026-10-11')).toBe('2026-10-05') // Sunday belongs to the week before
    expect(weekDays('2026-10-05')[6]).toBe('2026-10-11')
  })
  it('crosses month and year boundaries', () => {
    expect(addDays('2026-12-31', 1)).toBe('2027-01-01')
    expect(addMonths('2026-01-31', 1)).toBe('2026-02-28')
    expect(addMonths('2026-12-15', 1)).toBe('2027-01-15')
    expect(addMonths('2026-01-15', -1)).toBe('2025-12-15')
  })
  it('a week spanning two months touches both rosters', () => {
    expect(visibleMonths('week', '2026-10-29')).toEqual(['2026-10', '2026-11'])
    expect(visibleMonths('day', '2026-10-29')).toEqual(['2026-10'])
  })
  it('month grid is whole Monday-first weeks', () => {
    const weeks = monthWeeks('2026-11-10')
    expect(weeks.every((w) => w.length === 7)).toBe(true)
    expect(weeks[0]![0]).toBe('2026-10-26')
    expect(weeks.at(-1)!.at(-1)).toBe('2026-12-06')
  })
  it('navigates by the view unit', () => {
    expect(shiftAnchor('day', '2026-10-08', 1)).toBe('2026-10-09')
    expect(shiftAnchor('week', '2026-10-08', -1)).toBe('2026-10-01')
    expect(shiftAnchor('month', '2026-10-31', 1)).toBe('2026-11-30')
  })
  it('labels ranges', () => {
    expect(rangeLabel('week', '2026-10-08')).toBe('5 – 11 October 2026')
    expect(rangeLabel('week', '2026-10-29')).toBe('26 Oct – 1 Nov 2026')
    expect(rangeLabel('week', '2026-12-31')).toBe('28 Dec 2026 – 3 Jan 2027')
    expect(rangeLabel('month', '2026-10-08')).toBe('October 2026')
  })
  it('decides today in Israel time', () => {
    expect(todayIso(new Date('2026-10-08T22:30:00Z'))).toBe('2026-10-09')
  })
})

describe('currentMonth', () => {
  it('is the month in Asia/Jerusalem, not in UTC or the browser zone', () => {
    // 30 Sep 22:30 UTC is already 1 Oct 01:30 in Israel.
    expect(currentMonth(new Date('2026-09-30T22:30:00Z'))).toBe('2026-10')
  })
})
