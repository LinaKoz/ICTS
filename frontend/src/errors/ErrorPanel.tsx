import { mapError } from './mapError'

export function ErrorPanel({ error, onReload, onRetry }: { error: unknown; onReload?: () => void; onRetry?: () => void }) {
  const m = mapError(error)
  return (
    <div className="panel panel-error" role="alert">
      <strong>{m.title}</strong>
      <p>{m.message}</p>
      {m.action === 'reload' && onReload && <button onClick={onReload}>Reload data</button>}
      {m.action === 'retry' && onRetry && <button onClick={onRetry}>Try again</button>}
    </div>
  )
}
