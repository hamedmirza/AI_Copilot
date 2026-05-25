/** Module-level refs shared by ChatPanel and the app-level chat WebSocket bridge. */
export const assistantMessageIdRef = { current: null as string | null }
export const generationStoppedRef = { current: false }

export function resetChatStreamRefs() {
  assistantMessageIdRef.current = null
  generationStoppedRef.current = false
}
