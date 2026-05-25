import { api } from '@/api/client'
import { buildAnswerTimingMetadata, toChatSession } from '@/components/Chat/types'
import { assistantMessageIdRef } from '@/lib/chatStreamRefs'
import { useChatStore, type ChatMessage } from '@/store'

export async function refreshCurrentSessionSummary(sessionId?: string | null) {
  const targetSessionId = sessionId ?? useChatStore.getState().currentSessionId
  if (!targetSessionId) return
  try {
    const updated = await api.chat.sessions.get(targetSessionId)
    useChatStore.getState().upsertSession(toChatSession(updated))
  } catch {
    // Keep the current chat usable even if a background summary refresh fails.
  }
}

export function finalizeStreamingMessage(override?: Partial<ChatMessage>) {
  const assistantId = assistantMessageIdRef.current
  const {
    pendingToolCalls,
    streamingContent,
    updateMessage,
    setStreaming,
    setPendingToolCalls,
    clearStreamingContent,
    setAssistantStatus,
  } = useChatStore.getState()
  if (assistantId) {
    updateMessage(assistantId, (message) => ({
      ...message,
      content: override?.content ?? streamingContent ?? message.content,
      metadata: buildAnswerTimingMetadata(message.metadata, override?.metadata),
      tool_calls: pendingToolCalls.length > 0 ? pendingToolCalls : message.tool_calls,
      pending: false,
      error: override?.error,
    }))
  }
  setStreaming(false)
  setPendingToolCalls([])
  clearStreamingContent()
  setAssistantStatus(null)
  assistantMessageIdRef.current = null
}

export function ensureStreamingAssistant(): string {
  if (assistantMessageIdRef.current) return assistantMessageIdRef.current
  const currentSessionId = useChatStore.getState().currentSessionId
  const messageId = `assistant-${crypto.randomUUID()}`
  const answerStartedAt = new Date().toISOString()
  assistantMessageIdRef.current = messageId
  useChatStore.getState().appendMessage({
    id: messageId,
    role: 'assistant',
    content: '',
    pending: true,
    session_id: currentSessionId || undefined,
    metadata: { answer_started_at: answerStartedAt },
  })
  return messageId
}
