import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api } from '@/api/client'
import { useRunDetail } from '@/hooks/useRunDetail'
import { useEditorStore, useProjectStore, useRunStore } from '@/store'
import { useWebSocket } from '@/hooks/useWebSocket'
import { showError, showSuccess } from '@/lib/toast'
import { Button, EmptyState, Skeleton } from '@/components/ui/primitives'
import type { RunSummary } from '@/types/runs'
import { ApproveDialog } from './ApproveDialog'
import { ArtifactViewer } from './ArtifactViewer'
import { RunDetailDrawer } from './RunDetailDrawer'
import { RunHistoryList } from './RunHistoryList'
import { RunLogPanel } from '@/components/shared/RunLogPanel'
import { normalizeRunEvents } from '@/lib/runEvents'

const STAGES = ['planner', 'architect', 'ui_designer', 'coder', 'reviewer', 'tester', 'supervisor']

export function AgentPanel() {
  const projectId = useProjectStore((s) => s.currentProjectId)
  const { currentRunId, runStatus, events, runs, setCurrentRun, setRunStatus, addEvent, setRuns } = useRunStore()
  const { artifacts, loading: detailLoading, hydrateRun } = useRunDetail()
  const [description, setDescription] = useState('')
  const [validationProfile, setValidationProfile] = useState('python')
  const [submitting, setSubmitting] = useState(false)
  const [descError, setDescError] = useState('')
  const [rejectReason, setRejectReason] = useState('')
  const [showReject, setShowReject] = useState(false)
  const [showApprove, setShowApprove] = useState(false)
  const [rejectError, setRejectError] = useState('')
  const [loading, setLoading] = useState(false)
  const [artifactsLoading, setArtifactsLoading] = useState(false)
  const [retryBusy, setRetryBusy] = useState(false)
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [drawerRunId, setDrawerRunId] = useState<string | null>(null)
  const [drawerMode, setDrawerMode] = useState<'detail' | 'list'>('detail')
  const logRef = useRef<HTMLDivElement>(null)
  const [autoScroll, setAutoScroll] = useState(true)
  const [logExpanded, setLogExpanded] = useState(false)
  const normalizedEvents = useMemo(
    () => normalizeRunEvents(events as Array<Record<string, unknown>>),
    [events],
  )

  const runSummaries: RunSummary[] = runs.map((r) => ({
    id: String(r.id),
    status: String(r.status),
    current_stage: r.current_stage != null ? String(r.current_stage) : null,
    task_id: r.task_id != null ? String(r.task_id) : undefined,
    error_message: r.error_message != null ? String(r.error_message) : null,
    created_at: String(r.created_at || ''),
  }))

  const loadRuns = useCallback(async () => {
    if (!projectId) return
    setLoading(true)
    try {
      const data = await api.projects.runs(projectId)
      setRuns(data as Array<Record<string, unknown>>)
    } catch (e) {
      showError(e)
    } finally {
      setLoading(false)
    }
  }, [projectId, setRuns])

  useEffect(() => { loadRuns() }, [loadRuns])

  useEffect(() => {
    if (!currentRunId) return
    setArtifactsLoading(true)
    hydrateRun(currentRunId, false)
      .finally(() => setArtifactsLoading(false))
  }, [currentRunId, hydrateRun])

  useEffect(() => {
    if (events.some((e) => e.type?.toString().includes('_complete'))) {
      if (currentRunId) void hydrateRun(currentRunId, false)
    }
  }, [events, currentRunId, hydrateRun])

  const bumpTreeRefresh = useEditorStore((s) => s.bumpTreeRefresh)

  const applyRunEvent = useCallback((ev: Record<string, unknown>) => {
    const type = String(ev.type || '')
    if (type === 'awaiting_approval') setRunStatus('awaiting_approval', String(ev.stage || ''))
    else if (type === 'run_blocked') setRunStatus('blocked', String(ev.stage || ''))
    else if (type === 'run_failed') setRunStatus('failed', String(ev.stage || ''))
    else if (type === 'run_completed') setRunStatus('completed', String(ev.stage || ''))
    else if (type === 'run_changes_requested') setRunStatus('changes_requested', String(ev.stage || ''))
    else if (type.endsWith('_started')) setRunStatus('running', type.replace('_started', ''))
    if (['run_completed', 'code_patch_applied', 'awaiting_approval'].includes(type)) {
      window.setTimeout(() => bumpTreeRefresh(), 3000)
    }
  }, [bumpTreeRefresh, setRunStatus])

  const onGlobalEvent = useCallback((data: unknown) => {
    const ev = data as Record<string, unknown>
    if (ev.run_id === currentRunId) {
      addEvent(ev)
      applyRunEvent(ev)
    }
  }, [currentRunId, addEvent, applyRunEvent])

  useWebSocket('/api/ws/events', onGlobalEvent, !!projectId)

  const onRunEvent = useCallback((data: unknown) => {
    const ev = data as Record<string, unknown>
    addEvent(ev)
    applyRunEvent(ev)
    if (ev.type?.toString().includes('complete') || ev.type === 'awaiting_approval') {
      loadRuns()
    }
  }, [addEvent, applyRunEvent, loadRuns])

  useWebSocket(
    currentRunId ? `/api/ws/runs/${currentRunId}` : '',
    onRunEvent,
    !!currentRunId
  )

  useEffect(() => {
    if (!logExpanded || !autoScroll || !logRef.current) return
    const scrollEl = logRef.current.querySelector('[data-run-log-scroll]') as HTMLElement | null
    if (!scrollEl) return
    scrollEl.scrollTop = scrollEl.scrollHeight
  }, [normalizedEvents, autoScroll, logExpanded])

  const selectRun = useCallback(async (runId: string) => {
    await hydrateRun(runId, true)
  }, [hydrateRun])

  const openDrawer = (runId: string, mode: 'detail' | 'list' = 'detail') => {
    setDrawerRunId(runId)
    setDrawerMode(mode)
    setDrawerOpen(true)
  }

  const handleRetryWithFeedback = useCallback(async (feedback: string) => {
    if (!currentRunId) return
    setRetryBusy(true)
    try {
      await api.runs.retry(currentRunId, feedback ? { feedback } : undefined)
      setRunStatus('running')
      showSuccess('Retrying pipeline')
      await hydrateRun(currentRunId, true)
    } catch (e) {
      showError(e)
    } finally {
      setRetryBusy(false)
    }
  }, [currentRunId, hydrateRun, setRunStatus])

  const submitTask = async () => {
    if (description.trim().length < 10) {
      setDescError('Description must be at least 10 characters')
      return
    }
    if (!projectId) return
    if (runStatus === 'running') return
    setDescError('')
    setSubmitting(true)
    try {
      const result = await api.tasks.create({
        project_id: projectId,
        description,
        validation_profile: validationProfile,
      }) as { run: { id: string; status: string } }
      const run = result.run
      setCurrentRun(run.id)
      setRunStatus(run.status)
      await hydrateRun(run.id, true)
      showSuccess('Task submitted')
      await loadRuns()
    } catch (e) {
      showError(e)
    } finally {
      setSubmitting(false)
    }
  }

  const stageStatus = (stage: string) => {
    const started = events.some((e) => e.type === `${stage}_started`)
    const complete = events.some((e) => e.type === `${stage}_complete`)
    const failed = events.some((e) => e.type === `${stage}_failed`)
    if (failed) return 'failed'
    if (complete) return 'done'
    if (started) return 'running'
    return 'pending'
  }

  if (!projectId) {
    return <EmptyState title="No project" description="Select a project to run agent tasks" />
  }

  return (
    <div className="h-full flex flex-col p-3 overflow-hidden">
      <div className="mb-3">
        <textarea
          className="w-full h-20 bg-[var(--bg-tertiary)] border border-[var(--border)] rounded p-2 text-sm resize-none"
          placeholder="Describe your task (min 10 chars)..."
          value={description}
          onChange={(e) => setDescription(e.target.value)}
        />
        {descError && <p className="text-[var(--error)] text-xs mt-1">{descError}</p>}
        <div className="flex gap-2 mt-2 items-center">
          <select
            className="bg-[var(--bg-tertiary)] border border-[var(--border)] rounded px-2 py-1 text-sm"
            value={validationProfile}
            onChange={(e) => setValidationProfile(e.target.value)}
          >
            <option value="python">Python</option>
            <option value="react">React</option>
            <option value="fullstack">Fullstack</option>
            <option value="node">Node</option>
            <option value="custom">Custom</option>
          </select>
          <Button
            loading={submitting}
            disabled={runStatus === 'running'}
            title={runStatus === 'running' ? 'A run is already in progress' : undefined}
            onClick={submitTask}
          >
            New Task
          </Button>
        </div>
      </div>

      <div className="flex gap-1 mb-2 flex-wrap">
        {STAGES.map((s) => {
          const st = stageStatus(s)
          return (
            <div key={s} className="flex items-center gap-1 text-xs px-2 py-1 bg-[var(--bg-tertiary)] rounded">
              <span className={`w-2 h-2 rounded-full ${
                st === 'done' ? 'bg-[var(--success)]' :
                st === 'running' ? 'bg-[var(--accent)] animate-pulse' :
                st === 'failed' ? 'bg-[var(--error)]' : 'bg-gray-500'
              }`} />
              {s}
            </div>
          )
        })}
      </div>

      <div className="flex gap-2 mb-2 flex-wrap">
        <Button
          disabled={runStatus !== 'awaiting_approval'}
          onClick={() => setShowApprove(true)}
        >
          Approve
        </Button>
        <Button variant="danger" disabled={runStatus !== 'awaiting_approval'} onClick={() => setShowReject(true)}>
          Reject
        </Button>
        <Button
          variant="secondary"
          disabled={!['blocked', 'changes_requested'].includes(runStatus)}
          onClick={() => void handleRetryWithFeedback('')}
        >
          Retry
        </Button>
        {currentRunId && (
          <Button variant="ghost" className="text-xs" onClick={() => openDrawer(currentRunId)}>
            View details
          </Button>
        )}
      </div>

      <div className={logExpanded ? 'flex-1 min-h-0 flex flex-col mb-2' : 'mb-2 shrink-0'}>
        {events.length === 0 && !loading ? (
          <EmptyState title="No runs yet" description="Submit a task to the Agent panel to get started" />
        ) : (
          <div ref={logRef} className={logExpanded ? 'flex-1 min-h-0 flex flex-col' : undefined}>
            <RunLogPanel
              events={normalizedEvents}
              fullHeight={logExpanded}
              onExpandedChange={setLogExpanded}
              onLogScroll={logExpanded ? (e) => {
                const el = e.currentTarget
                const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 40
                setAutoScroll(atBottom)
              } : undefined}
              emptyLabel={runStatus === 'running' ? 'Pipeline running…' : 'Waiting for updates…'}
            />
          </div>
        )}
      </div>
      {logExpanded && !autoScroll && (
        <Button variant="ghost" className="text-xs mb-2" onClick={() => setAutoScroll(true)}>
          ↓ Jump to bottom
        </Button>
      )}

      <div className={logExpanded ? 'shrink-0 overflow-auto max-h-48' : 'flex-1 min-h-0 overflow-auto'}>
        <ArtifactViewer
          artifacts={artifacts}
          loading={artifactsLoading || detailLoading}
          onRetryWithFeedback={handleRetryWithFeedback}
          retryBusy={retryBusy}
        />
      </div>

      <div className="border-t border-[var(--border)] pt-2 shrink-0">
        <p className="text-xs text-[var(--text-secondary)] mb-1">Run History</p>
        {loading ? (
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

      {showApprove && currentRunId && projectId && (
        <ApproveDialog
          runId={currentRunId}
          projectId={projectId}
          artifacts={artifacts}
          onClose={() => setShowApprove(false)}
          onApproved={() => setRunStatus('completed')}
        />
      )}

      {showReject && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-[var(--bg-secondary)] p-4 rounded border border-[var(--border)] w-96">
            <textarea
              className="w-full h-24 bg-[var(--bg-tertiary)] border border-[var(--border)] rounded p-2 text-sm"
              placeholder="Rejection reason (required)"
              value={rejectReason}
              onChange={(e) => setRejectReason(e.target.value)}
            />
            {rejectError && <p className="text-[var(--error)] text-xs">{rejectError}</p>}
            <div className="flex gap-2 justify-end mt-2">
              <Button variant="secondary" onClick={() => setShowReject(false)}>Cancel</Button>
              <Button onClick={async () => {
                if (!rejectReason.trim()) { setRejectError('Rejection reason required'); return }
                if (!currentRunId) return
                try {
                  await api.runs.reject(currentRunId, rejectReason)
                  showSuccess('Run rejected')
                  setShowReject(false)
                  await hydrateRun(currentRunId, true)
                } catch (e) { showError(e) }
              }}>Submit</Button>
            </div>
          </div>
        </div>
      )}

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
