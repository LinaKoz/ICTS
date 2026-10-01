export type ShiftId = 'A' | 'B' | 'C'

const SHIFTS: ShiftId[] = ['A', 'B', 'C']

/**
 * The 24-hour day split into its three shifts (A 00-08, B 08-16, C 16-24).
 * With `active`, that shift's third is drawn in its colour and the others are muted.
 */
export function DayBand({ active, className }: { active?: ShiftId; className?: string }) {
  return (
    <span className={`dayband${active ? ' dayband-one' : ''}${className ? ` ${className}` : ''}`} aria-hidden="true">
      {SHIFTS.map((s) => (
        <span key={s} className={`dayband-seg band-${s}${s === active ? ' is-on' : ''}`} />
      ))}
    </span>
  )
}
