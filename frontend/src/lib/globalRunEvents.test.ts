import { describe, expect, it, vi } from 'vitest'
import { dispatchGlobalRunEvent, subscribeGlobalRunEvents } from './globalRunEvents'

describe('globalRunEvents', () => {
  it('notifies subscribers and unsubscribes cleanly', () => {
    const listener = vi.fn()
    const unsubscribe = subscribeGlobalRunEvents(listener)
    dispatchGlobalRunEvent({ type: 'run_completed', run_id: 'r1' })
    expect(listener).toHaveBeenCalledWith({ type: 'run_completed', run_id: 'r1' })
    unsubscribe()
    listener.mockClear()
    dispatchGlobalRunEvent({ type: 'ping' })
    expect(listener).not.toHaveBeenCalled()
  })
})
