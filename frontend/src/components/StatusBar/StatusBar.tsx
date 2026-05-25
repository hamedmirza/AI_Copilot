import { useCallback, useEffect, useState } from 'react'
import { api } from '@/api/client'
import { useAppStore, useChatStore, useProjectStore, useRunStore, useSettingsStore } from '@/store'

function formatUptime(seconds: number): string {
  if (seconds < 60) return `${seconds}s`
  const m = Math.floor(seconds / 60)
  if (m < 60) return `${m}m`
  const h = Math.floor(m / 60)
  return `${h}h ${m % 60}m`
}

function providerDotClass(status: string | null): string {
  if (status === 'healthy') return 'bg-green-300'
  if (status === 'unreachable') return 'bg-red-300'
  return 'bg-yellow-300'
}

export function StatusBar() {
  const backendOnline = useAppStore((s) => s.backendOnline)
  const wsReconnecting = useAppStore((s) => s.wsReconnecting)
  const wsConnections = useAppStore((s) => s.wsConnections)
  const setBackendOnline = useAppStore((s) => s.setBackendOnline)
  const setWsConnections = useAppStore((s) => s.setWsConnections)
  const projects = useProjectStore((s) => s.projects)
  const currentProjectId = useProjectStore((s) => s.currentProjectId)
  const runStatus = useRunStore((s) => s.runStatus)
  const currentStage = useRunStore((s) => s.currentStage)
  const settings = useSettingsStore((s) => s.settings)
  const chatStreaming = useChatStore((s) => s.streaming)
  const chatAssistantStatus = useChatStore((s) => s.assistantStatus)
  const chatStreamingContent = useChatStore((s) => s.streamingContent)

  const [branch, setBranch] = useState<string | null>(null)
  const [providerStatus, setProviderStatus] = useState<string | null>(null)
  const [activeProvider, setActiveProvider] = useState<'lmstudio' | 'ollama'>('lmstudio')
  const [uptimeSeconds, setUptimeSeconds] = useState<number | null>(null)
  const [workerCount, setWorkerCount] = useState<number | null>(null)

  const project = projects.find((p) => String(p.id) === String(currentProjectId))
  const workers = workerCount ?? (typeof settings.worker_count === 'number' ? settings.worker_count : 1)

  const refreshHealth = useCallback(async () => {
    try {
      const h = await api.health()
      setBackendOnline(true)
      setUptimeSeconds(h.uptime_seconds ?? null)
      setWorkerCount(h.worker_count ?? null)
      if (h.ws_connections !== undefined) setWsConnections(h.ws_connections)
    } catch {
      setBackendOnline(false)
    }
  }, [setBackendOnline, setWsConnections])

  const refreshProvider = useCallback(async () => {
    try {
      const h = await api.providerHealth()
      setActiveProvider(h.active_provider === 'ollama' ? 'ollama' : 'lmstudio')
      setProviderStatus(h.active_provider === 'ollama' ? h.ollama : h.lmstudio)
    } catch {
      setProviderStatus('unreachable')
    }
  }, [])

  const refreshBranch = useCallback(async () => {
    if (!currentProjectId) {
      setBranch(null)
      return
    }
    try {
      const st = await api.git.status(currentProjectId) as { branch?: string }
      setBranch(st.branch || null)
    } catch {
      setBranch(null)
    }
  }, [currentProjectId])

  useEffect(() => {
    refreshHealth()
    refreshProvider()
    const interval = setInterval(() => {
      refreshHealth()
      refreshProvider()
    }, 15000)
    return () => clearInterval(interval)
  }, [refreshHealth, refreshProvider])

  useEffect(() => {
    refreshBranch()
  }, [refreshBranch])

  const runLabel =
    runStatus === 'idle' ? 'Idle' :
    runStatus === 'running' ? `Running: ${currentStage || '…'}` :
    runStatus === 'awaiting_clarification' ? 'Awaiting clarification' :
    runStatus === 'awaiting_approval' ? 'Awaiting approval' :
    runStatus === 'blocked' ? 'Blocked' : runStatus

  return (
    <div className="h-6 flex items-center justify-between px-3 bg-[var(--accent)] text-white text-xs shrink-0 gap-2">
      <div className="flex items-center gap-2 min-w-0 truncate">
        <span className="truncate">{project ? String(project.name) : 'No project'}</span>
        {branch && (
          <>
            <span className="opacity-70">|</span>
            <span className="truncate opacity-90">{branch}</span>
          </>
        )}
        <span className="opacity-70">|</span>
        <span
          className="flex items-center gap-1 shrink-0"
          title={`${activeProvider === 'ollama' ? 'Ollama' : 'LM Studio'}: ${providerStatus || 'unknown'}`}
        >
          <span className={`w-2 h-2 rounded-full ${providerDotClass(providerStatus)}`} />
          <span className="opacity-90">{activeProvider === 'ollama' ? 'Ollama' : 'LM'}</span>
        </span>
        {chatStreaming && (
          <span className="text-blue-100 shrink-0">
            {chatStreamingContent
              ? 'Streaming…'
              : (chatAssistantStatus || 'Thinking…')}
          </span>
        )}
        {!backendOnline && <span className="text-yellow-200 shrink-0">Backend offline</span>}
        {wsReconnecting && <span className="text-yellow-200 shrink-0">Reconnecting…</span>}
      </div>
      <div className="opacity-90 shrink-0 hidden sm:block">{runLabel}</div>
      <div className="flex items-center gap-2 opacity-80 shrink-0">
        {uptimeSeconds !== null && <span title="Server uptime">{formatUptime(uptimeSeconds)}</span>}
        <span title="Worker count">W:{workers}</span>
        <span title="WebSocket connections">WS:{wsConnections}</span>
        <span className="hidden md:inline">⌘, Settings</span>
      </div>
    </div>
  )
}
