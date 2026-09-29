import type { AssignmentOut } from '../../api/schemas'

/** Spreadsheet formula injection: a cell starting with one of these is run as a formula by Excel. */
const cell = (v: string) => {
  const safe = /^[=+\-@\t\r]/.test(v) ? `'${v}` : v
  return /[",\r\n]/.test(safe) ? `"${safe.replace(/"/g, '""')}"` : safe
}

/** UTF-8 CSV (with BOM, so Excel reads Hebrew names) of assignments, sorted by date, shift, role, name. */
export function rosterCsv(assignments: AssignmentOut[], nameOf: (workerId: string) => string): string {
  const rows = assignments
    .map((a) => [a.date, a.shift, a.role, a.worker_id, nameOf(a.worker_id)])
    .sort((x, y) => x.slice(0, 3).join('|').localeCompare(y.slice(0, 3).join('|')) || x[4]!.localeCompare(y[4]!))
  return '﻿' + [['date', 'shift', 'role', 'worker_id', 'worker'], ...rows].map((r) => r.map(cell).join(',')).join('\r\n') + '\r\n'
}

export function downloadCsv(filename: string, content: string): void {
  const url = URL.createObjectURL(new Blob([content], { type: 'text/csv;charset=utf-8' }))
  const link = Object.assign(document.createElement('a'), { href: url, download: filename })
  document.body.append(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}
