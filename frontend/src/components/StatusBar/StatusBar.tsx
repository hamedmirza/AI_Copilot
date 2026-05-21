import { useAppStore, useProjectStore, useRunStore, useUIStore } from '@/store'

export function StatusBar() {
  const backendOnline = useAppStore((s) => s.backendOnline)
  const wsReconnecting = useAppStore((s) => s.wsReconnecting)
  const projects = useProjectStore((s) => s.projects)
  const currentProjectId = useProjectStore((s) => s.currentProjectId)
  const runStatus = useRunStore((s) => s.runStatus)
  const currentStage = useRunStore((s) => s.currentStage)

  const project = projects.find((p) => p.id === currentProjectId)

  return (
    <div className="h-6 flex items-center justify-between px-3 bg-[var(--accent)] text-white text-xs shrink-0">
      <div className="flex items-center gap-3">
        <span>{project ? String(project.name) : 'No project'}</span>
        <span className="opacity-70">|</span>
        <span className={`flex items-center gap-1 ${backendOnline ? '' : 'text-yellow-200'}`}>
          <span className={`w-2 h-2 rounded-full ${backendOnline ? 'bg-green-300' : 'bg-yellow-300'}`} />
          {backendOnline ? 'Backend online' : 'Backend offline'}
        </span>
        {wsReconnecting && <span className="text-yellow-200">Reconnecting...</span>}
      </div>
      <div className="opacity-90">
        {runStatus === 'idle' ? 'Idle' :
         runStatus === 'running' ? `Running: ${currentStage || '...'}` :
         runStatus === 'awaiting_approval' ? 'Awaiting approval' :
         runStatus === 'blocked' ? 'Blocked' : runStatus}
      </div>
      <div className="opacity-70">⌘, Settings</div>
    </div>
  )
}
