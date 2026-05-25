import { useCallback, useEffect } from 'react'
import { buildAnswerTimingMetadata, toChatMessage, toChatToolCall } from '@/components/Chat/types'
import { useWebSocket } from '@/hooks/useWebSocket'
import {
  assistantMessageIdRef,
  generationStoppedRef,
  resetChatStreamRefs,
} from '@/lib/chatStreamRefs'
import {
  ensureStreamingAssistant,
  finalizeStreamingMessage,
  refreshCurrentSessionSummary,
} from '@/lib/chatStreaming'
import { useChatStore } from '@/store'

export function useChatWebSocket() {
  const currentSessionId = useChatStore((state) => state.currentSessionId)

  useEffect(() => {
    if (!currentSessionId) {
      resetChatStreamRefs()
    }
  }, [currentSessionId])

  const onChatEvent = useCallback((payload: unknown) => {
    const envelope = payload as Record<string, unknown>
    const type = String(envelope.type || '')
    const event = (((envelope.payload as Record<string, unknown> | undefined) || envelope)) as Record<string, unknown>

    if (
      generationStoppedRef.current &&
      (type === 'token' || type === 'status' || type === 'done' || type === 'meta')
    ) {
      return
    }

    const {
      setAssistantStatus,
      updateMessage,
      clearStreamingContent,
      setStreaming,
      appendStreamingContent,
      upsertPendingToolCall,
      finishPendingToolCall,
      addSpawnedRunId,
      clearRunEvents,
      appendMessage,
      addRunEvent,
      setPendingRunId,
    } = useChatStore.getState()

    if (type === 'info') {
      const status = String(event.message || event.status || '').trim()
      if (status) {
        setAssistantStatus(status)
      }
      return
    }

    if (type === 'meta') {
      const provider = String(event.provider || '').trim()
      const model = String(event.model || '').trim()
      const mode = String(event.mode || '').trim()
      const assistantId = ensureStreamingAssistant()
      updateMessage(assistantId, (message) => ({
        ...message,
        metadata: {
          ...(message.metadata || {}),
          provider: provider || message.metadata?.provider,
          model: model || message.metadata?.model,
          mode: mode || message.metadata?.mode,
        },
      }))
      return
    }

    if (type === 'status') {
      const status = String(event.message || event.status || event.label || '').trim()
      if (status) {
        setAssistantStatus(status)
      }
      return
    }

    if (type === 'token') {
      if (event.reset) {
        clearStreamingContent()
      }
      const chunk = String(event.token || event.delta || event.text || event.content || '')
      const assistantId = ensureStreamingAssistant()
      setStreaming(true)
      setAssistantStatus(null)
      appendStreamingContent(chunk)
      updateMessage(assistantId, (message) => ({
        ...message,
        content: `${message.content}${chunk}`,
      }))
      return
    }

    if (type === 'tool_start') {
      setAssistantStatus('Running tools…')
      upsertPendingToolCall(toChatToolCall({
        id: event.tool_call_id ?? event.call_id ?? event.id,
        name: event.name ?? event.tool_name ?? event.tool,
        args: event.args ?? event.arguments ?? event.input ?? {},
        status: 'pending',
        started_at: new Date().toISOString(),
      }))
      return
    }

    if (type === 'tool_end') {
      const toolId = String(event.tool_call_id || event.call_id || event.id || '')
      if (!toolId) return
      const toolError = event.error
        ? String(event.error)
        : event.ok === false
          ? String(event.result ?? event.output ?? 'Tool failed')
          : undefined
      finishPendingToolCall(toolId, {
        status: toolError ? 'error' : 'completed',
        result: event.result ?? event.output,
        error: toolError,
        completedAt: new Date().toISOString(),
      })
      return
    }

    if (type === 'run_spawned') {
      const runId = String(event.run_id || '')
      if (!runId) return
      addSpawnedRunId(runId)
      clearRunEvents(runId)
      const alreadyRendered = useChatStore.getState().messages.some((message) => (
        message.metadata?.type === 'run_spawned' && String(message.metadata?.run_id || '') === runId
      ))
      if (alreadyRendered) return
      if (event.message && typeof event.message === 'object') {
        appendMessage(toChatMessage(event.message as Record<string, unknown>))
        return
      }
      appendMessage({
        id: `assistant-run-${runId}`,
        role: 'assistant',
        content: String(event.message_text || event.message || 'Spawned pipeline task'),
        metadata: {
          type: 'run_spawned',
          run_id: runId,
          task_id: event.task_id,
          display_name: event.display_name ? String(event.display_name) : undefined,
        },
        created_at: new Date().toISOString(),
      })
      return
    }

    if (type === 'run_event') {
      const nested = event.event && typeof event.event === 'object'
        ? event.event as Record<string, unknown>
        : event
      const runId = String(event.run_id || nested.run_id || '')
      if (!runId) return
      addSpawnedRunId(runId)
      if (event.message && typeof event.message === 'object') {
        const summary = toChatMessage(event.message as Record<string, unknown>)
        const existing = useChatStore.getState().messages.some((message) => message.id === summary.id)
        if (!existing) {
          appendMessage(summary)
        }
      }
      addRunEvent(runId, {
        ...nested,
        run_id: runId,
        type: String(nested.type || nested.event_type || ''),
        stage: nested.stage ? String(nested.stage) : null,
        severity: nested.severity ? String(nested.severity) : undefined,
        message: nested.message ? String(nested.message) : '',
      })
      return
    }

    if (type === 'run_summary') {
      if (event.message && typeof event.message === 'object') {
        const summary = toChatMessage(event.message as Record<string, unknown>)
        const existing = useChatStore.getState().messages.some((message) => message.id === summary.id)
        if (!existing) {
          appendMessage(summary)
        }
      }
      void refreshCurrentSessionSummary()
      return
    }

    if (type === 'run_thread_message') {
      if (event.message && typeof event.message === 'object') {
        const threadMessage = toChatMessage(event.message as Record<string, unknown>)
        const existing = useChatStore.getState().messages.some((message) => message.id === threadMessage.id)
        if (!existing) {
          appendMessage(threadMessage)
        }
        if (threadMessage.metadata?.clarification_pending && threadMessage.metadata?.run_id) {
          setPendingRunId(String(threadMessage.metadata.run_id))
        }
      }
      void refreshCurrentSessionSummary()
      return
    }

    if (type === 'error') {
      const message = String(event.message || 'Chat stream failed')
      finalizeStreamingMessage({ content: message, error: message })
      return
    }

    if (type === 'cancelled') {
      generationStoppedRef.current = false
      if (event.message && typeof event.message === 'object' && assistantMessageIdRef.current) {
        const parsed = toChatMessage(event.message as Record<string, unknown>)
        updateMessage(assistantMessageIdRef.current, (message) => ({
          ...parsed,
          id: assistantMessageIdRef.current || parsed.id,
          pending: false,
          metadata: buildAnswerTimingMetadata(message.metadata, parsed.metadata),
        }))
        finalizeStreamingMessage(parsed)
        void refreshCurrentSessionSummary()
        return
      }
      finalizeStreamingMessage()
      void refreshCurrentSessionSummary()
      return
    }

    if (type === 'done') {
      if (event.message && typeof event.message === 'object' && assistantMessageIdRef.current) {
        const parsed = toChatMessage(event.message as Record<string, unknown>)
        updateMessage(assistantMessageIdRef.current, (message) => ({
          ...parsed,
          id: assistantMessageIdRef.current || parsed.id,
          pending: false,
          metadata: buildAnswerTimingMetadata(message.metadata, parsed.metadata),
        }))
        finalizeStreamingMessage(parsed)
        void refreshCurrentSessionSummary()
        return
      }
      finalizeStreamingMessage()
      void refreshCurrentSessionSummary()
    }
  }, [])

  useWebSocket(
    currentSessionId ? `/api/ws/chat/${currentSessionId}` : '',
    onChatEvent,
    !!currentSessionId,
  )
}
