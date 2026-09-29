import { useSyncExternalStore } from 'react'
import { dismissToast, getToasts, subscribe } from './toastStore'

export function Toaster() {
  const list = useSyncExternalStore(subscribe, getToasts)
  return (
    <div className="toaster" role="status" aria-live="polite">
      {list.map((t) => (
        <div key={t.id} className="toast" onClick={() => dismissToast(t.id)}>{t.message}</div>
      ))}
    </div>
  )
}
