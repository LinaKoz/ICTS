export interface Toast { id: number; message: string }
let toasts: Toast[] = []
let nextId = 1
const listeners = new Set<() => void>()
const emit = () => listeners.forEach((l) => l())

/** A message that is already on screen is not shown again (e.g. one network failure hitting several queries). */
export function showToast(message: string, ms = 6000): void {
  if (toasts.some((t) => t.message === message)) return
  const id = nextId++
  toasts = [...toasts, { id, message }]
  emit()
  setTimeout(() => dismissToast(id), ms)
}
export function dismissToast(id: number): void {
  toasts = toasts.filter((t) => t.id !== id)
  emit()
}

export const subscribe = (l: () => void) => (listeners.add(l), () => void listeners.delete(l))
export const getToasts = () => toasts
