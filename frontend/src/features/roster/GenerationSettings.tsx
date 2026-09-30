import { useEffect, useId, useRef, useState } from 'react'

interface Props {
  forbid: boolean
  onForbid: (on: boolean) => void
  monthName: string
  /** What the stored roster was generated with, or null when there is none. */
  storedForbid: boolean | null
}

/** Popover with the options for the next generation. Closes on Escape or a click outside. */
export function GenerationSettings({ forbid, onForbid, monthName, storedForbid }: Props) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  const popId = useId()

  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) setOpen(false) }
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false) }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => { document.removeEventListener('mousedown', onDown); document.removeEventListener('keydown', onKey) }
  }, [open])

  return (
    <div className="gen-settings" ref={ref}>
      <button className={`gen-toggle${open ? ' is-open' : ''}`} aria-expanded={open} aria-controls={popId} onClick={() => setOpen(!open)}>
        <span aria-hidden="true">⚙</span> Generation settings
        {forbid && <span className="gen-dot" title="Back-to-back shifts are forbidden" />}
      </button>
      {open && (
        <div className="gen-pop" id={popId} role="dialog" aria-label="Generation settings">
          <div className="gen-head">
            <h4>Next generation</h4>
            <button className="modal-close" onClick={() => setOpen(false)} aria-label="Close" title="Close">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" aria-hidden="true">
                <path d="M5 5l14 14M19 5L5 19" />
              </svg>
            </button>
          </div>
          <p className="muted gen-scope">For {monthName}</p>
          <label className="switch-row">
            <span className="switch-text">
              <strong>Forbid back-to-back shifts</strong>
              <span className="muted">A worker will not get two shifts in a row.</span>
            </span>
            <input type="checkbox" role="switch" className="switch" checked={forbid} onChange={(e) => onForbid(e.target.checked)} />
          </label>
          {storedForbid !== null && (
            <p className="gen-current">
              Current roster: <strong>{storedForbid ? 'no back-to-back shifts' : 'back-to-back shifts allowed'}</strong>
            </p>
          )}
        </div>
      )}
    </div>
  )
}
