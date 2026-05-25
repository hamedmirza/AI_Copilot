import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Brain, PanelLeftClose, PanelLeftOpen } from 'lucide-react'
import { api } from '@/api/client'
import {
  assistantMessageIdRef,
  generationStoppedRef,
} from '@/lib/chatStreamRefs'
import {
  ensureStreamingAssistant,
  finalizeStreamingMessage,
  refreshCurrentSessionSummary,
} from '@/lib/chatStreaming'
import { applyModelsResponse } from '@/lib/lmstudioModels'
import {
  elementContextPayload,
  formatElementForAgentTask,
  inferValidationProfile,
} from '@/lib/pageElementContext'
import { showError, showSuccess } from '@/lib/toast'
import { ConfirmModal } from '@/components/ui/ConfirmModal'
import { Button, EmptyState } from '@/components/ui/primitives'
import {
  useChatStore,
  useEditorStore,
  useProjectStore,
  useSettingsStore,
  useUIStore,
  type ChatMessage,
  type ChatMode,
  type ChatModelSelectionMode,
} from '@/store'
import { ChatComposer, type ComposerCommand } from './ChatComposer'
import { ChatHistory } from './ChatHistory'
import { MessageList } from './MessageList'
import { ModelSelector } from './ModelSelector'
import {
  formatRelativeChatTime,
  normalizeChatMode,
  normalizeModelSelectionMode,
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

function extractRunIds(messages: ChatMessage[]): string[] {
  const runIds = new Set<string>()
  messages.forEach((message) => {
    const metadata = message.metadata || {}
    const runId = metadata.run_id
    if (runId) {
      runIds.add(String(runId))
    }
    const referencedRuns = metadata.run_ids
    if (Array.isArray(referencedRuns)) {
      referencedRuns.forEach((item) => {
        if (item) runIds.add(String(item))
      })
    }
  })
  return Array.from(runIds)
}

type SessionSelectionOptions = {
  selectionMode?: ChatModelSelectionMode
  modelOverride?: string
  allowWebSearch?: boolean
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
  const addSpawnedRunId = useChatStore((state) => state.addSpawnedRunId)
  const setSpawnedRunIds = useChatStore((state) => state.setSpawnedRunIds)
  const setStreamingContent = useChatStore((state) => state.setStreamingContent)
  const clearStreamingContent = useChatStore((state) => state.clearStreamingContent)
  const setAssistantStatus = useChatStore((state) => state.setAssistantStatus)
  const addRunEvent = useChatStore((state) => state.addRunEvent)
  const clearRunEvents = useChatStore((state) => state.clearRunEvents)
  const pendingRunId = useChatStore((state) => state.pendingRunId)
  const composerPrefill = useChatStore((state) => state.composerPrefill)
  const setComposerPrefill = useChatStore((state) => state.setComposerPrefill)
  const resetChatState = useChatStore((state) => state.resetChatState)
  const pageElementSelection = useUIStore((state) => state.pageElementSelection)
  const setPageElementSelection = useUIStore((state) => state.setPageElementSelection)
  const setRightPanelTab = useUIStore((state) => state.setRightPanelTab)
  const requestOpenRunDrawer = useUIStore((state) => state.requestOpenRunDrawer)
  const [loadingSessions, setLoadingSessions] = useState(false)
  const [linkedRunStatus, setLinkedRunStatus] = useState<string | null>(null)
  const [loadingMessages, setLoadingMessages] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [deletingSession, setDeletingSession] = useState(false)
  const [composerValue, setComposerValue] = useState('')
  const [deleteConfirmSessionId, setDeleteConfirmSessionId] = useState<string | null>(null)
  const [allowWebSearchDraft, setAllowWebSearchDraft] = useState(false)

  useEffect(() => {
    if (composerPrefill) {
      setComposerValue(composerPrefill)
      setComposerPrefill('')
    }
  }, [composerPrefill, setComposerPrefill])

  useEffect(() => {
    if (!pendingRunId) {
      setLinkedRunStatus(null)
      return
    }
    let cancelled = false
    void api.runs.get(pendingRunId)
      .then((run) => {
        if (!cancelled) setLinkedRunStatus(String((run as { status?: string }).status || ''))
      })
      .catch(() => {
        if (!cancelled) setLinkedRunStatus(null)
      })
    return () => { cancelled = true }
  }, [pendingRunId])

  const [searchResults, setSearchResults] = useState<typeof sessions | null>(null)
  const [stopping, setStopping] = useState(false)
  const previousSessionIdRef = useRef<string | null>(null)

  const agentWorking = useMemo(() => {
    if (submitting || streaming) return true
    if (assistantStatus) return true
    if (pendingToolCalls.some((tool) => tool.status === 'pending')) return true
    return messages.some((message) => message.role === 'assistant' && message.pending)
  }, [assistantStatus, messages, pendingToolCalls, streaming, submitting])

  const composerDisabled = agentWorking || loadingSessions

  const currentSession = useMemo(
    () => sessions.find((session) => session.id === currentSessionId) || null,
    [sessions, currentSessionId]
  )
  const effectiveAllowWebSearch = currentSession?.allow_web_search ?? allowWebSearchDraft
  const effectiveNothink = useMemo(
    () => resolveEffectiveNothink(currentSession?.nothink, appSettings.nothink_default),
    [appSettings.nothink_default, currentSession?.nothink],
  )
  const historySessions = useMemo(
    () => historySearchQuery.trim() ? (searchResults || sessions) : sessions,
    [historySearchQuery, searchResults, sessions]
  )

  useEffect(() => {
    setAllowWebSearchDraft(Boolean(currentSession?.allow_web_search))
  }, [currentSession?.allow_web_search, currentSessionId])

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

  const handleAllowWebSearchToggle = useCallback(async (enabled: boolean) => {
    setAllowWebSearchDraft(enabled)
    if (!currentSessionId || !currentSession) return
    upsertSession({ ...currentSession, allow_web_search: enabled })
    try {
      const updated = await api.chat.sessions.update(currentSessionId, { allow_web_search: enabled })
      upsertSession(toChatSession(updated))
    } catch (error) {
      upsertSession(currentSession)
      showError(error)
    }
  }, [currentSession, currentSessionId, upsertSession])

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
      allow_web_search: options?.allowWebSearch ?? allowWebSearchDraft,
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
    setAllowWebSearchDraft(Boolean(session.allow_web_search))
    return session
  }, [
    activeMode,
    allowWebSearchDraft,
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
        await createSession(activeMode, { allowWebSearch: effectiveAllowWebSearch })
        return
      }
      setSessions(nextSessions)
      const savedSessionId = useChatStore.getState().currentSessionId
      const selected = nextSessions.find((session) => session.id === savedSessionId) || nextSessions[0]
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
    effectiveAllowWebSearch,
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

  const loadMessages = useCallback(async (sessionId: string) => {
    setLoadingMessages(true)
    try {
      const raw = await api.chat.messages.list(sessionId)
      const items = Array.isArray(raw) ? raw : raw.items
      const parsed = items.map((message) => toChatMessage(message))
      setMessages(parsed)
      setSpawnedRunIds(extractRunIds(parsed))
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
    const prevId = previousSessionIdRef.current
    if (prevId && prevId !== currentSessionId) {
      const state = useChatStore.getState()
      if (state.streaming || submitting) {
        void api.chat.sessions.cancel(prevId).catch(() => {})
      }
    }
    previousSessionIdRef.current = currentSessionId
  }, [currentSessionId, submitting])

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
        allowWebSearch: effectiveAllowWebSearch,
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
    generationStoppedRef.current = false
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
        page_element: pageElementSelection
          ? elementContextPayload(pageElementSelection)
          : undefined,
      }

      setPageElementSelection(null)

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
    createSession,
    currentSessionId,
    modelSelectionMode,
    projectId,
    selectedModel,
    selection,
    pageElementSelection,
    setPageElementSelection,
    setPendingToolCalls,
    setStreaming,
    setAssistantStatus,
    setStreamingContent,
    tabs,
    upsertSession,
    updateMessage,
    effectiveAllowWebSearch,
  ])

  const handleStop = useCallback(async () => {
    if (!currentSessionId) return
    generationStoppedRef.current = true
    setStopping(true)
    try {
      const result = await api.chat.sessions.cancel(currentSessionId)
      if (!result.cancelled) {
        finalizeStreamingMessage()
        generationStoppedRef.current = false
      }
    } catch (error) {
      finalizeStreamingMessage()
      generationStoppedRef.current = false
      showError(error)
    } finally {
      setStopping(false)
    }
  }, [currentSessionId])

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
      await createSession(activeMode, { allowWebSearch: effectiveAllowWebSearch })
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
        const created = await createSession('agent', { allowWebSearch: effectiveAllowWebSearch })
        sessionId = created?.id || null
      }
      if (!sessionId || !projectId) return
      setComposerValue('')
      const taskDescription = pageElementSelection
        ? formatElementForAgentTask(pageElementSelection, command.description)
        : command.description
      const validationProfile = inferValidationProfile(treeItems.map((item) => item.path))
      setPageElementSelection(null)
      try {
        let runId = ''
        let taskId = ''
        let runDisplayName = ''
        try {
          const result = await api.chat.spawnTask(sessionId, {
            description: taskDescription,
            validation_profile: validationProfile,
            allow_web_search: effectiveAllowWebSearch,
          }) as Record<string, unknown>
          runId = String(result.run_id || (result.run as Record<string, unknown> | undefined)?.id || '')
          taskId = String(result.task_id || (result.task as Record<string, unknown> | undefined)?.id || '')
          runDisplayName = String(result.display_name || (result.run as Record<string, unknown> | undefined)?.display_name || '')
        } catch {
          const fallback = await api.tasks.create({
            project_id: projectId,
            description: taskDescription,
            validation_profile: validationProfile,
            allow_web_search: effectiveAllowWebSearch,
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
    effectiveAllowWebSearch,
    handleManualModelChange,
    persistModeChange,
    pageElementSelection,
    projectId,
    sendMessage,
    setPageElementSelection,
    treeItems,
  ])

  const handleSelectSession = useCallback((sessionId: string) => {
    setCurrentSessionId(sessionId)
  }, [setCurrentSessionId])

  const handleDeleteSession = useCallback((sessionId: string) => {
    setDeleteConfirmSessionId(sessionId)
  }, [])

  const confirmDeleteSession = useCallback(async () => {
    const sessionId = deleteConfirmSessionId
    if (!sessionId) return
    setDeleteConfirmSessionId(null)
    setDeletingSession(true)
    try {
      await api.chat.sessions.delete(sessionId)
      removeSession(sessionId)
      const nextSessions = useChatStore.getState().sessions.filter((session) => session.id !== sessionId)
      if (nextSessions.length > 0) {
        setCurrentSessionId(nextSessions[0].id)
      } else {
        await createSession(activeMode, { allowWebSearch: effectiveAllowWebSearch })
      }
    } catch (error) {
      showError(error)
    } finally {
      setDeletingSession(false)
    }
  }, [activeMode, createSession, deleteConfirmSessionId, effectiveAllowWebSearch, removeSession, setCurrentSessionId])

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
            disabled={composerDisabled}
            onSelectionModeChange={(mode) => void handleModelSelectionModeChange(mode)}
            onModelChange={(model) => void handleManualModelChange(model)}
          />
          {currentSessionId && (
            <button
              type="button"
              title={effectiveNothink ? 'Thinking: off (fast)' : 'Thinking: on'}
              aria-label={effectiveNothink ? 'Thinking off' : 'Thinking on'}
              aria-pressed={!effectiveNothink}
              disabled={composerDisabled}
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
              } • Thinking: ${effectiveNothink ? 'off' : 'on'} • Web: ${effectiveAllowWebSearch ? 'on' : 'off'}`}
            </span>
          </div>
        )}
      </div>

      <div className="relative flex min-h-0 flex-1 overflow-hidden">
        {historyOpen && (
          <>
            <button
              type="button"
              className="absolute inset-0 z-30 bg-black/50"
              aria-label="Close chat history"
              onClick={() => setHistoryOpen(false)}
            />
            <aside className="absolute left-0 top-0 bottom-0 z-40 flex w-72 max-w-[85%] min-h-0 flex-col border-r border-[var(--border)] bg-[var(--bg-secondary)] shadow-lg">
              <ChatHistory
                sessions={historySessions}
                currentSessionId={currentSessionId}
                loading={loadingSessions}
                deleting={deletingSession}
                searchQuery={historySearchQuery}
                onSearchChange={setHistorySearchQuery}
                onSelect={handleSelectSession}
                onNew={() => void createSession(activeMode, { allowWebSearch: effectiveAllowWebSearch })}
                onDelete={handleDeleteSession}
              />
            </aside>
          </>
        )}

        <div className="min-w-0 flex-1 flex flex-col overflow-hidden">
          <MessageList
            messages={messages}
            loading={loadingMessages}
            streaming={streaming}
            thinkingLabel={assistantStatus || (streaming ? 'Thinking…' : null)}
            pendingToolCalls={pendingToolCalls}
            runEventsById={runEventsById}
            onOpenRunInAgents={(runId) => {
              setRightPanelTab('agents')
              requestOpenRunDrawer(runId, 'conversation')
            }}
          />

          <ChatComposer
            value={composerValue}
            mode={activeMode}
            allowWebSearch={effectiveAllowWebSearch}
            treeItems={treeItems}
            disabled={composerDisabled}
            submitting={submitting}
            busy={agentWorking}
            stopping={stopping}
            onStop={() => void handleStop()}
            pendingRunId={pendingRunId}
            linkedRunStatus={linkedRunStatus}
            pageElement={pageElementSelection}
            onClearPageElement={() => setPageElementSelection(null)}
            onChange={setComposerValue}
            onModeChange={(mode) => void persistModeChange(mode)}
            onAllowWebSearchChange={(enabled) => void handleAllowWebSearchToggle(enabled)}
            onCommand={handleCommand}
          />
        </div>
      </div>

      <ConfirmModal
        open={deleteConfirmSessionId != null}
        title="Delete chat session?"
        description="This permanently removes the conversation history for this session."
        confirmLabel="Delete"
        variant="destructive"
        onConfirm={() => void confirmDeleteSession()}
        onCancel={() => setDeleteConfirmSessionId(null)}
      />
    </div>
  )
}
