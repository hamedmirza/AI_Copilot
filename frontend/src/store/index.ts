import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { ModelsApiResponse } from '@/lib/lmstudioModels'
import type { ModelsCacheEntry, ProviderKind } from '@/lib/providerModels'
import { appendRunEventDeduped, dedupeRunEvents, normalizeRunEvent, trimRunEvents } from '@/lib/runEvents'
import type { RunEvent } from '@/types/runs'

export type { RunEvent }

export type Panel = 'explorer' | 'search' | 'git' | 'agents' | 'settings'
export type SidebarPanel = Exclude<Panel, 'settings'>
export type CenterView = 'editor' | 'browser' | 'kanban'
export type AgentPanelPlacement = 'sidebar' | 'right'
export type RightPanelTab = 'chat' | 'runs' | 'agents'
export type RunDrawerTab = 'conversation' | 'pipeline'
export type ChatMode = 'general' | 'agent' | 'planner' | 'debugger' | 'architect'
export type ChatModelSelectionMode = 'auto' | 'manual'

export interface EditorTab {
  path: string
  content: string
  dirty: boolean
  language: string
  preview?: boolean
}

export interface TreeItem {
  path: string
  type: string
  size: number
}

export interface EditorSelection {
  path: string
  text: string
  startLineNumber: number
  endLineNumber: number
}

export interface ChatSession {
  id: string
  project_id: string
  title: string
  mode: ChatMode | string
  model_override?: string | null
  nothink?: boolean | null
  allow_web_search?: boolean
  message_count?: number
  last_message_preview?: string | null
  last_message_at?: string | null
  created_at?: string
  updated_at?: string
}

export interface ChatToolCall {
  id: string
  name: string
  args: unknown
  result?: unknown
  status: 'pending' | 'completed' | 'error'
  startedAt?: string
  completedAt?: string
  error?: string
}

export interface ChatMessage {
  id: string
  session_id?: string
  role: 'user' | 'assistant' | 'tool' | 'system'
  content: string
  tool_call_id?: string
  created_at?: string
  metadata?: Record<string, unknown>
  tool_calls?: ChatToolCall[]
  pending?: boolean
  error?: string
}

export interface PageElementSelection {
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

interface UIState {
  activePanel: Panel
  sidebarCollapsed: boolean
  sidebarWidth: number
  rightPanelWidth: number
  bottomPanelHeight: number
  rightPanelCollapsed: boolean
  bottomPanelCollapsed: boolean
  activeCenterView: CenterView
  browserUrlByProject: Record<string, string>
  pickerBridgeInstalledByProject: Record<string, boolean>
  browserPickerActive: boolean
  pageElementSelection: PageElementSelection | null
  browserBridgeReady: boolean
  browserAgentMode: boolean
  browserAgentRunId: string | null
  bottomTab: 'terminal' | 'git' | 'problems'
  agentPanelPlacement: AgentPanelPlacement
  rightPanelTab: RightPanelTab
  runDrawerRequest: { runId: string; tab: RunDrawerTab; seq: number } | null
  setActivePanel: (p: Panel) => void
  toggleSidebar: () => void
  openSidebarPanel: (p: SidebarPanel) => void
  setSidebarWidth: (w: number) => void
  setRightPanelWidth: (w: number) => void
  setBottomPanelHeight: (h: number) => void
  toggleRightPanel: () => void
  toggleBottomPanel: () => void
  setActiveCenterView: (view: CenterView) => void
  toggleCenterView: (view: CenterView) => void
  setBrowserUrlForProject: (projectId: string, url: string) => void
  setBrowserPickerActive: (active: boolean) => void
  setPageElementSelection: (sel: PageElementSelection | null) => void
  setBrowserBridgeReady: (ready: boolean) => void
  setBrowserAgentMode: (active: boolean, runId?: string | null) => void
  setPickerBridgeInstalled: (projectId: string, installed: boolean) => void
  resetBrowserPickerForProjectSwitch: () => void
  setBottomTab: (t: 'terminal' | 'git' | 'problems') => void
  setAgentPanelPlacement: (placement: AgentPanelPlacement) => void
  openAgentsPanel: () => void
  setRightPanelTab: (t: RightPanelTab) => void
  requestOpenRunDrawer: (runId: string, tab?: RunDrawerTab) => void
  clearRunDrawerRequest: () => void
}

interface ProjectState {
  projects: Array<Record<string, unknown>>
  currentProjectId: string | null
  setProjects: (p: Array<Record<string, unknown>>) => void
  setCurrentProject: (id: string | null) => void
}

interface EditorState {
  tabs: EditorTab[]
  activeTab: string | null
  expandedFolders: Record<string, boolean>
  treeItems: TreeItem[]
  treeRefreshTick: number
  selection: EditorSelection | null
  openTab: (tab: EditorTab) => void
  openPreview: (tab: EditorTab) => void
  promoteTab: (path: string) => void
  closeTab: (path: string) => void
  setActiveTab: (path: string) => void
  updateTabContent: (path: string, content: string, dirty?: boolean) => void
  markClean: (path: string) => void
  renameTabPath: (oldPath: string, newPath: string) => void
  setTreeItems: (items: TreeItem[]) => void
  setSelection: (selection: EditorSelection | null) => void
  toggleFolder: (path: string) => void
  bumpTreeRefresh: () => void
  clearWorkspace: () => void
}

interface RunState {
  currentRunId: string | null
  runStatus: string
  currentStage: string | null
  events: Array<Record<string, unknown>>
  runEventsByRunId: Record<string, RunEvent[]>
  runs: Array<Record<string, unknown>>
  setCurrentRun: (id: string | null) => void
  setRunStatus: (status: string, stage?: string | null) => void
  addEvent: (e: Record<string, unknown>) => void
  setEvents: (e: Array<Record<string, unknown>>) => void
  setRunEvents: (runId: string, events: RunEvent[]) => void
  appendRunEvent: (runId: string, raw: Record<string, unknown>) => void
  clearRunEvents: (runId?: string) => void
  setRuns: (r: Array<Record<string, unknown>>) => void
  resetRunPanel: () => void
  resetRunForProjectSwitch: () => void
}

export interface LMStudioModelCatalogEntry {
  id: string
  state: string
  loaded: boolean
  size_gb: number
  tool_use: boolean
  params: string
  quantization: string
}

export interface LMStudioResources {
  pressure: 'ok' | 'elevated' | 'high'
  loaded_count: number
  loaded_size_gb: number
}

interface SettingsState {
  settings: Record<string, unknown>
  models: string[]
  modelCatalog: LMStudioModelCatalogEntry[]
  modelRecommendations: Record<string, string>
  lmstudioResources: LMStudioResources | null
  modelsCacheByProvider: Partial<Record<ProviderKind, ModelsCacheEntry>>
  setSettings: (s: Record<string, unknown>) => void
  setModels: (m: string[]) => void
  setModelCatalog: (catalog: LMStudioModelCatalogEntry[]) => void
  setModelRecommendations: (recommendations: Record<string, string>) => void
  setLmstudioResources: (resources: LMStudioResources | null) => void
  setModelsCache: (provider: ProviderKind, response: ModelsApiResponse) => void
  clearModelsCache: () => void
}

interface AppState {
  backendOnline: boolean
  wsReconnecting: boolean
  wsConnections: number
  onboardingReady: boolean
  showOnboarding: boolean
  showSettings: boolean
  setBackendOnline: (v: boolean) => void
  setWsReconnecting: (v: boolean) => void
  setWsConnections: (v: number) => void
  setOnboardingReady: (v: boolean) => void
  setShowOnboarding: (v: boolean) => void
  setShowSettings: (v: boolean) => void
}

interface ChatState {
  sessions: ChatSession[]
  currentSessionId: string | null
  historyOpen: boolean
  historySearchQuery: string
  messages: ChatMessage[]
  streaming: boolean
  activeMode: ChatMode
  modelSelectionMode: ChatModelSelectionMode
  selectedModel: string
  pendingToolCalls: ChatToolCall[]
  spawnedRunIds: string[]
  streamingContent: string
  assistantStatus: string | null
  runEventsById: Record<string, RunEvent[]>
  pendingRunId: string | null
  composerPrefill: string
  setSessions: (sessions: ChatSession[]) => void
  upsertSession: (session: ChatSession) => void
  removeSession: (sessionId: string) => void
  setCurrentSessionId: (sessionId: string | null) => void
  setHistoryOpen: (open: boolean) => void
  setHistorySearchQuery: (query: string) => void
  setMessages: (messages: ChatMessage[]) => void
  appendMessage: (message: ChatMessage) => void
  updateMessage: (messageId: string, updater: (message: ChatMessage) => ChatMessage) => void
  setStreaming: (streaming: boolean) => void
  setActiveMode: (mode: ChatMode) => void
  setModelSelectionMode: (mode: ChatModelSelectionMode) => void
  setSelectedModel: (model: string) => void
  setPendingToolCalls: (toolCalls: ChatToolCall[]) => void
  upsertPendingToolCall: (toolCall: ChatToolCall) => void
  finishPendingToolCall: (toolCallId: string, patch: Partial<ChatToolCall>) => void
  setSpawnedRunIds: (runIds: string[]) => void
  addSpawnedRunId: (runId: string) => void
  setStreamingContent: (content: string) => void
  appendStreamingContent: (chunk: string) => void
  clearStreamingContent: () => void
  setAssistantStatus: (status: string | null) => void
  addRunEvent: (runId: string, event: RunEvent) => void
  clearRunEvents: (runId?: string) => void
  setPendingRunId: (runId: string | null) => void
  setComposerPrefill: (text: string) => void
  resetChatState: () => void
  resetChatForProjectSwitch: () => void
}

export const useUIStore = create<UIState>()(
  persist(
    (set) => ({
      activePanel: 'explorer',
      sidebarCollapsed: false,
      sidebarWidth: 280,
      rightPanelWidth: 360,
      bottomPanelHeight: 240,
      rightPanelCollapsed: false,
      bottomPanelCollapsed: false,
      activeCenterView: 'editor',
      browserUrlByProject: {},
      pickerBridgeInstalledByProject: {},
      browserPickerActive: false,
      pageElementSelection: null,
      browserBridgeReady: false,
      browserAgentMode: false,
      browserAgentRunId: null,
      bottomTab: 'terminal',
      agentPanelPlacement: 'right',
      rightPanelTab: 'chat',
      setActivePanel: (p) => set({ activePanel: p }),
      toggleSidebar: () => set((s) => ({ sidebarCollapsed: !s.sidebarCollapsed })),
      openSidebarPanel: (p) => set({ activePanel: p, sidebarCollapsed: false }),
      setSidebarWidth: (w) => set({ sidebarWidth: w }),
      setRightPanelWidth: (w) => set({ rightPanelWidth: w }),
      setBottomPanelHeight: (h) => set({ bottomPanelHeight: h }),
      toggleRightPanel: () => set((s) => ({ rightPanelCollapsed: !s.rightPanelCollapsed })),
      toggleBottomPanel: () => set((s) => ({ bottomPanelCollapsed: !s.bottomPanelCollapsed })),
      setActiveCenterView: (view) => set({ activeCenterView: view }),
      toggleCenterView: (view) =>
        set((s) => ({
          activeCenterView: s.activeCenterView === view ? 'editor' : view,
        })),
      setBrowserUrlForProject: (projectId, url) =>
        set((s) => ({
          browserUrlByProject: { ...s.browserUrlByProject, [projectId]: url },
        })),
      setBrowserPickerActive: (browserPickerActive) => set({ browserPickerActive }),
      setPageElementSelection: (pageElementSelection) => set({ pageElementSelection }),
      setBrowserBridgeReady: (browserBridgeReady) => set({ browserBridgeReady }),
      setBrowserAgentMode: (browserAgentMode, runId = null) =>
        set({ browserAgentMode, browserAgentRunId: runId ?? null }),
      setPickerBridgeInstalled: (projectId, installed) =>
        set((s) => ({
          pickerBridgeInstalledByProject: {
            ...s.pickerBridgeInstalledByProject,
            [projectId]: installed,
          },
        })),
      resetBrowserPickerForProjectSwitch: () =>
        set({
          browserPickerActive: false,
          pageElementSelection: null,
          browserBridgeReady: false,
          browserAgentMode: false,
          browserAgentRunId: null,
        }),
      setBottomTab: (t) => set({ bottomTab: t }),
      setAgentPanelPlacement: (placement) =>
        set((s) => {
          if (placement === 'right') {
            if (s.activePanel === 'agents') {
              return {
                agentPanelPlacement: 'right',
                activePanel: 'explorer',
                rightPanelTab: 'agents',
                rightPanelCollapsed: false,
              }
            }
            return { agentPanelPlacement: 'right' }
          }
          if (s.rightPanelTab === 'agents') {
            return {
              agentPanelPlacement: 'sidebar',
              rightPanelTab: 'runs',
              activePanel: 'agents',
              sidebarCollapsed: false,
            }
          }
          return { agentPanelPlacement: 'sidebar' }
        }),
      openAgentsPanel: () =>
        set((s) => {
          if (s.agentPanelPlacement === 'right') {
            return { rightPanelCollapsed: false, rightPanelTab: 'agents' }
          }
          return { activePanel: 'agents', sidebarCollapsed: false }
        }),
      setRightPanelTab: (t) =>
        set((s) => {
          if (t === 'agents' && s.agentPanelPlacement !== 'right') {
            return { rightPanelTab: t, agentPanelPlacement: 'right', rightPanelCollapsed: false }
          }
          return { rightPanelTab: t }
        }),
      runDrawerRequest: null as UIState['runDrawerRequest'],
      requestOpenRunDrawer: (runId, tab = 'conversation') =>
        set((s) => ({
          runDrawerRequest: {
            runId,
            tab,
            seq: (s.runDrawerRequest?.seq ?? 0) + 1,
          },
          rightPanelCollapsed: false,
          rightPanelTab: s.agentPanelPlacement === 'right' ? 'agents' : 'runs',
        })),
      clearRunDrawerRequest: () => set({ runDrawerRequest: null }),
    }),
    {
      name: 'ai-copilot-ui',
      version: 3,
      migrate: (persisted, version) => {
        const state = (persisted ?? {}) as Record<string, unknown>
        if (version < 1) {
          return { ...state, agentPanelPlacement: 'right' }
        }
        if (version < 3) {
          if (state.activeCenterView === 'reporting' || state.activeCenterView === 'kanban') {
            return { ...state, activeCenterView: 'kanban' }
          }
          if (state.activeCenterView !== 'editor' && state.activeCenterView !== 'browser') {
            return { ...state, activeCenterView: 'editor' }
          }
        }
        return persisted
      },
      partialize: (state) => ({
        activePanel: state.activePanel,
        sidebarCollapsed: state.sidebarCollapsed,
        sidebarWidth: state.sidebarWidth,
        rightPanelWidth: state.rightPanelWidth,
        bottomPanelHeight: state.bottomPanelHeight,
        rightPanelCollapsed: state.rightPanelCollapsed,
        bottomPanelCollapsed: state.bottomPanelCollapsed,
        activeCenterView: state.activeCenterView,
        browserUrlByProject: state.browserUrlByProject,
        pickerBridgeInstalledByProject: state.pickerBridgeInstalledByProject,
        bottomTab: state.bottomTab,
        agentPanelPlacement: state.agentPanelPlacement,
        rightPanelTab: state.rightPanelTab,
      }),
    },
  )
)

export const useProjectStore = create<ProjectState>()(
  persist(
    (set) => ({
      projects: [],
      currentProjectId: null,
      setProjects: (projects) => set({ projects }),
      setCurrentProject: (id) => set({ currentProjectId: id }),
    }),
    {
      name: 'ai-copilot-project',
      partialize: (state) => ({ currentProjectId: state.currentProjectId }),
    },
  ),
)

export const useEditorStore = create<EditorState>((set) => ({
  tabs: [],
  activeTab: null,
  expandedFolders: {},
  treeItems: [],
  treeRefreshTick: 0,
  selection: null,
  openTab: (tab) =>
    set((s) => {
      const exists = s.tabs.find((t) => t.path === tab.path)
      if (exists) {
        // promote to permanent if it was a preview
        return {
          tabs: s.tabs.map((t) => t.path === tab.path ? { ...t, preview: false } : t),
          activeTab: tab.path,
        }
      }
      // replace existing preview tab in-place, or append
      const previewIdx = s.tabs.findIndex((t) => t.preview)
      if (previewIdx !== -1) {
        const tabs = [...s.tabs]
        tabs[previewIdx] = { ...tab, preview: false }
        return { tabs, activeTab: tab.path }
      }
      return { tabs: [...s.tabs, { ...tab, preview: false }], activeTab: tab.path }
    }),
  openPreview: (tab) =>
    set((s) => {
      const exists = s.tabs.find((t) => t.path === tab.path)
      if (exists) return { activeTab: tab.path }
      const previewIdx = s.tabs.findIndex((t) => t.preview)
      if (previewIdx !== -1) {
        const tabs = [...s.tabs]
        tabs[previewIdx] = { ...tab, preview: true }
        return { tabs, activeTab: tab.path }
      }
      return { tabs: [...s.tabs, { ...tab, preview: true }], activeTab: tab.path }
    }),
  promoteTab: (path) =>
    set((s) => ({
      tabs: s.tabs.map((t) => t.path === path ? { ...t, preview: false } : t),
    })),
  closeTab: (path) =>
    set((s) => {
      const tabs = s.tabs.filter((t) => t.path !== path)
      const activeTab = s.activeTab === path ? tabs[tabs.length - 1]?.path ?? null : s.activeTab
      return { tabs, activeTab }
    }),
  setActiveTab: (path) => set({ activeTab: path }),
  updateTabContent: (path, content, dirty = true) =>
    set((s) => ({
      tabs: s.tabs.map((t) => (t.path === path ? { ...t, content, dirty } : t)),
    })),
  markClean: (path) =>
    set((s) => ({
      tabs: s.tabs.map((t) => (t.path === path ? { ...t, dirty: false } : t)),
    })),
  renameTabPath: (oldPath, newPath) =>
    set((s) => ({
      tabs: s.tabs.map((t) => (t.path === oldPath ? { ...t, path: newPath } : t)),
      activeTab: s.activeTab === oldPath ? newPath : s.activeTab,
    })),
  setTreeItems: (items) => set({ treeItems: items }),
  setSelection: (selection) => set({ selection }),
  toggleFolder: (path) =>
    set((s) => ({
      expandedFolders: {
        ...s.expandedFolders,
        [path]: !s.expandedFolders[path],
      },
    })),
  bumpTreeRefresh: () => set((s) => ({ treeRefreshTick: s.treeRefreshTick + 1 })),
  clearWorkspace: () => set({ tabs: [], activeTab: null, treeItems: [], selection: null }),
}))

export const useRunStore = create<RunState>((set, get) => ({
  currentRunId: null,
  runStatus: 'idle',
  currentStage: null,
  events: [],
  runEventsByRunId: {},
  runs: [],
  setCurrentRun: (id) => set({ currentRunId: id }),
  setRunStatus: (status, stage = null) => set({ runStatus: status, currentStage: stage }),
  addEvent: (e) => {
    const runId = get().currentRunId
    if (runId) {
      get().appendRunEvent(runId, e)
      return
    }
    set((s) => ({ events: [...s.events, e] }))
  },
  setEvents: (events) => {
    const runId = get().currentRunId
    const normalized = events.map((row) => normalizeRunEvent(row) as RunEvent)
    if (runId) {
      get().setRunEvents(runId, normalized)
      return
    }
    set({ events })
  },
  setRunEvents: (runId, events) =>
    set((s) => {
      const deduped = trimRunEvents(dedupeRunEvents(events))
      const patch: Partial<RunState> = {
        runEventsByRunId: { ...s.runEventsByRunId, [runId]: deduped },
      }
      if (s.currentRunId === runId) {
        patch.events = deduped as unknown as Array<Record<string, unknown>>
      }
      return patch
    }),
  appendRunEvent: (runId, raw) =>
    set((s) => {
      const existing = s.runEventsByRunId[runId] || []
      const next = appendRunEventDeduped(existing, raw)
      const patch: Partial<RunState> = {
        runEventsByRunId: { ...s.runEventsByRunId, [runId]: next },
      }
      if (s.currentRunId === runId) {
        patch.events = next as unknown as Array<Record<string, unknown>>
      }
      return patch
    }),
  clearRunEvents: (runId) =>
    set((s) => {
      if (!runId) {
        return {
          runEventsByRunId: {},
          events: s.currentRunId ? [] : s.events,
        }
      }
      const nextMap = { ...s.runEventsByRunId }
      delete nextMap[runId]
      const patch: Partial<RunState> = { runEventsByRunId: nextMap }
      if (s.currentRunId === runId) patch.events = []
      return patch
    }),
  setRuns: (runs) => set({ runs }),
  resetRunPanel: () =>
    set({
      currentRunId: null,
      runStatus: 'idle',
      currentStage: null,
      events: [],
      runEventsByRunId: {},
      runs: [],
    }),
  resetRunForProjectSwitch: () =>
    set({
      currentRunId: null,
      runStatus: 'idle',
      currentStage: null,
      events: [],
      runEventsByRunId: {},
      runs: [],
    }),
}))

export const useSettingsStore = create<SettingsState>((set) => ({
  settings: {},
  models: [],
  modelCatalog: [],
  modelRecommendations: {},
  lmstudioResources: null,
  modelsCacheByProvider: {},
  setSettings: (settings) => set({ settings }),
  setModels: (models) => set({ models }),
  setModelCatalog: (modelCatalog) => set({ modelCatalog }),
  setModelRecommendations: (modelRecommendations) => set({ modelRecommendations }),
  setLmstudioResources: (lmstudioResources) => set({ lmstudioResources }),
  setModelsCache: (provider, response) =>
    set((state) => ({
      modelsCacheByProvider: {
        ...state.modelsCacheByProvider,
        [provider]: { response, fetchedAt: Date.now() },
      },
    })),
  clearModelsCache: () => set({ modelsCacheByProvider: {} }),
}))

export const useAppStore = create<AppState>((set) => ({
  backendOnline: false,
  wsReconnecting: false,
  wsConnections: 0,
  onboardingReady: false,
  showOnboarding: false,
  showSettings: false,
  setBackendOnline: (v) => set({ backendOnline: v }),
  setWsReconnecting: (v) => set({ wsReconnecting: v }),
  setWsConnections: (v) => set({ wsConnections: v }),
  setOnboardingReady: (v) => set({ onboardingReady: v }),
  setShowOnboarding: (v) => set({ showOnboarding: v }),
  setShowSettings: (v) => set({ showSettings: v }),
}))

export const useChatStore = create<ChatState>((set) => ({
  sessions: [],
  currentSessionId: null,
  historyOpen: false,
  historySearchQuery: '',
  messages: [],
  streaming: false,
  activeMode: 'general',
  modelSelectionMode: 'auto',
  selectedModel: '',
  pendingToolCalls: [],
  spawnedRunIds: [],
  streamingContent: '',
  assistantStatus: null,
  runEventsById: {},
  pendingRunId: null,
  composerPrefill: '',
  setSessions: (sessions) => set({ sessions }),
  upsertSession: (session) =>
    set((state) => {
      const index = state.sessions.findIndex((item) => item.id === session.id)
      if (index === -1) return { sessions: [session, ...state.sessions] }
      const sessions = [...state.sessions]
      sessions[index] = { ...sessions[index], ...session }
      return { sessions }
    }),
  removeSession: (sessionId) =>
    set((state) => ({
      sessions: state.sessions.filter((session) => session.id !== sessionId),
      currentSessionId: state.currentSessionId === sessionId ? null : state.currentSessionId,
    })),
  setCurrentSessionId: (sessionId) => set({ currentSessionId: sessionId }),
  setHistoryOpen: (historyOpen) => set({ historyOpen }),
  setHistorySearchQuery: (historySearchQuery) => set({ historySearchQuery }),
  setMessages: (messages) => set({ messages }),
  appendMessage: (message) => set((state) => ({ messages: [...state.messages, message] })),
  updateMessage: (messageId, updater) =>
    set((state) => ({
      messages: state.messages.map((message) => (
        message.id === messageId ? updater(message) : message
      )),
    })),
  setStreaming: (streaming) => set({ streaming }),
  setActiveMode: (mode) => set({ activeMode: mode }),
  setModelSelectionMode: (modelSelectionMode) => set({ modelSelectionMode }),
  setSelectedModel: (selectedModel) => set({ selectedModel }),
  setPendingToolCalls: (pendingToolCalls) => set({ pendingToolCalls }),
  upsertPendingToolCall: (toolCall) =>
    set((state) => {
      const existing = state.pendingToolCalls.find((item) => item.id === toolCall.id)
      if (!existing) return { pendingToolCalls: [...state.pendingToolCalls, toolCall] }
      return {
        pendingToolCalls: state.pendingToolCalls.map((item) => (
          item.id === toolCall.id ? { ...item, ...toolCall } : item
        )),
      }
    }),
  finishPendingToolCall: (toolCallId, patch) =>
    set((state) => ({
      pendingToolCalls: state.pendingToolCalls.map((toolCall) => (
        toolCall.id === toolCallId ? { ...toolCall, ...patch } : toolCall
      )),
    })),
  setSpawnedRunIds: (spawnedRunIds) => set({ spawnedRunIds }),
  addSpawnedRunId: (runId) =>
    set((state) => ({
      spawnedRunIds: state.spawnedRunIds.includes(runId)
        ? state.spawnedRunIds
        : [...state.spawnedRunIds, runId],
    })),
  setStreamingContent: (streamingContent) => set({ streamingContent }),
  appendStreamingContent: (chunk) =>
    set((state) => ({ streamingContent: `${state.streamingContent}${chunk}` })),
  clearStreamingContent: () => set({ streamingContent: '' }),
  setAssistantStatus: (assistantStatus) => set({ assistantStatus }),
  addRunEvent: (runId, event) => {
    useRunStore.getState().appendRunEvent(runId, event as unknown as Record<string, unknown>)
    set((state) => ({
      runEventsById: {
        ...state.runEventsById,
        [runId]: useRunStore.getState().runEventsByRunId[runId] || [],
      },
    }))
  },
  clearRunEvents: (runId) => {
    useRunStore.getState().clearRunEvents(runId)
    set((state) => {
      if (!runId) return { runEventsById: {} }
      const next = { ...state.runEventsById }
      delete next[runId]
      return { runEventsById: next }
    })
  },
  setPendingRunId: (pendingRunId) => set({ pendingRunId }),
  setComposerPrefill: (composerPrefill) => set({ composerPrefill }),
  resetChatState: () => set({
    sessions: [],
    currentSessionId: null,
    historyOpen: false,
    historySearchQuery: '',
    messages: [],
    streaming: false,
    activeMode: 'general',
    modelSelectionMode: 'auto',
    selectedModel: '',
    pendingToolCalls: [],
    spawnedRunIds: [],
    streamingContent: '',
    assistantStatus: null,
    runEventsById: {},
    pendingRunId: null,
    composerPrefill: '',
  }),
  resetChatForProjectSwitch: () => set((state) => ({
    sessions: [],
    currentSessionId: null,
    historySearchQuery: '',
    messages: [],
    streaming: false,
    pendingToolCalls: [],
    spawnedRunIds: [],
    streamingContent: '',
    assistantStatus: null,
    runEventsById: {},
    pendingRunId: null,
    composerPrefill: '',
    activeMode: state.activeMode,
    modelSelectionMode: state.modelSelectionMode,
    selectedModel: state.selectedModel,
    historyOpen: state.historyOpen,
  })),
}))
