/** postMessage protocol between BrowserPanel (parent) and copilot-picker-bridge.js (iframe). */

export const PICKER_MSG = {
  BRIDGE_READY: 'COPILOT_PICKER_BRIDGE_READY',
  ENABLE_PICKER: 'COPILOT_PICKER_ENABLE',
  DISABLE_PICKER: 'COPILOT_PICKER_DISABLE',
  ELEMENT_SELECTED: 'COPILOT_PICKER_ELEMENT_SELECTED',
  QUICK_ADD: 'COPILOT_PICKER_QUICK_ADD',
  PICKER_CANCELLED: 'COPILOT_PICKER_CANCELLED',
} as const

export type PickerMessageType = (typeof PICKER_MSG)[keyof typeof PICKER_MSG]

export interface PickerEnablePayload {
  parentOrigin: string
}

export interface PickerElementPayload {
  url: string
  title: string
  selector: string
  tagName: string
  id?: string
  classNames: string[]
  textPreview: string
  outerHtmlSnippet: string
  rect: { x: number; y: number; width: number; height: number }
  computedStyles?: Record<string, string>
  capturedAt: string
}

export interface PickerBridgeMessage {
  type: PickerMessageType
  payload?: PickerEnablePayload | PickerElementPayload | Record<string, unknown>
}

export function isAllowedPickerOrigin(origin: string): boolean {
  try {
    const { hostname, protocol } = new URL(origin)
    if (protocol !== 'http:' && protocol !== 'https:') return false
    return hostname === 'localhost' || hostname === '127.0.0.1' || hostname === '[::1]'
  } catch {
    return false
  }
}
