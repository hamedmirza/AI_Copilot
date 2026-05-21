import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '@/api/client'
import { useEditorStore, useProjectStore, useRunStore } from '@/store'
import { useWebSocket } from '@/hooks/useWebSocket'
import { showError, showSuccess } from '@/lib/toast'
import { Button, EmptyState, Skeleton } from '@/components/ui/primitives'
import { ArtifactViewer } from './ArtifactViewer'

const STAGES = ['planner', 'architect', 'ui_designer', 'coder', 'reviewer', 'tester', 'supervisor']

export function AgentPanel() {
  const projectId = useProjectStore((s) => s.currentProjectId)
  const { currentRunId, runStatus, events, runs, setCurrentRun, setRunStatus, addEvent, setEvents, setRuns } = useRunStore()
  const [description, setDescription] = useState('')
  const [validationProfile, setValidationProfile] = useState('python')
  const [submitting, setSubmitting] = useState(false)
  const [descError, setDescError] = useState('')
  const [rejectReason, setRejectReason] = useState('')
  const [showReject, setShowReject] = useState(false)
  const [rejectError, setRejectError] = useState('')
  const [loading, setLoading] = useState(false)
  const [artifacts, setArtifacts] = useState<Array<{ id: number; artifact_type: string; content: Record<string, unknown>; created_at: string }>>([])
  const [artifactsLoading, setArtifactsLoading] = useState(false)
  const logRef = useRef<HTMLDivElement>(null)
  const [autoScroll, setAutoScroll] = useState(true)

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

  const loadArtifacts = useCallback(async () => {
    if (!currentRunId) {
      setArtifacts([])
      return
    }
    setArtifactsLoading(true)
    try {
      const data = await api.runs.artifacts(currentRunId) as Array<{ id: number; artifact_type: string; content: Record<string, unknown>; created_at: string }>
      setArtifacts(data)
    } catch (e) {
      showError(e)
    } finally {
      setArtifactsLoading(false)
    }
  }, [currentRunId])

  useEffect(() => { loadArtifacts() }, [loadArtifacts])

  useEffect(() => {
    if (events.some((e) => e.type?.toString().includes('_complete'))) {
      loadArtifacts()
    }
  }, [events, loadArtifacts])

  const bumpTreeRefresh = useEditorStore((s) => s.bumpTreeRefresh)

  const applyRunEvent = useCallback((ev: Record<string, unknown>) => {
    const type = String(ev.type || '')
    if (type === 'awaiting_approval') setRunStatus('awaiting_approval', String(ev.stage || ''))
    else if (type === 'run_blocked') setRunStatus('blocked', String(ev.stage || ''))
    else if (type === 'run_failed') setRunStatus('failed', String(ev.stage || ''))
    else if (type === 'run_completed') setRunStatus('completed', String(ev.stage || ''))
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
    if (autoScroll && logRef.current) {
      logRef.current.scrollTop = logRef.current.scrollHeight
    }
  }, [events, autoScroll])

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
      setEvents([])
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

      <div className="flex gap-2 mb-2">
        <Button
          disabled={runStatus !== 'awaiting_approval'}
          onClick={async () => {
            if (!currentRunId || !confirm('Approve and apply changes?')) return
            try {
              await api.runs.approve(currentRunId)
              showSuccess('Approved — applying changes')
              setRunStatus('completed')
            } catch (e) { showError(e) }
          }}
        >
          Approve
        </Button>
        <Button variant="danger" disabled={runStatus !== 'awaiting_approval'} onClick={() => setShowReject(true)}>
          Reject
        </Button>
        <Button
          variant="secondary"
          disabled={!['blocked', 'changes_requested'].includes(runStatus)}
          onClick={async () => {
            if (!currentRunId) return
            try {
              await api.runs.retry(currentRunId)
              setRunStatus('running')
              showSuccess('Retrying from coder stage')
            } catch (e) { showError(e) }
          }}
        >
          Retry
        </Button>
      </div>

      <div
        ref={logRef}
        className="flex-1 overflow-auto bg-[#1a1a1a] rounded p-2 text-xs font-mono mb-2"
        onScroll={(e) => {
          const el = e.currentTarget
          const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 40
          setAutoScroll(atBottom)
        }}
      >
        {events.length === 0 && !loading && (
          <EmptyState title="No runs yet" description="Submit a task to the Agent panel to get started" />
        )}
        {events.map((ev, i) => (
          <div key={i} className={`py-0.5 ${
            ev.severity === 'error' ? 'text-[var(--error)]' :
            ev.severity === 'warn' ? 'text-[var(--warning)]' : 'text-[var(--text-secondary)]'
          }`}>
            [{String(ev.type)}] {String(ev.message || '')}
          </div>
        ))}
      </div>
      {!autoScroll && (
        <Button variant="ghost" className="text-xs mb-2" onClick={() => setAutoScroll(true)}>
          ↓ Jump to bottom
        </Button>
      )}

      <ArtifactViewer artifacts={artifacts} loading={artifactsLoading} />

      {loading ? (
        <Skeleton className="h-20 w-full" />
      ) : (
        <div className="max-h-32 overflow-auto border-t border-[var(--border)] pt-2">
          <p className="text-xs text-[var(--text-secondary)] mb-1">Run History</p>
          {runs.map((r) => (
            <div
              key={String(r.id)}
              className="text-xs py-1 hover:bg-[var(--bg-tertiary)] cursor-pointer px-1 rounded"
              onClick={() => { setCurrentRun(String(r.id)); setRunStatus(String(r.status)); setEvents([]) }}
            >
              {String(r.id).slice(0, 8)} — {String(r.status)}
            </div>
          ))}
        </div>
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
                } catch (e) { showError(e) }
              }}>Submit</Button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
