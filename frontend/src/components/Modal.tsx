import { useEffect, useRef, type KeyboardEvent, type ReactNode } from 'react'

const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'

interface Props {
  label: string
  onClose: () => void
  children: ReactNode
}

/** A centered dialog over a dimmed backdrop. Closes on Escape or a click outside; focus moves into it and Tab stays inside while open. */
export function Modal({ label, onClose, children }: Props) {
  const ref = useRef<HTMLDivElement>(null)
  const close = useRef(onClose)
  useEffect(() => { close.current = onClose })

  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null
    ref.current?.focus()
    return () => { previous?.focus?.() }
  }, [])

  // Keys are handled on the dialog, not the document: focus is inside the top-most dialog, so with two
  // stacked (a shift popup and the edit dialog over it) only the top one reacts.
  function onKeyDown(e: KeyboardEvent<HTMLDivElement>) {
    if (e.key === 'Escape') { close.current(); return }
    if (e.key !== 'Tab' || !ref.current) return
    // Keep Tab inside the dialog: wrap from the last focusable element to the first and back.
    const items = Array.from(ref.current.querySelectorAll<HTMLElement>(FOCUSABLE)).filter((el) => el.offsetParent !== null || el === document.activeElement)
    if (items.length === 0) { e.preventDefault(); return }
    const first = items[0]!
    const last = items[items.length - 1]!
    const active = document.activeElement
    if (e.shiftKey && (active === first || active === ref.current)) { e.preventDefault(); last.focus() }
    else if (!e.shiftKey && active === last) { e.preventDefault(); first.focus() }
  }

  return (
    <div className="modal-backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget) close.current() }}>
      <div className="modal" role="dialog" aria-modal="true" aria-label={label} tabIndex={-1} ref={ref} onKeyDown={onKeyDown}>
        {children}
      </div>
    </div>
  )
}
