import { beforeEach, describe, expect, it, vi } from 'vitest'
import { handleBrowserPickerKeyDown } from './useBrowserPickerShortcuts'

function keyEvent(init: Partial<KeyboardEvent> & { key: string }): KeyboardEvent {
  return {
    metaKey: false,
    ctrlKey: false,
    shiftKey: false,
    preventDefault: vi.fn(),
    target: document.body,
    ...init,
  } as unknown as KeyboardEvent
}

describe('handleBrowserPickerKeyDown', () => {
  const handlers = {
    togglePicker: vi.fn(),
    addToChat: vi.fn(),
    cancelPicker: vi.fn(),
  }

  beforeEach(() => {
    handlers.togglePicker.mockClear()
    handlers.addToChat.mockClear()
    handlers.cancelPicker.mockClear()
  })

  it('Cmd+Shift+D toggles picker', () => {
    const e = keyEvent({ key: 'd', metaKey: true, shiftKey: true })
    expect(handleBrowserPickerKeyDown(e, handlers, { hasSelection: false, pickerActive: false })).toBe(true)
    expect(e.preventDefault).toHaveBeenCalled()
    expect(handlers.togglePicker).toHaveBeenCalled()
  })

  it('Cmd+L adds to chat only when selection exists', () => {
    const withoutSelection = keyEvent({ key: 'l', metaKey: true })
    expect(handleBrowserPickerKeyDown(withoutSelection, handlers, { hasSelection: false, pickerActive: false })).toBe(false)
    expect(withoutSelection.preventDefault).not.toHaveBeenCalled()

    handlers.addToChat.mockClear()
    const withSelection = keyEvent({ key: 'l', metaKey: true })
    expect(handleBrowserPickerKeyDown(withSelection, handlers, { hasSelection: true, pickerActive: false })).toBe(true)
    expect(withSelection.preventDefault).toHaveBeenCalled()
    expect(handlers.addToChat).toHaveBeenCalled()
  })

  it('Cmd+Shift+L does not add to chat', () => {
    const e = keyEvent({ key: 'l', metaKey: true, shiftKey: true })
    expect(handleBrowserPickerKeyDown(e, handlers, { hasSelection: true, pickerActive: false })).toBe(false)
    expect(handlers.addToChat).not.toHaveBeenCalled()
  })

  it('Escape cancels when picker active or selection present', () => {
    const e = keyEvent({ key: 'Escape' })
    expect(handleBrowserPickerKeyDown(e, handlers, { hasSelection: false, pickerActive: true })).toBe(true)
    expect(e.preventDefault).toHaveBeenCalled()
    expect(handlers.cancelPicker).toHaveBeenCalled()
  })

  it('ignores shortcuts when typing in input', () => {
    const input = document.createElement('input')
    const e = keyEvent({ key: 'd', metaKey: true, shiftKey: true, target: input })
    expect(handleBrowserPickerKeyDown(e, handlers, { hasSelection: false, pickerActive: false })).toBe(false)
  })
})
