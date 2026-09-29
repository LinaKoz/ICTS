import { describe, expect, it } from 'vitest'
import type { AssignmentOut } from '../../api/schemas'
import { rosterCsv } from './exportCsv'

const a = (over: Partial<AssignmentOut>): AssignmentOut => ({ worker_id: '1', date: '2026-10-05', shift: 'A', role: 'SCREENER', ...over })

describe('rosterCsv', () => {
  it('has a BOM, a header and rows sorted by date, shift, role', () => {
    const csv = rosterCsv([a({ date: '2026-10-06', worker_id: '2' }), a({ shift: 'B' }), a({})], (id) => `W${id}`)
    const lines = csv.slice(1).trim().split('\r\n')
    expect(csv.startsWith('﻿')).toBe(true)
    expect(lines[0]).toBe('date,shift,role,worker_id,worker')
    expect(lines.slice(1)).toEqual([
      '2026-10-05,A,SCREENER,1,W1',
      '2026-10-05,B,SCREENER,1,W1',
      '2026-10-06,A,SCREENER,2,W2',
    ])
  })
  it('quotes commas and quotes, and neutralises formulas', () => {
    const csv = rosterCsv([a({ worker_id: '1' }), a({ worker_id: '2', shift: 'B' })], (id) => (id === '1' ? 'Levi, "Dana"' : '=SUM(A1)'))
    expect(csv).toContain('"Levi, ""Dana"""')
    expect(csv).toContain("'=SUM(A1)")
  })
})
