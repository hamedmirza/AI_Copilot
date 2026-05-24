import { startTransition, useCallback, useEffect, useRef, useState } from 'react'
import { Toaster } from 'sonner'
import { api } from '@/api/client'
import { useWebSocket } from '@/hooks/useWebSocket'
import { ActivityBar } from '@/components/ActivityBar/ActivityBar'
import { EditorPanel } from '@/components/Editor/EditorPanel'
import { AgentPanel } from '@/components/AgentPanel/AgentPanel'
import { ChatPanel } from '@/components/Chat/ChatPanel'
import { GitPanel } from '@/components/GitPanel/GitPanel'
import { TerminalPanel } from '@/components/Terminal/TerminalPanel'
import { LogViewer } from '@/components/LogViewer/LogViewer'
import { SettingsPanel } from '@/components/Settings/SettingsPanel'
import { OnboardingWizard } from '@/components/Onboarding/OnboardingWizard'
import { ProjectManagerDialog } from '@/components/Project/ProjectManagerDialog'
import { StatusBar } from '@/components/StatusBar/StatusBar'
import { useAppStore, useChatStore, useEditorStore, useProjectStore, useRunStore, useSettingsStore, useUIStore } from '@/store'
import { Button, EmptyState } from '@/components/ui/primitives'
import { showError } from '@/lib/toast'
import { getContribution } from '@/workbench/registry'

function SidebarContent() {
  const panel = useUIStore((s) => s.activePanel)
  const contrib = getContribution('sidebar', panel)
  if (!contrib) return null
  const Component = contrib.Component
  return <Component />
}

function ResizeHandle({ onDrag }: { onDrag: (delta: number) => void }) {
  const startX = useRef(0)
  return (
    <div
      className="w-1 cursor-col-resize hover:bg-[var(--accent)] shrink-0"
      onMouseDown={(e) => {
        startX.current = e.clientX
        const move = (ev: MouseEvent) => onDrag(ev.clientX - startX.current)
        const up = () => {
          document.removeEventListener('mousemove', move)
          document.removeEventListener('mouseup', up)
        }
        document.addEventListener('mousemove', move)
        document.addEventListener('mouseup', up)
      }}
    />
  )
}

export default function App() {
  const {
    sidebarWidth, sidebarCollapsed, rightPanelWidth, bottomPanelHeight,
    rightPanelCollapsed, bottomPanelCollapsed, bottomTab,
    rightPanelTab, activeCenterView,
    setSidebarWidth, setRightPanelWidth, setBottomPanelHeight,
    activePanel,
  } = useUIStore()
  const { projects, currentProjectId, setProjects, setCurrentProject } = useProjectStore()
  const { setSettings } = useSettingsStore()
  const {
    onboardingReady,
    setBackendOnline,
    setOnboardingReady,
    setShowOnboarding,
    setShowSettings,
    setWsConnections,
  } = useAppStore()
  const [projectManagerOpen, setProjectManagerOpen] = useState(false)
  const [projectManagerMode, setProjectManagerMode] = useState<'list' | 'add'>('list')

  const currentProject = projects.find((p) => String(p.id) === currentProjectId)
  const sidebarContrib = getContribution('sidebar', activePanel)
  const panelTitle = sidebarContrib?.title ?? 'Explorer'
  const browserContrib = getContribution('center', 'browser')
  const BrowserComponent = browserContrib?.Component

  useEffect(() => {
    let cancelled = false

    const bootstrap = async () => {
      if (!useProjectStore.persist.hasHydrated()) {
        await new Promise<void>((resolve) => {
          const unsub = useProjectStore.persist.onFinishHydration(() => {
            unsub()
            resolve()
          })
        })
      }
      if (cancelled) return

      api.health()
        .then(() => setBackendOnline(true))
        .catch(() => setBackendOnline(false))
      api.settings.get().then(setSettings).catch(() => {})

      const [onboarding, p] = await Promise.all([
        api.onboarding.status().catch(() => ({ complete: false, project_count: 0 })),
        api.projects.list().catch(() => []),
      ])
      if (cancelled) return

      setProjects(p)
      if (!onboarding.complete) {
        setShowOnboarding(true)
      } else if (p.length === 0 && onboarding.project_count > 0) {
        showError('Projects exist but could not be loaded. Check the API and refresh the page.')
      }

      if (p.length === 0) {
        setCurrentProject(null)
        return
      }

      const savedId = useProjectStore.getState().currentProjectId
      const validSaved = savedId && p.some((proj) => String(proj.id) === String(savedId))
      if (!validSaved) {
        setCurrentProject(String(p[0].id))
      }
    }

    bootstrap()
      .catch(showError)
      .finally(() => {
        if (!cancelled) setOnboardingReady(true)
      })

    return () => { cancelled = true }
  }, [setBackendOnline, setCurrentProject, setOnboardingReady, setProjects, setSettings, setShowOnboarding])

  const bumpTreeRefresh = useEditorStore((s) => s.bumpTreeRefresh)
  const setRunStatus = useRunStore((s) => s.setRunStatus)
  const currentRunId = useRunStore((s) => s.currentRunId)
  const spawnedRunIds = useChatStore((s) => s.spawnedRunIds)
  const trackedRunEvents = useChatStore((s) => s.runEventsById)
  const addRunEvent = useChatStore((s) => s.addRunEvent)

  const gitPanelVisible =
    activePanel === 'git' || (bottomTab === 'git' && !bottomPanelCollapsed)

  useWebSocket('/api/ws/events', useCallback((data) => {
    const ev = data as Record<string, unknown>
    const type = String(ev.type || '')
    if (type === 'ping' && typeof ev.connections === 'number') {
      setWsConnections(ev.connections)
    }
    const runId = String(ev.run_id || '')
    if (type === 'awaiting_approval') setRunStatus('awaiting_approval', String(ev.stage || ''))
    else if (type === 'run_blocked') setRunStatus('blocked', String(ev.stage || ''))
    else if (type === 'run_failed') setRunStatus('failed', String(ev.stage || ''))
    else if (type === 'run_completed') setRunStatus('completed', String(ev.stage || ''))
    else if (type.endsWith('_started') && ev.run_id === currentRunId) {
      setRunStatus('running', type.replace('_started', ''))
    }
    const trackedRunIds = new Set([
      ...spawnedRunIds,
      ...Object.keys(trackedRunEvents),
      ...(currentRunId ? [currentRunId] : []),
    ])
    if (runId && trackedRunIds.has(runId)) {
      addRunEvent(runId, ev)
    }
    if (['run_completed', 'code_patch_applied', 'awaiting_approval'].includes(type)) {
      window.setTimeout(() => bumpTreeRefresh(), 3000)
    }
  }, [addRunEvent, bumpTreeRefresh, currentRunId, setRunStatus, setWsConnections, spawnedRunIds, trackedRunEvents]), true)

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === ',') {
        e.preventDefault()
        setShowSettings(true)
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [setShowSettings])

  const openProjectManager = (mode: 'list' | 'add' = 'list') => {
    setProjectManagerMode(mode)
    setProjectManagerOpen(true)
  }

  const switchProject = async (id: string) => {
    const proj = projects.find((p) => String(p.id) === id)
    if (!proj) return
    useEditorStore.getState().clearWorkspace()
    useRunStore.getState().resetRunForProjectSwitch()
    useChatStore.getState().resetChatForProjectSwitch()
    startTransition(() => {
      setCurrentProject(id)
      useUIStore.getState().openSidebarPanel('explorer')
      bumpTreeRefresh()
    })
  }

  return (
    <div className="h-full flex flex-col">
      <Toaster theme="dark" position="bottom-right" richColors />
      <OnboardingWizard />
      <SettingsPanel />
      <ProjectManagerDialog
        open={projectManagerOpen}
        onClose={() => setProjectManagerOpen(false)}
        initialMode={projectManagerMode}
        onProjectsChanged={() => bumpTreeRefresh()}
      />

      {/* Top bar */}
      <div className="h-9 flex items-center px-3 bg-[#323233] border-b border-[var(--border)] shrink-0">
        {projects.length > 0 ? (
          <select
            className="bg-transparent text-sm border-none outline-none"
            value={currentProjectId || ''}
            onChange={(e) => switchProject(e.target.value)}
          >
            {projects.map((p) => (
              <option key={String(p.id)} value={String(p.id)}>{String(p.name)}</option>
            ))}
          </select>
        ) : (
          <span className="text-sm text-[var(--text-secondary)]">No project selected</span>
        )}
        <button
          className="ml-2 text-xs text-[var(--accent)] hover:opacity-80"
          title="Add new project"
          onClick={() => openProjectManager('add')}
        >
          + Project
        </button>
        <button
          className="ml-2 text-xs text-[var(--text-secondary)] hover:text-white"
          title="Manage projects"
          onClick={() => openProjectManager('list')}
        >
          Manage
        </button>
        <span className="ml-auto text-xs text-[var(--text-secondary)]">AI Copilot IDE</span>
        <button
          className="ml-3 text-xs text-[var(--text-secondary)] hover:text-white"
          onClick={() => setShowOnboarding(true)}
        >
          Help
        </button>
      </div>

      {projects.length === 0 ? (
        <div className="flex-1 overflow-hidden">
          <EmptyState
            title="No projects yet"
            description="Create a project to connect a local folder or Git repository."
            action={
              <Button onClick={() => openProjectManager('add')}>Add Project</Button>
            }
          />
        </div>
      ) : (
      <div className="flex-1 flex overflow-hidden">
        <ActivityBar />

        {!sidebarCollapsed && (
          <>
            <div style={{ width: sidebarWidth }} className="shrink-0 border-r border-[var(--border)] overflow-hidden flex flex-col">
              <div className="px-3 py-1.5 text-xs uppercase text-[var(--text-secondary)] border-b border-[var(--border)]">
                {panelTitle}
              </div>
              <div className="flex-1 overflow-hidden">
                <SidebarContent />
              </div>
            </div>

            <ResizeHandle onDrag={(d) => setSidebarWidth(Math.max(180, sidebarWidth + d))} />
          </>
        )}

        <div className="flex-1 flex flex-col overflow-hidden">
          <div className="flex-1 overflow-hidden">
            {activeCenterView === 'browser' && BrowserComponent ? (
              <BrowserComponent />
            ) : (
              <EditorPanel />
            )}
          </div>

          {!bottomPanelCollapsed && (
            <>
              <div
                className="h-1 cursor-row-resize hover:bg-[var(--accent)] shrink-0"
                onMouseDown={(e) => {
                  const startY = e.clientY
                  const move = (ev: MouseEvent) => setBottomPanelHeight(Math.max(100, bottomPanelHeight - (ev.clientY - startY)))
                  const up = () => {
                    document.removeEventListener('mousemove', move)
                    document.removeEventListener('mouseup', up)
                  }
                  document.addEventListener('mousemove', move)
                  document.addEventListener('mouseup', up)
                }}
              />
              <div style={{ height: bottomPanelHeight }} className="shrink-0 border-t border-[var(--border)] flex flex-col">
                <div className="flex border-b border-[var(--border)]">
                  {(['terminal', 'git', 'problems'] as const).map((tab) => (
                    <button
                      key={tab}
                      className={`px-3 py-1 text-xs capitalize ${bottomTab === tab ? 'border-b border-[var(--accent)]' : ''}`}
                      onClick={() => useUIStore.getState().setBottomTab(tab)}
                    >
                      {tab}
                    </button>
                  ))}
                  <button
                    className="ml-auto px-2 text-xs text-[var(--text-secondary)]"
                    onClick={() => useUIStore.getState().toggleBottomPanel()}
                  >
                    ×
                  </button>
                </div>
                <div className="flex-1 overflow-hidden">
                  {bottomTab === 'terminal' && <TerminalPanel />}
                  {bottomTab === 'git' && <GitPanel pollWhenVisible={gitPanelVisible} />}
                  {bottomTab === 'problems' && <LogViewer />}
                </div>
              </div>
            </>
          )}
        </div>

        {!rightPanelCollapsed && (
          <>
            <ResizeHandle onDrag={(d) => setRightPanelWidth(Math.max(200, rightPanelWidth - d))} />
            <div style={{ width: rightPanelWidth }} className="shrink-0 border-l border-[var(--border)] overflow-hidden flex flex-col">
              <div className="flex border-b border-[var(--border)] bg-[var(--bg-secondary)] shrink-0">
                {(['chat', 'runs'] as const).map((tab) => (
                  <button
                    key={tab}
                    className={`px-3 py-2 text-xs uppercase tracking-wide ${
                      rightPanelTab === tab ? 'border-b border-[var(--accent)] text-white' : 'text-[var(--text-secondary)]'
                    }`}
                    onClick={() => useUIStore.getState().setRightPanelTab(tab)}
                  >
                    {tab}
                  </button>
                ))}
              </div>
              <div className="flex-1 overflow-hidden">
                {rightPanelTab === 'chat' ? <ChatPanel /> : <AgentPanel />}
              </div>
            </div>
          </>
        )}
      </div>
      )}

      <StatusBar />
    </div>
  )
}
