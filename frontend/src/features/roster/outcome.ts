import type { GenerateOutcomeOut } from '../../api/schemas'

export interface OutcomeSummary {
  kind: 'ok' | 'warning' | 'error'
  messages: string[]
}

/** §7 "Plain-language outcomes". */
export function describeOutcome(o: GenerateOutcomeOut): OutcomeSummary {
  switch (o.outcome) {
    case 'no_solution_within_limit':
      return { kind: 'error', messages: ['No roster found in time; nothing was changed'] }
    case 'invalid_input':
      return { kind: 'error', messages: ['The roster inputs are invalid; nothing was changed'] }
    case 'engine_error':
      return { kind: 'error', messages: [o.message ? `Scheduling engine error: ${o.message}` : 'Scheduling engine error'] }
  }
  const messages: string[] = []
  const cov = o.coverage
  const k = cov ? cov.lower_bound - cov.locked_uncovered : 0
  if (o.lexicographically_optimal) messages.push('Best possible roster')
  if (cov?.status === 'OPTIMAL' && k >= 1) {
    messages.push(`At least ${k} upcoming position${k === 1 ? '' : 's'} cannot be filled with current contracts`)
  }
  if (cov?.status === 'FEASIBLE') {
    messages.push(
      k > 0
        ? `Best found within the time limit; at least ${k} upcoming position${k === 1 ? '' : 's'} cannot be filled`
        : 'Best found within the time limit',
    )
  }
  if (o.min_hours?.status === 'FEASIBLE') messages.push('Minimum hours not proven optimal within the time limit')
  const warning = k >= 1 || cov?.status === 'FEASIBLE' || o.min_hours?.status === 'FEASIBLE'
  return { kind: warning ? 'warning' : 'ok', messages }
}
