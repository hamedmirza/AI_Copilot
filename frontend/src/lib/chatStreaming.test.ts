import { beforeEach, describe, expect, it } from 'vitest'
import {
  assistantMessageIdRef,
  generationStoppedRef,
  resetChatStreamRefs,
} from '@/lib/chatStreamRefs'
import {
  ensureStreamingAssistant,
  finalizeStreamingMessage,
} from '@/lib/chatStreaming'
import { useChatStore } from '@/store'

function resetChatStore() {
  useChatStore.setState({
    sessions: [],
    currentSessionId: 'session-1',
    historyOpen: false,
    historySearchQuery: '',
    messages: [],
    streaming: true,
    activeMode: 'general',
    modelSelectionMode: 'auto',
    selectedModel: '',
    pendingToolCalls: [],
    spawnedRunIds: [],
    streamingContent: 'partial',
    assistantStatus: 'Thinking…',
    runEventsById: {},
    pendingRunId: null,
    composerPrefill: '',
  })
}

describe('chatStreamRefs', () => {
  beforeEach(() => {
    resetChatStreamRefs()
  })

  it('resetChatStreamRefs clears assistant and stop flags', () => {
    assistantMessageIdRef.current = 'assistant-1'
    generationStoppedRef.current = true
    resetChatStreamRefs()
    expect(assistantMessageIdRef.current).toBeNull()
    expect(generationStoppedRef.current).toBe(false)
  })
})

describe('chatStreaming helpers', () => {
  beforeEach(() => {
    resetChatStreamRefs()
    resetChatStore()
  })

  it('ensureStreamingAssistant creates one pending assistant message', () => {
    const id = ensureStreamingAssistant()
    expect(id).toBe(assistantMessageIdRef.current)
    const messages = useChatStore.getState().messages
    expect(messages).toHaveLength(1)
    expect(messages[0]).toMatchObject({ id, role: 'assistant', pending: true, session_id: 'session-1' })
    expect(ensureStreamingAssistant()).toBe(id)
    expect(useChatStore.getState().messages).toHaveLength(1)
  })

  it('finalizeStreamingMessage clears streaming state and refs', () => {
    const id = ensureStreamingAssistant()
    useChatStore.getState().updateMessage(id, (message) => ({ ...message, content: 'done' }))
    finalizeStreamingMessage()
    expect(assistantMessageIdRef.current).toBeNull()
    const state = useChatStore.getState()
    expect(state.streaming).toBe(false)
    expect(state.streamingContent).toBe('')
    expect(state.assistantStatus).toBeNull()
    expect(state.messages[0]?.pending).toBe(false)
  })
})
