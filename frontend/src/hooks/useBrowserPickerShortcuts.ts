import { useEffect } from 'react'
import { useUIStore } from '@/store'

export interface BrowserPickerShortcutHandlers {
  togglePicker: () => void
  addToChat: () => void
  cancelPicker: () => void
}

export interface BrowserPickerShortcutOptions {
  hasSelection: boolean
  pickerActive: boolean
}

export function handleBrowserPickerKeyDown(
  e: KeyboardEvent,
  handlers: BrowserPickerShortcutHandlers,
  options: BrowserPickerShortcutOptions,
): boolean {
  const target = e.target as HTMLElement | null
  const tag = target?.tagName?.toLowerCase()
  if (tag === 'input' || tag === 'textarea' || target?.isContentEditable) return false

  const mod = e.metaKey || e.ctrlKey
  if (mod && e.shiftKey && e.key.toLowerCase() === 'd') {
    e.preventDefault()
    handlers.togglePicker()
    return true
  }
  if (mod && !e.shiftKey && e.key.toLowerCase() === 'l') {
    if (!options.hasSelection) return false
    e.preventDefault()
    handlers.addToChat()
    return true
  }
  if (e.key === 'Escape' && (options.pickerActive || options.hasSelection)) {
    e.preventDefault()
    handlers.cancelPicker()
    return true
  }
  return false
}

export function useBrowserPickerShortcuts(
  enabled: boolean,
  handlers: BrowserPickerShortcutHandlers,
  options: BrowserPickerShortcutOptions,
) {
  useEffect(() => {
    if (!enabled) return

    const onKeyDown = (e: KeyboardEvent) => {
      handleBrowserPickerKeyDown(e, handlers, {
        hasSelection: options.hasSelection,
        pickerActive: options.pickerActive,
      })
    }

    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [enabled, handlers, options, options.hasSelection, options.pickerActive])
}

export function openChatForElementFix() {
  const ui = useUIStore.getState()
  if (ui.rightPanelCollapsed) ui.toggleRightPanel()
  ui.setRightPanelTab('chat')
}
