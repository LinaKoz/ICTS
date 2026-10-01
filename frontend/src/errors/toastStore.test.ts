import { afterEach, describe, expect, it } from 'vitest'
import { dismissToast, getToasts, showToast } from './toastStore'

afterEach(() => getToasts().forEach((t) => dismissToast(t.id)))

describe('showToast', () => {
  it('shows an identical message only once while it is visible', () => {
    showToast('Network error')
    showToast('Network error')
    showToast('Other')
    expect(getToasts().map((t) => t.message)).toEqual(['Network error', 'Other'])
  })
  it('shows the message again after it was dismissed', () => {
    showToast('Network error')
    dismissToast(getToasts()[0]!.id)
    showToast('Network error')
    expect(getToasts()).toHaveLength(1)
  })
})
