import { describe, expect, it, vi } from 'vitest'
import {
  BROWSER_REFRESH_EVENT,
  dispatchBrowserRefresh,
  listenForBrowserRefresh,
} from './browserRefresh'

describe('browserRefresh', () => {
  it('dispatches copilot-browser-refresh custom event', () => {
    const handler = vi.fn()
    window.addEventListener(BROWSER_REFRESH_EVENT, handler)
    dispatchBrowserRefresh()
    expect(handler).toHaveBeenCalledTimes(1)
    window.removeEventListener(BROWSER_REFRESH_EVENT, handler)
  })

  it('listenForBrowserRefresh invokes callback and unsubscribes', () => {
    const handler = vi.fn()
    const unsubscribe = listenForBrowserRefresh(handler)
    dispatchBrowserRefresh()
    expect(handler).toHaveBeenCalledTimes(1)
    unsubscribe()
    dispatchBrowserRefresh()
    expect(handler).toHaveBeenCalledTimes(1)
  })
})
