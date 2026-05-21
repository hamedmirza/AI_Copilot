import { create } from 'zustand'
import { persist } from 'zustand/middleware'

export type Panel = 'explorer' | 'search' | 'git' | 'agents' | 'settings'

export interface EditorTab {
  path: string
  content: string
  dirty: boolean
  language: string
}

interface UIState {
  activePanel: Panel
  sidebarWidth: number
  rightPanelWidth: number
  bottomPanelHeight: number
  rightPanelCollapsed: boolean
  bottomPanelCollapsed: boolean
  bottomTab: 'terminal' | 'git' | 'problems'
  setActivePanel: (p: Panel) => void
  setSidebarWidth: (w: number) => void
  setRightPanelWidth: (w: number) => void
  setBottomPanelHeight: (h: number) => void
  toggleRightPanel: () => void
  toggleBottomPanel: () => void
  setBottomTab: (t: 'terminal' | 'git' | 'problems') => void
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
  treeItems: Array<{ path: string; type: string; size: number }>
  treeRefreshTick: number
  openTab: (tab: EditorTab) => void
  closeTab: (path: string) => void
  setActiveTab: (path: string) => void
  updateTabContent: (path: string, content: string, dirty?: boolean) => void
  markClean: (path: string) => void
  renameTabPath: (oldPath: string, newPath: string) => void
  setTreeItems: (items: Array<{ path: string; type: string; size: number }>) => void
  toggleFolder: (path: string) => void
  bumpTreeRefresh: () => void
  clearWorkspace: () => void
}

interface RunState {
  currentRunId: string | null
  runStatus: string
  currentStage: string | null
  events: Array<Record<string, unknown>>
  runs: Array<Record<string, unknown>>
  setCurrentRun: (id: string | null) => void
  setRunStatus: (status: string, stage?: string | null) => void
  addEvent: (e: Record<string, unknown>) => void
  setEvents: (e: Array<Record<string, unknown>>) => void
  setRuns: (r: Array<Record<string, unknown>>) => void
  resetRunPanel: () => void
}

interface SettingsState {
  settings: Record<string, unknown>
  models: string[]
  setSettings: (s: Record<string, unknown>) => void
  setModels: (m: string[]) => void
}

interface AppState {
  backendOnline: boolean
  wsReconnecting: boolean
  showOnboarding: boolean
  showSettings: boolean
  setBackendOnline: (v: boolean) => void
  setWsReconnecting: (v: boolean) => void
  setShowOnboarding: (v: boolean) => void
  setShowSettings: (v: boolean) => void
}

export const useUIStore = create<UIState>()(
  persist(
    (set) => ({
      activePanel: 'explorer',
      sidebarWidth: 280,
      rightPanelWidth: 360,
      bottomPanelHeight: 240,
      rightPanelCollapsed: false,
      bottomPanelCollapsed: false,
      bottomTab: 'terminal',
      setActivePanel: (p) => set({ activePanel: p }),
      setSidebarWidth: (w) => set({ sidebarWidth: w }),
      setRightPanelWidth: (w) => set({ rightPanelWidth: w }),
      setBottomPanelHeight: (h) => set({ bottomPanelHeight: h }),
      toggleRightPanel: () => set((s) => ({ rightPanelCollapsed: !s.rightPanelCollapsed })),
      toggleBottomPanel: () => set((s) => ({ bottomPanelCollapsed: !s.bottomPanelCollapsed })),
      setBottomTab: (t) => set({ bottomTab: t }),
    }),
    { name: 'ai-copilot-ui' }
  )
)

export const useProjectStore = create<ProjectState>((set) => ({
  projects: [],
  currentProjectId: null,
  setProjects: (projects) => set({ projects }),
  setCurrentProject: (id) => set({ currentProjectId: id }),
}))

export const useEditorStore = create<EditorState>((set) => ({
  tabs: [],
  activeTab: null,
  expandedFolders: {},
  treeItems: [],
  treeRefreshTick: 0,
  openTab: (tab) =>
    set((s) => {
      const exists = s.tabs.find((t) => t.path === tab.path)
      if (exists) return { activeTab: tab.path }
      return { tabs: [...s.tabs, tab], activeTab: tab.path }
    }),
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
  toggleFolder: (path) =>
    set((s) => ({
      expandedFolders: { ...s.expandedFolders, [path]: !s.expandedFolders[path] },
    })),
  bumpTreeRefresh: () => set((s) => ({ treeRefreshTick: s.treeRefreshTick + 1 })),
  clearWorkspace: () => set({ tabs: [], activeTab: null, treeItems: [] }),
}))

export const useRunStore = create<RunState>((set) => ({
  currentRunId: null,
  runStatus: 'idle',
  currentStage: null,
  events: [],
  runs: [],
  setCurrentRun: (id) => set({ currentRunId: id }),
  setRunStatus: (status, stage = null) => set({ runStatus: status, currentStage: stage }),
  addEvent: (e) => set((s) => ({ events: [...s.events, e] })),
  setEvents: (events) => set({ events }),
  setRuns: (runs) => set({ runs }),
  resetRunPanel: () => set({ currentRunId: null, runStatus: 'idle', currentStage: null, events: [], runs: [] }),
}))

export const useSettingsStore = create<SettingsState>((set) => ({
  settings: {},
  models: [],
  setSettings: (settings) => set({ settings }),
  setModels: (models) => set({ models }),
}))

export const useAppStore = create<AppState>((set) => ({
  backendOnline: false,
  wsReconnecting: false,
  showOnboarding: false,
  showSettings: false,
  setBackendOnline: (v) => set({ backendOnline: v }),
  setWsReconnecting: (v) => set({ wsReconnecting: v }),
  setShowOnboarding: (v) => set({ showOnboarding: v }),
  setShowSettings: (v) => set({ showSettings: v }),
}))
