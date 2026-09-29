import { ApiError } from './ApiError'

export type ErrorAction = 'login' | 'reload' | 'retry' | 'none'
export type ErrorPresentation = 'toast' | 'panel' | 'redirect'

export interface MappedError {
  title: string
  message: string
  presentation: ErrorPresentation
  action: ErrorAction
}

/**
 * Maps any thrown value to what the UI shows (§7 "Common states"):
 * 401 -> login, 403 -> message, 409 -> "data changed, reload", network -> toast.
 */
export function mapError(err: unknown): MappedError {
  if (!(err instanceof ApiError)) {
    return {
      title: 'Unexpected error',
      message: err instanceof Error ? err.message : 'Something went wrong.',
      presentation: 'toast',
      action: 'none',
    }
  }
  if (err.status === 0) {
    return {
      title: 'Network error',
      message: 'Could not reach the server. Check your connection and try again.',
      presentation: 'toast',
      action: 'retry',
    }
  }
  if (err.status === 401) {
    return { title: 'Signed out', message: 'Your session has ended. Please sign in again.', presentation: 'redirect', action: 'login' }
  }
  if (err.status === 403) {
    return { title: 'Not allowed', message: 'You do not have permission to do this.', presentation: 'panel', action: 'none' }
  }
  if (err.status === 409) {
    return {
      title: 'Data changed',
      message: 'The data changed since you loaded it. Reload and try again.',
      presentation: 'panel',
      action: 'reload',
    }
  }
  if (err.status === 429 && err.code === 'GENERATION_IN_PROGRESS') {
    return {
      title: 'Generation in progress',
      message: 'A roster is already being generated. Wait for it to finish, then try again.',
      presentation: 'panel',
      action: 'retry',
    }
  }
  if (err.status === 422 && err.code === 'LOCKED_SHIFT') {
    return { title: 'Shift already started', message: err.message, presentation: 'panel', action: 'reload' }
  }
  if (err.status === 422 && err.code === 'HARD_VIOLATIONS') {
    return { title: 'Hard constraint violated', message: err.message, presentation: 'panel', action: 'none' }
  }
  if (err.status >= 500) {
    return {
      title: err.code === 'ENGINE_ERROR' ? 'Scheduling engine error' : 'Server error',
      message: `${err.message} Nothing was changed.`,
      presentation: 'panel',
      action: 'retry',
    }
  }
  return { title: 'Request failed', message: err.message, presentation: 'panel', action: 'none' }
}
