import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Brain, PanelLeftClose, PanelLeftOpen } from 'lucide-react'
import { api } from '@/api/client'
import { useWebSocket } from '@/hooks/useWebSocket'
import { applyModelsResponse } from '@/lib/lmstudioModels'
import { showError, showSuccess } from '@/lib/toast'
import { Button, EmptyState } from '@/components/ui/primitives'
import {
  useChatStore,
  useEditorStore,
  useProjectStore,
  useSettingsStore,
  type ChatMessage,
  type ChatMode,
  type ChatModelSelectionMode,
} from '@/store'
import { ChatComposer, type ComposerCommand } from './ChatComposer'
import { ChatHistory } from './ChatHistory'
import { MessageList } from './MessageList'
import { ModelSelector } from './ModelSelector'
import {
  buildAnswerTimingMetadata,
  formatRelativeChatTime,
  normalizeChatMode,
  normalizeModelSelectionMode,
  toChatToolCall,
  toChatMessage,
  resolveEffectiveNothink,
  toChatSession,
} from './types'

function buildMcpSummary(servers: Array<Record<string, unknown>>) {
  if (servers.length === 0) {
    return 'No MCP servers configured yet.'
  }
  return servers.map((server) => {
    const name = String(server.name || 'Unnamed server')
    const enabled = server.enabled === false ? 'disabled' : 'enabled'
    const count = Number(server.tool_count || 0)
    const status = server.last_status ? `, status: ${String(server.last_status)}` : ''
    return `- ${name} (${enabled}, ${count} tools${status})`
  }).join('\n')
}

type SessionSelectionOptions = {
  selectionMode?: ChatModelSelectionMode
  modelOverride?: string
}

export function ChatPanel() {
  const projectId = useProjectStore((state) => state.currentProjectId)
  const tabs = useEditorStore((state) => state.tabs)
  const activeTab = useEditorStore((state) => state.activeTab)
  const selection = useEditorStore((state) => state.selection)
  const treeItems = useEditorStore((state) => state.treeItems)
  const availableModels = useSettingsStore((state) => state.models)
  const modelCatalog = useSettingsStore((state) => state.modelCatalog)
  const lmstudioResources = useSettingsStore((state) => state.lmstudioResources)
  const setModels = useSettingsStore((state) => state.setModels)
  const setModelCatalog = useSettingsStore((state) => state.setModelCatalog)
  const setModelRecommendations = useSettingsStore((state) => state.setModelRecommendations)
  const setLmstudioResources = useSettingsStore((state) => state.setLmstudioResources)
  const appSettings = useSettingsStore((state) => state.settings)

  const sessions = useChatStore((state) => state.sessions)
  const currentSessionId = useChatStore((state) => state.currentSessionId)
  const historyOpen = useChatStore((state) => state.historyOpen)
  const historySearchQuery = useChatStore((state) => state.historySearchQuery)
  const messages = useChatStore((state) => state.messages)
  const streaming = useChatStore((state) => state.streaming)
  const activeMode = useChatStore((state) => state.activeMode)
  const modelSelectionMode = useChatStore((state) => state.modelSelectionMode)
  const selectedModel = useChatStore((state) => state.selectedModel)
  const pendingToolCalls = useChatStore((state) => state.pendingToolCalls)
  const runEventsById = useChatStore((state) => state.runEventsById)
  const spawnedRunIds = useChatStore((state) => state.spawnedRunIds)
  const streamingContent = useChatStore((state) => state.streamingContent)
  const assistantStatus = useChatStore((state) => state.assistantStatus)
  const setSessions = useChatStore((state) => state.setSessions)
  const upsertSession = useChatStore((state) => state.upsertSession)
  const removeSession = useChatStore((state) => state.removeSession)
  const setCurrentSessionId = useChatStore((state) => state.setCurrentSessionId)
  const setHistoryOpen = useChatStore((state) => state.setHistoryOpen)
  const setHistorySearchQuery = useChatStore((state) => state.setHistorySearchQuery)
  const setMessages = useChatStore((state) => state.setMessages)
  const appendMessage = useChatStore((state) => state.appendMessage)
  const updateMessage = useChatStore((state) => state.updateMessage)
  const setStreaming = useChatStore((state) => state.setStreaming)
  const setActiveMode = useChatStore((state) => state.setActiveMode)
  const setModelSelectionMode = useChatStore((state) => state.setModelSelectionMode)
  const setSelectedModel = useChatStore((state) => state.setSelectedModel)
  const setPendingToolCalls = useChatStore((state) => state.setPendingToolCalls)
  const upsertPendingToolCall = useChatStore((state) => state.upsertPendingToolCall)
  const finishPendingToolCall = useChatStore((state) => state.finishPendingToolCall)
  const addSpawnedRunId = useChatStore((state) => state.addSpawnedRunId)
  const setSpawnedRunIds = useChatStore((state) => state.setSpawnedRunIds)
  const setStreamingContent = useChatStore((state) => state.setStreamingContent)
  const appendStreamingContent = useChatStore((state) => state.appendStreamingContent)
  const clearStreamingContent = useChatStore((state) => state.clearStreamingContent)
  const setAssistantStatus = useChatStore((state) => state.setAssistantStatus)
  const addRunEvent = useChatStore((state) => state.addRunEvent)
  const clearRunEvents = useChatStore((state) => state.clearRunEvents)
  const pendingRunId = useChatStore((state) => state.pendingRunId)
  const composerPrefill = useChatStore((state) => state.composerPrefill)
  const setPendingRunId = useChatStore((state) => state.setPendingRunId)
  const setComposerPrefill = useChatStore((state) => state.setComposerPrefill)
  const resetChatState = useChatStore((state) => state.resetChatState)

  const [loadingSessions, setLoadingSessions] = useState(false)
  const [loadingMessages, setLoadingMessages] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [deletingSession, setDeletingSession] = useState(false)
  const [runActionBusy, setRunActionBusy] = useState(false)
  const [composerValue, setComposerValue] = useState('')

  useEffect(() => {
    if (composerPrefill) {
      setComposerValue(composerPrefill)
      setComposerPrefill('')
    }
  }, [composerPrefill, setComposerPrefill])
  const [searchResults, setSearchResults] = useState<typeof sessions | null>(null)
  const assistantMessageIdRef = useRef<string | null>(null)

  const currentSession = useMemo(
    () => sessions.find((session) => session.id === currentSessionId) || null,
    [sessions, currentSessionId]
  )
  const effectiveNothink = useMemo(
    () => resolveEffectiveNothink(currentSession?.nothink, appSettings.nothink_default),
    [appSettings.nothink_default, currentSession?.nothink],
  )
  const historySessions = useMemo(
    () => historySearchQuery.trim() ? (searchResults || sessions) : sessions,
    [historySearchQuery, searchResults, sessions]
  )

  const setModeLocally = useCallback((mode: ChatMode) => {
    setActiveMode(mode)
    if (currentSession) {
      upsertSession({ ...currentSession, mode })
    }
  }, [currentSession, setActiveMode, upsertSession])

  const persistModeChange = useCallback(async (mode: ChatMode) => {
    setModeLocally(mode)
    if (!currentSessionId) return
    try {
      const updated = await api.chat.sessions.update(currentSessionId, { mode })
      upsertSession(toChatSession(updated))
    } catch (error) {
      showError(error)
    }
  }, [currentSessionId, setModeLocally, upsertSession])

  const finalizeStreamingMessage = useCallback((override?: Partial<ChatMessage>) => {
    const assistantId = assistantMessageIdRef.current
    const toolCalls = useChatStore.getState().pendingToolCalls
    const content = useChatStore.getState().streamingContent
    if (assistantId) {
      updateMessage(assistantId, (message) => ({
        ...message,
        content: override?.content ?? content ?? message.content,
        metadata: buildAnswerTimingMetadata(message.metadata, override?.metadata),
        tool_calls: toolCalls.length > 0 ? toolCalls : message.tool_calls,
        pending: false,
        error: override?.error,
      }))
    }
    setStreaming(false)
    setPendingToolCalls([])
    clearStreamingContent()
    setAssistantStatus(null)
    assistantMessageIdRef.current = null
  }, [clearStreamingContent, setAssistantStatus, setPendingToolCalls, setStreaming, updateMessage])

  const ensureStreamingAssistant = useCallback(() => {
    if (assistantMessageIdRef.current) return assistantMessageIdRef.current
    const messageId = `assistant-${crypto.randomUUID()}`
    const answerStartedAt = new Date().toISOString()
    assistantMessageIdRef.current = messageId
    appendMessage({
      id: messageId,
      role: 'assistant',
      content: '',
      pending: true,
      session_id: currentSessionId || undefined,
      metadata: { answer_started_at: answerStartedAt },
    })
    return messageId
  }, [appendMessage, currentSessionId])

  const createSession = useCallback(async (
    mode: ChatMode = activeMode,
    options?: SessionSelectionOptions,
  ) => {
    if (!projectId) return null
    const nextSelectionMode = options?.selectionMode ?? 'auto'
    const manualModel = (options?.modelOverride ?? selectedModel).trim()
    const raw = await api.chat.sessions.create({
      project_id: projectId,
      mode,
      title: 'New chat',
      model_override: nextSelectionMode === 'manual' && manualModel ? manualModel : null,
    }) as Record<string, unknown>
    const session = toChatSession(raw)
    upsertSession(session)
    setCurrentSessionId(session.id)
    setMessages([])
    setPendingToolCalls([])
    setSpawnedRunIds([])
    clearRunEvents()
    assistantMessageIdRef.current = null
    setStreaming(false)
    clearStreamingContent()
    setActiveMode(normalizeChatMode(session.mode))
    setModelSelectionMode(normalizeModelSelectionMode(session.model_override))
    setSelectedModel(session.model_override || '')
    return session
  }, [
    activeMode,
    clearRunEvents,
    clearStreamingContent,
    projectId,
    setActiveMode,
    setCurrentSessionId,
    setMessages,
    setModelSelectionMode,
    setPendingToolCalls,
    setSelectedModel,
    setSpawnedRunIds,
    setStreaming,
    selectedModel,
    upsertSession,
  ])

  const loadSessions = useCallback(async () => {
    if (!projectId) {
      resetChatState()
      setSearchResults(null)
      return
    }
    setLoadingSessions(true)
    try {
      const raw = await api.chat.sessions.list(projectId)
      const nextSessions = raw.map((session) => toChatSession(session))
      if (nextSessions.length === 0) {
        await createSession(activeMode)
        return
      }
      setSessions(nextSessions)
      const selected = nextSessions.find((session) => session.id === currentSessionId) || nextSessions[0]
      setCurrentSessionId(selected.id)
      setActiveMode(normalizeChatMode(selected.mode))
      setModelSelectionMode(normalizeModelSelectionMode(selected.model_override))
      setSelectedModel(selected.model_override || '')
    } catch (error) {
      showError(error)
      setSessions([])
      setMessages([])
    } finally {
      setLoadingSessions(false)
    }
  }, [
    activeMode,
    createSession,
    currentSessionId,
    projectId,
    resetChatState,
    setSearchResults,
    setActiveMode,
    setCurrentSessionId,
    setMessages,
    setModelSelectionMode,
    setSelectedModel,
    setSessions,
  ])

  const refreshCurrentSessionSummary = useCallback(async (sessionId?: string | null) => {
    const targetSessionId = sessionId ?? useChatStore.getState().currentSessionId
    if (!targetSessionId) return
    try {
      const updated = await api.chat.sessions.get(targetSessionId)
      upsertSession(toChatSession(updated))
    } catch {
      // Keep the current chat usable even if a background summary refresh fails.
    }
  }, [upsertSession])

  const loadMessages = useCallback(async (sessionId: string) => {
    setLoadingMessages(true)
    try {
      const raw = await api.chat.messages.list(sessionId)
      const items = Array.isArray(raw) ? raw : raw.items
      const parsed = items.map((message) => toChatMessage(message))
      setMessages(parsed)
      setSpawnedRunIds(
        parsed
          .filter((message) => message.metadata?.type === 'run_spawned' && message.metadata?.run_id)
          .map((message) => String(message.metadata?.run_id))
      )
    } catch (error) {
      showError(error)
      setMessages([])
    } finally {
      setLoadingMessages(false)
    }
  }, [setMessages, setSpawnedRunIds])

  useEffect(() => {
    if (availableModels.length > 0) return
    void api.settings
      .models()
      .then((response) =>
        applyModelsResponse(response, {
          setModels,
          setModelCatalog,
          setModelRecommendations,
          setLmstudioResources,
        }),
      )
      .catch(() => {})
  }, [
    availableModels.length,
    setModels,
    setModelCatalog,
    setModelRecommendations,
    setLmstudioResources,
  ])

  useEffect(() => {
    void loadSessions()
  }, [loadSessions])

  useEffect(() => {
    setHistorySearchQuery('')
    setSearchResults(null)
  }, [projectId, setHistorySearchQuery])

  useEffect(() => {
    if (!projectId || !historySearchQuery.trim()) {
      setSearchResults(null)
      return
    }
    let cancelled = false
    const timeoutId = window.setTimeout(() => {
      void api.chat.sessions.list(projectId, historySearchQuery.trim())
        .then((raw) => {
          if (cancelled) return
          setSearchResults(raw.map((session) => toChatSession(session)))
        })
        .catch(() => {
          if (!cancelled) {
            setSearchResults(null)
          }
        })
    }, 200)
    return () => {
      cancelled = true
      window.clearTimeout(timeoutId)
    }
  }, [historySearchQuery, projectId, sessions, setSearchResults])

  useEffect(() => {
    if (!currentSessionId) return
    assistantMessageIdRef.current = null
    setPendingToolCalls([])
    setStreaming(false)
    clearStreamingContent()
    clearRunEvents()
    void loadMessages(currentSessionId)
  }, [clearRunEvents, clearStreamingContent, currentSessionId, loadMessages, setPendingToolCalls, setStreaming])

  useEffect(() => {
    if (!currentSession) return
    setActiveMode(normalizeChatMode(currentSession.mode))
    setModelSelectionMode(normalizeModelSelectionMode(currentSession.model_override))
    setSelectedModel(currentSession.model_override || '')
  }, [currentSession, setActiveMode, setModelSelectionMode, setSelectedModel])

  const handleModelSelectionModeChange = useCallback(async (nextMode: ChatModelSelectionMode) => {
    setModelSelectionMode(nextMode)
    if (nextMode === 'manual') {
      if (!selectedModel) {
        showError('Select a model to use Manual mode')
        return
      }
      if (currentSession) {
        upsertSession({ ...currentSession, model_override: selectedModel })
      }
      if (currentSessionId) {
        try {
          const updated = await api.chat.sessions.update(currentSessionId, { model_override: selectedModel })
          upsertSession(toChatSession(updated))
        } catch (error) {
          showError(error)
          return
        }
      }
      showSuccess(`Chat model set to ${selectedModel}`)
      return
    }
    if (currentSession) {
      upsertSession({ ...currentSession, model_override: null })
    }
    if (currentSessionId) {
      try {
        const updated = await api.chat.sessions.update(currentSessionId, { model_override: null })
        upsertSession(toChatSession(updated))
      } catch (error) {
        showError(error)
        return
      }
    }
    showSuccess('Chat model selection set to Auto')
  }, [
    currentSession,
    currentSessionId,
    selectedModel,
    setModelSelectionMode,
    upsertSession,
  ])

  const handleNothinkToggle = useCallback(async () => {
    if (!currentSessionId || !currentSession) return
    const nextNothink = !effectiveNothink
    upsertSession({ ...currentSession, nothink: nextNothink })
    try {
      const updated = await api.chat.sessions.update(currentSessionId, { nothink: nextNothink })
      upsertSession(toChatSession(updated))
      showSuccess(nextNothink ? 'Thinking disabled (fast mode)' : 'Thinking enabled')
    } catch (error) {
      upsertSession(currentSession)
      showError(error)
    }
  }, [currentSession, currentSessionId, effectiveNothink, upsertSession])

  const handleManualModelChange = useCallback(async (model: string) => {
    setModelSelectionMode('manual')
    setSelectedModel(model)
    if (currentSession) {
      upsertSession({ ...currentSession, model_override: model })
    }
    if (currentSessionId) {
      try {
        const updated = await api.chat.sessions.update(currentSessionId, { model_override: model })
        upsertSession(toChatSession(updated))
      } catch (error) {
        showError(error)
        return
      }
    }
    showSuccess(`Chat model set to ${model}`)
  }, [
    currentSession,
    currentSessionId,
    setModelSelectionMode,
    setSelectedModel,
    upsertSession,
  ])

  const sendMessage = useCallback(async (content: string) => {
    if (!projectId) return
    let sessionId = currentSessionId
    if (!sessionId) {
      const created = await createSession(activeMode, {
        selectionMode: modelSelectionMode,
        modelOverride: selectedModel,
      })
      sessionId = created?.id || null
    }
    if (!sessionId) return

    const userMessage: ChatMessage = {
      id: `user-${crypto.randomUUID()}`,
      role: 'user',
      content,
      session_id: sessionId,
      created_at: new Date().toISOString(),
    }

    appendMessage(userMessage)
    setComposerValue('')
    setSubmitting(true)
    setPendingToolCalls([])
    setStreaming(true)
    setStreamingContent('')
    setAssistantStatus('Thinking…')
    const assistantId = ensureStreamingAssistant()

    try {
      const mentionedFiles = Array.from(
        new Set(
          Array.from(content.matchAll(/(^|\s)@([^\s]+)/g))
            .map((match) => match[2]?.trim())
            .filter((value): value is string => Boolean(value))
        )
      )
      const context = {
        open_files: tabs.map((tab) => tab.path),
        active_file: activeTab,
        mentioned_files: mentionedFiles,
        selection: selection ? {
          path: selection.path,
          text: selection.text,
          cursor_line: selection.startLineNumber,
          start_line: selection.startLineNumber,
          end_line: selection.endLineNumber,
        } : undefined,
      }

      const result = await api.chat.messages.send(sessionId, {
        content,
        mode: activeMode,
        model_override: modelSelectionMode === 'manual' ? selectedModel || undefined : undefined,
        context,
      }) as Record<string, unknown>

      if (result.session && typeof result.session === 'object') {
        upsertSession(toChatSession(result.session as Record<string, unknown>))
      }
      if (result.user_message && typeof result.user_message === 'object') {
        const persistedUser = toChatMessage(result.user_message as Record<string, unknown>)
        updateMessage(userMessage.id, () => persistedUser)
      }
    } catch (error) {
      updateMessage(assistantId, (message) => ({
        ...message,
        content: message.content || (error instanceof Error ? error.message : String(error)),
        pending: false,
        error: error instanceof Error ? error.message : String(error),
      }))
      finalizeStreamingMessage({
        content: error instanceof Error ? error.message : String(error),
        error: error instanceof Error ? error.message : String(error),
      })
      showError(error)
    } finally {
      setSubmitting(false)
    }
  }, [
    activeMode,
    activeTab,
    appendMessage,
    clearRunEvents,
    createSession,
    currentSessionId,
    ensureStreamingAssistant,
    finalizeStreamingMessage,
    modelSelectionMode,
    projectId,
    selectedModel,
    selection,
    setPendingToolCalls,
    setStreaming,
    setAssistantStatus,
    setStreamingContent,
    tabs,
    upsertSession,
    updateMessage,
  ])

  const handleCommand = useCallback(async (command: ComposerCommand) => {
    if (command.type === 'send') {
      await sendMessage(command.content)
      return
    }
    if (command.type === 'mode') {
      await persistModeChange(command.mode)
      showSuccess(`Chat mode set to ${command.mode}`)
      setComposerValue('')
      return
    }
    if (command.type === 'clear') {
      await createSession(activeMode)
      setComposerValue('')
      return
    }
    if (command.type === 'mcp-list') {
      try {
        const servers = await api.mcp.servers.list()
        appendMessage({
          id: `assistant-${crypto.randomUUID()}`,
          role: 'assistant',
          content: buildMcpSummary(servers),
          created_at: new Date().toISOString(),
        })
        setComposerValue('')
      } catch (error) {
        showError(error)
      }
      return
    }
    if (command.type === 'model') {
      await handleManualModelChange(command.model)
      setComposerValue('')
      return
    }
    if (command.type === 'task') {
      let sessionId = currentSessionId
      if (!sessionId) {
        const created = await createSession('agent')
        sessionId = created?.id || null
      }
      if (!sessionId || !projectId) return
      setComposerValue('')
      try {
        let runId = ''
        let taskId = ''
        let runDisplayName = ''
        try {
          const result = await api.chat.spawnTask(sessionId, {
            description: command.description,
            mode: activeMode,
          }) as Record<string, unknown>
          runId = String(result.run_id || (result.run as Record<string, unknown> | undefined)?.id || '')
          taskId = String(result.task_id || (result.task as Record<string, unknown> | undefined)?.id || '')
          runDisplayName = String(result.display_name || (result.run as Record<string, unknown> | undefined)?.display_name || '')
        } catch {
          const fallback = await api.tasks.create({
            project_id: projectId,
            description: command.description,
            validation_profile: 'react',
          }) as Record<string, unknown>
          const runObj = fallback.run as Record<string, unknown> | undefined
          runId = String(runObj?.id || '')
          taskId = String((fallback.task as Record<string, unknown> | undefined)?.id || '')
          runDisplayName = String(runObj?.display_name || '')
        }

        if (!runId) {
          throw new Error('Task created, but no run id was returned')
        }

        addSpawnedRunId(runId)
        clearRunEvents(runId)
        appendMessage({
          id: `assistant-run-${runId}`,
          role: 'assistant',
          content: `Spawned pipeline task${command.description ? `: ${command.description}` : ''}`,
          created_at: new Date().toISOString(),
          metadata: {
            type: 'run_spawned',
            run_id: runId,
            task_id: taskId,
            display_name: runDisplayName || undefined,
          },
        })
        void refreshCurrentSessionSummary(sessionId)
        showSuccess('Pipeline task started')
      } catch (error) {
        showError(error)
      }
    }
  }, [
    activeMode,
    addSpawnedRunId,
    appendMessage,
    clearRunEvents,
    createSession,
    currentSessionId,
    handleManualModelChange,
    persistModeChange,
    projectId,
    refreshCurrentSessionSummary,
    sendMessage,
  ])

  const onChatEvent = useCallback((payload: unknown) => {
    const envelope = payload as Record<string, unknown>
    const type = String(envelope.type || '')
    const event = (((envelope.payload as Record<string, unknown> | undefined) || envelope)) as Record<string, unknown>

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

    if (type === 'error') {
      const message = String(event.message || 'Chat stream failed')
      finalizeStreamingMessage({ content: message, error: message })
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
  }, [
    addRunEvent,
    addSpawnedRunId,
    appendMessage,
    appendStreamingContent,
    clearRunEvents,
    clearStreamingContent,
    ensureStreamingAssistant,
    finalizeStreamingMessage,
    finishPendingToolCall,
    setAssistantStatus,
    setStreaming,
    updateMessage,
    upsertPendingToolCall,
    refreshCurrentSessionSummary,
  ])

  useWebSocket(
    currentSessionId ? `/api/ws/chat/${currentSessionId}` : '',
    onChatEvent,
    !!currentSessionId
  )

  const handleSelectSession = useCallback((sessionId: string) => {
    setCurrentSessionId(sessionId)
  }, [setCurrentSessionId])

  const handleDeleteSession = useCallback(async (sessionId: string) => {
    if (!confirm('Delete this chat session?')) return
    setDeletingSession(true)
    try {
      await api.chat.sessions.delete(sessionId)
      removeSession(sessionId)
      const nextSessions = useChatStore.getState().sessions.filter((session) => session.id !== sessionId)
      if (nextSessions.length > 0) {
        setCurrentSessionId(nextSessions[0].id)
      } else {
        await createSession(activeMode)
      }
    } catch (error) {
      showError(error)
    } finally {
      setDeletingSession(false)
    }
  }, [activeMode, createSession, removeSession, setCurrentSessionId])

  const handleApproveRun = useCallback(async (runId: string) => {
    setRunActionBusy(true)
    try {
      await api.runs.approve(runId)
      showSuccess('Run approved')
    } catch (error) {
      showError(error)
    } finally {
      setRunActionBusy(false)
    }
  }, [])

  const handleRejectRun = useCallback(async (runId: string) => {
    const reason = prompt('Reason for rejection?')
    if (!reason) return
    setRunActionBusy(true)
    try {
      await api.runs.reject(runId, reason)
      showSuccess('Run rejected')
    } catch (error) {
      showError(error)
    } finally {
      setRunActionBusy(false)
    }
  }, [])

  const handleRetryRun = useCallback(async (runId: string, feedback?: string) => {
    setRunActionBusy(true)
    try {
      await api.runs.retry(runId, feedback ? { feedback } : undefined)
      showSuccess('Run retried')
    } catch (error) {
      showError(error)
    } finally {
      setRunActionBusy(false)
    }
  }, [])

  const handleSendAndRetry = useCallback(async (content: string, runId: string) => {
    if (!currentSessionId) return
    setSubmitting(true)
    try {
      const userMessage = await api.chat.messages.send(currentSessionId, {
        content,
        mode: activeMode,
        model_override: modelSelectionMode === 'manual' ? selectedModel : undefined,
      }) as Record<string, unknown>
      appendMessage(toChatMessage(userMessage))
      setComposerValue('')
      await api.runs.retry(runId, { feedback: content })
      setPendingRunId(null)
      showSuccess('Message sent and pipeline retry started')
    } catch (error) {
      showError(error)
    } finally {
      setSubmitting(false)
    }
  }, [
    activeMode,
    appendMessage,
    currentSessionId,
    modelSelectionMode,
    selectedModel,
    setPendingRunId,
  ])

  useEffect(() => {
    if (!spawnedRunIds.length) return
    const seenIds = new Set(Object.keys(runEventsById))
    spawnedRunIds.forEach((runId) => {
      if (seenIds.has(runId)) return
      void api.runs.events(runId)
        .then((events) => {
          ;(events as Array<Record<string, unknown>>).forEach((event) => addRunEvent(runId, {
            type: String(event.event_type || event.type || ''),
            stage: event.stage ? String(event.stage) : null,
            severity: event.severity ? String(event.severity) : undefined,
            message: event.message ? String(event.message) : '',
            run_id: runId,
            ...event,
          }))
        })
        .catch(() => {})
    })
  }, [addRunEvent, runEventsById, spawnedRunIds])

  if (!projectId) {
    return <EmptyState title="No project" description="Select a project to start chatting about its codebase." />
  }

  return (
    <div className="h-full flex flex-col overflow-hidden">
      <div className="p-3 border-b border-[var(--border)] bg-[var(--bg-secondary)] space-y-3">
        <div className="flex items-center justify-between gap-2">
          <Button variant="secondary" onClick={() => setHistoryOpen(!historyOpen)}>
            {historyOpen ? <PanelLeftClose className="h-4 w-4" /> : <PanelLeftOpen className="h-4 w-4" />}
            <span>History</span>
          </Button>
          {currentSession && (
            <div className="min-w-0 text-right">
              <div className="truncate text-sm text-[var(--text-primary)]">
                {String(currentSession.title || 'Untitled chat')}
              </div>
              <div className="text-[11px] text-[var(--text-secondary)]">
                {formatRelativeChatTime(
                  currentSession.last_message_at || currentSession.updated_at || currentSession.created_at || null
                ) || 'New conversation'}
              </div>
            </div>
          )}
        </div>
        <div className="flex items-center gap-2">
          <ModelSelector
            mode={activeMode}
            selectionMode={modelSelectionMode}
            model={selectedModel}
            models={availableModels}
            catalog={modelCatalog}
            resourcesPressure={lmstudioResources?.pressure ?? null}
            disabled={loadingSessions || submitting}
            onSelectionModeChange={(mode) => void handleModelSelectionModeChange(mode)}
            onModelChange={(model) => void handleManualModelChange(model)}
          />
          {currentSessionId && (
            <button
              type="button"
              title={effectiveNothink ? 'Thinking: off (fast)' : 'Thinking: on'}
              aria-label={effectiveNothink ? 'Thinking off' : 'Thinking on'}
              aria-pressed={!effectiveNothink}
              disabled={loadingSessions || submitting}
              onClick={() => void handleNothinkToggle()}
              className={`shrink-0 rounded border px-2 py-1.5 transition-colors ${
                effectiveNothink
                  ? 'border-[var(--border)] text-[var(--text-secondary)] hover:text-[var(--text-primary)]'
                  : 'border-[var(--accent)] bg-[var(--accent)]/15 text-[var(--accent)]'
              } disabled:opacity-50`}
            >
              <Brain className="h-4 w-4" />
            </button>
          )}
        </div>
        {currentSession && (
          <div className="flex items-center justify-between text-[11px] text-[var(--text-secondary)]">
            <span>{Number(currentSession.message_count || 0)} messages</span>
            <span>
              {`Mode: ${activeMode} • Model: ${
                modelSelectionMode === 'manual' && selectedModel ? selectedModel : 'Auto'
              } • Thinking: ${effectiveNothink ? 'off' : 'on'}`}
            </span>
          </div>
        )}
      </div>

      <div className="flex min-h-0 flex-1 overflow-hidden">
        {historyOpen && (
          <ChatHistory
            sessions={historySessions}
            currentSessionId={currentSessionId}
            loading={loadingSessions}
            deleting={deletingSession}
            searchQuery={historySearchQuery}
            onSearchChange={setHistorySearchQuery}
            onSelect={handleSelectSession}
            onNew={() => void createSession(activeMode)}
            onDelete={handleDeleteSession}
          />
        )}

        <div className="min-w-0 flex-1 flex flex-col overflow-hidden">
          <MessageList
            messages={messages}
            loading={loadingMessages}
            streaming={streaming}
            thinkingLabel={assistantStatus || (streaming ? 'Thinking…' : null)}
            pendingToolCalls={pendingToolCalls}
            runEventsById={runEventsById}
            runActionBusy={runActionBusy}
            onApproveRun={handleApproveRun}
            onRejectRun={handleRejectRun}
            onRetryRun={handleRetryRun}
          />

          <ChatComposer
            value={composerValue}
            mode={activeMode}
            treeItems={treeItems}
            disabled={submitting || loadingSessions}
            submitting={submitting}
            pendingRunId={pendingRunId}
            onChange={setComposerValue}
            onModeChange={(mode) => void persistModeChange(mode)}
            onCommand={handleCommand}
            onSendAndRetry={handleSendAndRetry}
          />
        </div>
      </div>
    </div>
  )
}
