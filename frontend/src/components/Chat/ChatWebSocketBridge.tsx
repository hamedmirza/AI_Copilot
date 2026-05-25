import { useChatWebSocket } from '@/hooks/useChatWebSocket'

/** App-level chat stream socket; survives right-panel collapse and tab switches. */
export function ChatWebSocketBridge() {
  useChatWebSocket()
  return null
}
