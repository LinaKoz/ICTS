export interface Toast { id: number; message: string }
let toasts: Toast[] = []
let nextId = 1
const listeners = new Set<() => void>()
const emit = () => listeners.forEach((l) => l())

export function showToast(message: string, ms = 6000): void {
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
