import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api } from '@/api/client'
import { useRunDetail } from '@/hooks/useRunDetail'
import { latestActivityLineFromEvents, patchRunsFromEvent } from '@/lib/runEvents'
import { useProjectStore, useRunStore, useUIStore } from '@/store'
import { subscribeGlobalRunEvents } from '@/lib/globalRunEvents'
import { showError } from '@/lib/toast'
import { EmptyState, Skeleton } from '@/components/ui/primitives'
import {
  formatRunElapsed,
  formatRunRelativeTime,
  hasRecoveryMetadata,
  runDisplayLabel,
  runStatusBadgeClass,
  runStatusLabel,
  type RunSummary,
} from '@/types/runs'
import { RunDetailDrawer } from './RunDetailDrawer'

type StatusFilter = 'all' | 'running' | 'done' | 'failed'

function matchesFilter(status: string, filter: StatusFilter): boolean {
  if (filter === 'all') return true
  if (filter === 'running') {
    return ['pending', 'running', 'awaiting_clarification', 'awaiting_approval'].includes(status)
  }
  if (filter === 'done') return status === 'completed'
  if (filter === 'failed') {
    return ['failed', 'blocked', 'changes_requested', 'cancelled'].includes(status)
  }
  return true
}

const FILTER_OPTIONS: { id: StatusFilter; label: string }[] = [
  { id: 'all', label: 'All' },
  { id: 'running', label: 'Running' },
  { id: 'done', label: 'Done' },
  { id: 'failed', label: 'Failed' },
]

export function RunsPanel() {
  const projectId = useProjectStore((s) => s.currentProjectId)
  const { currentRunId, runs, setRuns, setCurrentRun, appendRunEvent, runEventsByRunId } = useRunStore()
  const { hydrateRun } = useRunDetail()
  const [loadingRuns, setLoadingRuns] = useState(false)
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all')
  const [searchQuery, setSearchQuery] = useState('')
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null)
  const runsRef = useRef(runs)
  runsRef.current = runs
  const runDrawerRequest = useUIStore((s) => s.runDrawerRequest)
  const clearRunDrawerRequest = useUIStore((s) => s.clearRunDrawerRequest)
  const rightPanelTab = useUIStore((s) => s.rightPanelTab)

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
    updated_at: r.updated_at != null ? String(r.updated_at) : undefined,
    last_event_at: r.last_event_at != null ? String(r.last_event_at) : null,
    stale_running: Boolean(r.stale_running),
  })), [runs])

  const filteredRuns = useMemo(() => {
    const q = searchQuery.trim().toLowerCase()
    return runSummaries.filter((run) => {
      if (!matchesFilter(run.status, statusFilter)) return false
      if (!q) return true
      const label = runDisplayLabel(run).toLowerCase()
      return label.includes(q) || run.id.toLowerCase().includes(q)
    })
  }, [runSummaries, statusFilter, searchQuery])

  const loadRuns = useCallback(async () => {
    if (!projectId) {
      setRuns([])
      setSelectedRunId(null)
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

  useEffect(() => {
    if (!selectedRunId && filteredRuns.length > 0) {
      const preferred = currentRunId && filteredRuns.some((r) => r.id === currentRunId)
        ? currentRunId
        : filteredRuns[0].id
      setSelectedRunId(preferred)
    }
  }, [currentRunId, filteredRuns, selectedRunId])

  useEffect(() => {
    if (selectedRunId && !filteredRuns.some((r) => r.id === selectedRunId)) {
      setSelectedRunId(filteredRuns[0]?.id ?? null)
    }
  }, [filteredRuns, selectedRunId])

  useEffect(() => {
    if (!projectId) return
    return subscribeGlobalRunEvents((ev) => {
      const type = String(ev.type || '')
      const runId = String(ev.run_id || '')
      const currentRuns = runsRef.current
      if (runId) {
        appendRunEvent(runId, ev)
        const patched = patchRunsFromEvent(
          currentRuns.map((r) => ({
            id: String(r.id),
            status: String(r.status || 'pending'),
            current_stage: r.current_stage != null ? String(r.current_stage) : null,
          })),
          { run_id: runId, type, stage: ev.stage != null ? String(ev.stage) : null },
        )
        if (patched) {
          setRuns(patched.map((row) => {
            const existing = currentRuns.find((r) => String(r.id) === row.id)
            return existing ? { ...existing, ...row } : row
          }) as Array<Record<string, unknown>>)
        }
      }
      const refreshList = [
        'run_completed',
        'run_failed',
        'run_blocked',
        'run_changes_requested',
        'awaiting_approval',
      ].includes(type)
      const patchStage = type.endsWith('_started') || type.startsWith('pipeline_tool_')
      if (refreshList || patchStage) {
        void loadRuns()
      }
    })
  }, [appendRunEvent, loadRuns, projectId, setRuns])

  const selectRun = useCallback(async (runId: string) => {
    setSelectedRunId(runId)
    setCurrentRun(runId)
    await hydrateRun(runId, true)
  }, [hydrateRun, setCurrentRun])

  useEffect(() => {
    if (!runDrawerRequest || rightPanelTab !== 'runs') return
    void selectRun(runDrawerRequest.runId)
    clearRunDrawerRequest()
  }, [runDrawerRequest, rightPanelTab, clearRunDrawerRequest, selectRun])

  if (!projectId) {
    return <EmptyState title="No project" description="Select a project to inspect run history" />
  }

  return (
    <div className="h-full flex min-h-0 overflow-hidden">
      <div className="w-[40%] min-w-0 flex flex-col border-r border-[var(--border)] p-2">
        <div className="shrink-0 mb-2 space-y-2">
          <input
            type="search"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search runs…"
            className="w-full text-xs px-2 py-1.5 rounded border border-[var(--border)] bg-[var(--bg-tertiary)] outline-none focus:border-[var(--accent)]"
            aria-label="Search runs"
          />
          <div className="flex flex-wrap gap-1">
          {FILTER_OPTIONS.map((opt) => (
            <button
              key={opt.id}
              type="button"
              className={`text-[10px] px-2 py-1 rounded-full border transition-colors ${
                statusFilter === opt.id
                  ? 'border-[var(--accent)] bg-[var(--accent)]/15 text-[var(--accent)]'
                  : 'border-[var(--border)] text-[var(--text-secondary)] hover:text-[var(--text-primary)]'
              }`}
              onClick={() => setStatusFilter(opt.id)}
            >
              {opt.label}
            </button>
          ))}
          </div>
        </div>

        <div className="flex-1 min-h-0 overflow-auto space-y-1">
          {loadingRuns ? (
            <Skeleton className="h-16 w-full" />
          ) : filteredRuns.length === 0 ? (
            <p className="text-xs text-[var(--text-secondary)] p-2">No runs match this filter.</p>
          ) : (
            filteredRuns.map((run) => {
              const selected = selectedRunId === run.id
              const activity = latestActivityLineFromEvents(runEventsByRunId[run.id] || [])
              const isRunning = ['pending', 'running', 'awaiting_clarification', 'awaiting_approval'].includes(run.status) && !run.stale_running
              return (
                <button
                  key={run.id}
                  type="button"
                  className={`w-full text-left px-2 py-2 rounded border text-xs transition-colors ${
                    selected
                      ? 'border-[var(--accent)] bg-[var(--accent)]/10'
                      : 'border-transparent hover:bg-[var(--bg-tertiary)]'
                  } ${isRunning ? 'animate-pulse' : ''}`}
                  onClick={() => void selectRun(run.id)}
                >
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className={`px-1.5 py-0.5 rounded uppercase text-[10px] ${runStatusBadgeClass(run.status)}`}>
                      {runStatusLabel(run.status)}
                    </span>
                    {hasRecoveryMetadata(run) && (
                      <span className="text-[10px] text-[var(--text-secondary)] shrink-0">(R)</span>
                    )}
                    <span className="flex-1 min-w-0 truncate font-medium">{runDisplayLabel(run)}</span>
                  </div>
                  <div className="mt-0.5 text-[10px] text-[var(--text-secondary)] flex gap-2 flex-wrap">
                    <span>{formatRunRelativeTime(run.created_at)}</span>
                    {(() => {
                      const elapsed = formatRunElapsed(run.created_at, run.updated_at, run.status)
                      return elapsed ? <span>{elapsed}</span> : null
                    })()}
                    {run.stale_running && <span className="text-amber-400">stalled</span>}
                    {run.current_stage && <span className="truncate">{run.current_stage}</span>}
                    {activity && <span className="truncate text-[var(--accent)]">{activity}</span>}
                  </div>
                </button>
              )
            })
          )}
        </div>
      </div>

      <div className="w-[60%] min-w-0 flex flex-col">
        <RunDetailDrawer
          open={!!selectedRunId}
          runId={selectedRunId}
          runs={runSummaries}
          displayMode="inline"
          initialTab="pipeline"
          onClose={() => setSelectedRunId(null)}
          onRunChange={(id) => void selectRun(id)}
        />
      </div>
    </div>
  )
}
