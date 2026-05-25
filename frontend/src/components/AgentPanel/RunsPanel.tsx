import { useCallback, useEffect, useMemo, useState } from 'react'
import { api } from '@/api/client'
import { useRunDetail } from '@/hooks/useRunDetail'
import { useProjectStore, useRunStore } from '@/store'
import { useWebSocket } from '@/hooks/useWebSocket'
import { showError } from '@/lib/toast'
import { Button, EmptyState, Skeleton } from '@/components/ui/primitives'
import type { RunSummary } from '@/types/runs'
import { RunHistoryList } from './RunHistoryList'
import { RunDetailDrawer } from './RunDetailDrawer'

export function RunsPanel() {
  const projectId = useProjectStore((s) => s.currentProjectId)
  const { currentRunId, runs, setRuns } = useRunStore()
  const { hydrateRun } = useRunDetail()
  const [loadingRuns, setLoadingRuns] = useState(false)
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [drawerRunId, setDrawerRunId] = useState<string | null>(null)
  const [drawerMode, setDrawerMode] = useState<'detail' | 'list'>('detail')

  const runSummaries: RunSummary[] = useMemo(() => runs.map((r) => ({
    id: String(r.id),
    display_name: r.display_name != null ? String(r.display_name) : undefined,
    status: String(r.status),
    current_stage: r.current_stage != null ? String(r.current_stage) : null,
    task_id: r.task_id != null ? String(r.task_id) : undefined,
    task_kind: r.task_kind != null ? String(r.task_kind) : null,
    failure_class: r.failure_class != null ? String(r.failure_class) : null,
    recovery_status: r.recovery_status != null ? String(r.recovery_status) : null,
    error_message: r.error_message != null ? String(r.error_message) : null,
    created_at: String(r.created_at || ''),
  })), [runs])

  const currentRun = runSummaries.find((run) => run.id === currentRunId) || runSummaries[0] || null

  const loadRuns = useCallback(async () => {
    if (!projectId) {
      setRuns([])
      return
    }
    setLoadingRuns(true)
    try {
      const data = await api.projects.runs(projectId)
      setRuns(data as Array<Record<string, unknown>>)
    } catch (e) {
      showError(e)
    } finally {
      setLoadingRuns(false)
    }
  }, [projectId, setRuns])

  useEffect(() => { void loadRuns() }, [loadRuns])

  useWebSocket('/api/ws/events', useCallback((data: unknown) => {
    const ev = data as Record<string, unknown>
    const type = String(ev.type || '')
    if (!projectId) return
    if (['run_completed', 'run_failed', 'run_blocked', 'run_changes_requested', 'awaiting_approval'].includes(type)) {
      void loadRuns()
    }
  }, [loadRuns, projectId]), Boolean(projectId))

  const selectRun = useCallback(async (runId: string) => {
    await hydrateRun(runId, true)
  }, [hydrateRun])

  const openDrawer = (runId: string, mode: 'detail' | 'list' = 'detail') => {
    setDrawerRunId(runId)
    setDrawerMode(mode)
    setDrawerOpen(true)
  }

  if (!projectId) {
    return <EmptyState title="No project" description="Select a project to inspect run history" />
  }

  return (
    <div className="h-full flex flex-col p-3 overflow-hidden">
      <div className="rounded border border-[var(--border)] px-3 py-2 shrink-0">
        <p className="text-xs text-[var(--text-secondary)] mb-1 uppercase tracking-wide">Current run</p>
        {currentRun ? (
          <div className="space-y-2">
            <div>
              <p className="text-sm font-medium truncate">{currentRun.display_name || currentRun.id}</p>
              <p className="text-xs text-[var(--text-secondary)]">
                {currentRun.status}
                {currentRun.current_stage ? ` · ${currentRun.current_stage}` : ''}
                {currentRun.failure_class ? ` · ${currentRun.failure_class}` : ''}
              </p>
            </div>
            <Button variant="ghost" className="text-xs h-7 px-2" onClick={() => openDrawer(currentRun.id)}>
              Open run details
            </Button>
          </div>
        ) : (
          <p className="text-xs text-[var(--text-secondary)]">No runs yet.</p>
        )}
      </div>

      <div className="border-t border-[var(--border)] pt-2 mt-3 shrink-0">
        <p className="text-xs text-[var(--text-secondary)] mb-1">Run History</p>
        {loadingRuns ? (
          <Skeleton className="h-20 w-full" />
        ) : (
          <RunHistoryList
            runs={runSummaries}
            currentRunId={currentRunId}
            onSelect={(id) => void selectRun(id)}
            onOpenDetails={(id) => openDrawer(id)}
            onViewAll={() => openDrawer(runSummaries[0]?.id || currentRunId || '', 'list')}
          />
        )}
      </div>

      <RunDetailDrawer
        open={drawerOpen}
        runId={drawerRunId}
        runs={runSummaries}
        mode={drawerMode}
        onClose={() => setDrawerOpen(false)}
        onRunChange={(id) => {
          setDrawerRunId(id)
          setDrawerMode('detail')
          void selectRun(id)
        }}
      />
    </div>
  )
}
