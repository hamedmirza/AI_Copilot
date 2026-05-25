import { useCallback, useEffect, useMemo, useState } from 'react'
import { X } from 'lucide-react'
import { api } from '@/api/client'
import { useRunDetail } from '@/hooks/useRunDetail'
import { useWebSocket } from '@/hooks/useWebSocket'
import { showError, showSuccess } from '@/lib/toast'
import { Button } from '@/components/ui/primitives'
import { PipelineTimeline } from './PipelineTimeline'
import {
  isRetryableStatus,
  latestReviewArtifact,
  type GlobalSkillRecord,
  type LessonRecord,
  type PostmortemRecord,
  runDisplayLabel,
  runStatusBadgeClass,
  runStatusLabel,
  type RunSummary,
} from '@/types/runs'
import { useChatStore, useProjectStore, useRunStore, useUIStore } from '@/store'
import { ArtifactViewer } from './ArtifactViewer'
import { ApproveDialog } from './ApproveDialog'
import { ReviewArtifactPanel } from './ReviewArtifactPanel'
import { RunLogPanel } from '@/components/shared/RunLogPanel'
import { RunConversationPanel } from './RunConversationPanel'
import { RunComposer } from './RunComposer'
import { VisualEvidencePanel, type VisualEvidencePayload } from './VisualEvidencePanel'

type DrawerMode = 'detail' | 'list'
type DrawerTab = 'conversation' | 'pipeline'

function defaultDrawerTab(status: string): DrawerTab {
  if (status === 'awaiting_clarification' || status === 'awaiting_approval') {
    return 'conversation'
  }
  return 'pipeline'
}

interface RunDetailDrawerProps {
  open: boolean
  runId: string | null
  runs: RunSummary[]
  projectLessons?: LessonRecord[]
  globalSkills?: GlobalSkillRecord[]
  mode?: DrawerMode
  displayMode?: 'drawer' | 'inline'
  initialTab?: DrawerTab
  onClose: () => void
  onRunChange?: (runId: string) => void
}

export function RunDetailDrawer({
  open,
  runId,
  runs,
  projectLessons = [],
  globalSkills = [],
  mode = 'detail',
  displayMode = 'drawer',
  initialTab,
  onClose,
  onRunChange,
}: RunDetailDrawerProps) {
  const inline = displayMode === 'inline'
  const projectId = useProjectStore((s) => s.currentProjectId)
  const setRunStatus = useRunStore((s) => s.setRunStatus)
  const setCurrentSessionId = useChatStore((s) => s.setCurrentSessionId)
  const setRightPanelTab = useUIStore((s) => s.setRightPanelTab)
  const {
    detail,
    events,
    artifacts,
    thread,
    threadLoading,
    loading,
    hydrateRun,
    refreshThread,
  } = useRunDetail()
  const [listOnly, setListOnly] = useState(mode === 'list')
  const [activeTab, setActiveTab] = useState<DrawerTab>('pipeline')
  const [showApprove, setShowApprove] = useState(false)
  const [busy, setBusy] = useState(false)
  const [confirmRollback, setConfirmRollback] = useState<'workspace' | 'promote' | null>(null)
  const [postmortem, setPostmortem] = useState<PostmortemRecord | null>(null)
  const [deploymentGates, setDeploymentGates] = useState<
    Array<{ id: string; label: string; passed: boolean; required: boolean; detail: string }>
  >([])
  const [visualEvidence, setVisualEvidence] = useState<VisualEvidencePayload | null>(null)

  useEffect(() => {
    setListOnly(mode === 'list')
  }, [mode, open])

  useEffect(() => {
    if (!open || !runId || listOnly) return
    void hydrateRun(runId, true)
  }, [open, runId, listOnly, hydrateRun])

  useEffect(() => {
    if (!open || !runId) return
    setActiveTab(initialTab ?? (detail ? defaultDrawerTab(detail.status) : 'pipeline'))
  }, [open, runId, initialTab])

  useEffect(() => {
    if (!open || !runId || listOnly) return
    setPostmortem(null)
    void api.runs.postmortem(runId)
      .then((artifact) => setPostmortem(artifact as PostmortemRecord))
      .catch(() => setPostmortem(null))
  }, [listOnly, open, runId])

  useEffect(() => {
    if (!open || !runId || listOnly) return
    void api.runs.deploymentReadiness(runId)
      .then((data) => {
        setDeploymentGates(data.gates ?? [])
        setVisualEvidence((data.visual_evidence as VisualEvidencePayload | null) ?? null)
      })
      .catch(() => {
        setDeploymentGates([])
        setVisualEvidence(null)
      })
  }, [listOnly, open, runId, detail?.status])

  const onRunWsEvent = useCallback((data: unknown) => {
    const ev = data as Record<string, unknown>
    const type = String(ev.type || '')
    if (type === 'run_clarification_requested') {
      setRunStatus('awaiting_clarification', String(ev.stage || ''))
    } else if (type === 'awaiting_approval') {
      setRunStatus('awaiting_approval', String(ev.stage || ''))
    } else if (type === 'run_blocked') {
      setRunStatus('blocked', String(ev.stage || ''))
    } else if (type === 'run_failed') {
      setRunStatus('failed', String(ev.stage || ''))
    } else if (type === 'run_completed') {
      setRunStatus('completed', String(ev.stage || ''))
    } else if (type === 'run_changes_requested') {
      setRunStatus('changes_requested', String(ev.stage || ''))
    } else if (type.endsWith('_started')) {
      setRunStatus('running', type.replace('_started', ''))
    }
    if (runId) void refreshThread(runId)
    if (runId && (type.includes('complete') || type === 'awaiting_approval' || type === 'run_clarification_requested')) {
      void hydrateRun(runId, false)
    }
  }, [hydrateRun, refreshThread, runId, setRunStatus])

  useWebSocket(
    runId && open && !listOnly ? `/api/ws/runs/${runId}` : '',
    onRunWsEvent,
    Boolean(runId && open && !listOnly),
  )

  const reviewArtifact = useMemo(() => latestReviewArtifact(artifacts), [artifacts])
  const readinessWarnings = useMemo(() => {
    const readiness = detail?.readiness
    if (!readiness || typeof readiness !== 'object') return []
    const warnings = (readiness as Record<string, unknown>).warnings
    return Array.isArray(warnings) ? warnings.map((item) => String(item)) : []
  }, [detail?.readiness])

  const handleContinueVisual = useCallback(async () => {
    if (!runId) return
    setBusy(true)
    try {
      useUIStore.getState().setActiveCenterView('browser')
      await api.runs.continueVisual(runId)
      showSuccess('Visual verification resumed')
      await hydrateRun(runId, true)
      const data = await api.runs.deploymentReadiness(runId)
      setDeploymentGates(data.gates ?? [])
      setVisualEvidence((data.visual_evidence as VisualEvidencePayload | null) ?? null)
    } catch (e) {
      showError(e)
    } finally {
      setBusy(false)
    }
  }, [hydrateRun, runId])

  const visualEvidenceFromArtifacts = useMemo(() => {
    const row = artifacts.find((a) => a.artifact_type === 'visual_evidence')
    return row ? (row.content as VisualEvidencePayload) : null
  }, [artifacts])

  const resolvedVisualEvidence = visualEvidence ?? visualEvidenceFromArtifacts

  const needsBrowserClient = useMemo(
    () =>
      events.some((event) => String(event.type || '') === 'browser_client_required')
      || Boolean(resolvedVisualEvidence?.browser_client_required),
    [events, resolvedVisualEvidence?.browser_client_required],
  )

  const clarificationWarnings = useMemo(
    () => readinessWarnings.filter((w) => !w.toLowerCase().includes('clarification')),
    [readinessWarnings],
  )

  const handleClarify = useCallback(async (answer: string) => {
    if (!runId) return
    setBusy(true)
    try {
      await api.runs.clarify(runId, answer)
      setRunStatus('running')
      showSuccess('Clarification sent — pipeline resuming')
      await hydrateRun(runId, true)
      await refreshThread(runId)
      setActiveTab('conversation')
    } catch (e) {
      showError(e)
    } finally {
      setBusy(false)
    }
  }, [hydrateRun, refreshThread, runId, setRunStatus])

  const handleRetry = useCallback(async (feedback = '') => {
    if (!runId) return
    setBusy(true)
    try {
      await api.runs.retry(runId, feedback ? { feedback } : undefined)
      setRunStatus('running')
      showSuccess('Pipeline retry started')
      await hydrateRun(runId, true)
      await refreshThread(runId)
    } catch (e) {
      showError(e)
    } finally {
      setBusy(false)
    }
  }, [hydrateRun, refreshThread, runId, setRunStatus])

  const handleResume = useCallback(async () => {
    if (!runId) return
    setBusy(true)
    try {
      await api.runs.resume(runId)
      setRunStatus('running')
      showSuccess('Run re-queued')
      await hydrateRun(runId, true)
    } catch (e) {
      showError(e)
    } finally {
      setBusy(false)
    }
  }, [hydrateRun, runId, setRunStatus])

  const handleOpenChat = useCallback(() => {
    if (!detail?.chat_session_id) {
      showError('No chat session linked to this run yet.')
      return
    }
    setCurrentSessionId(detail.chat_session_id)
    setRightPanelTab('chat')
    showSuccess('Opened linked chat session')
  }, [detail?.chat_session_id, setCurrentSessionId, setRightPanelTab])

  const handleRollbackWorkspace = useCallback(async () => {
    if (!runId) return
    setBusy(true)
    try {
      await api.runs.rollbackWorkspace(runId)
      showSuccess('Workspace reset from project source')
      setConfirmRollback(null)
      await hydrateRun(runId, true)
    } catch (e) {
      showError(e)
    } finally {
      setBusy(false)
    }
  }, [hydrateRun, runId])

  const handleRollbackPromote = useCallback(async () => {
    if (!runId) return
    setBusy(true)
    try {
      const result = await api.runs.rollbackPromote(runId) as { restored_files?: number }
      showSuccess(`Promotion undone (${result.restored_files ?? 0} file(s) restored)`)
      setConfirmRollback(null)
      await hydrateRun(runId, true)
    } catch (e) {
      showError(e)
    } finally {
      setBusy(false)
    }
  }, [hydrateRun, runId])

  const copyRunId = () => {
    if (!runId) return
    navigator.clipboard.writeText(runId)
    showSuccess('Run ID copied')
  }

  if (!open) {
    if (inline) {
      return (
        <div className="h-full flex items-center justify-center p-4 text-sm text-[var(--text-secondary)]">
          Select a run to view details
        </div>
      )
    }
    return null
  }

  const shellClass = inline
    ? 'h-full flex flex-col min-h-0'
    : 'fixed inset-0 bg-black/60 z-50 flex items-center justify-center p-4'

  const panelClass = inline
    ? 'h-full flex flex-col min-h-0'
    : 'bg-[var(--bg-secondary)] border border-[var(--border)] rounded-lg w-[min(960px,95vw)] h-[min(820px,92vh)] flex flex-col'

  if (listOnly && !inline) {
    return (
      <div className={shellClass}>
        <div className="bg-[var(--bg-secondary)] border border-[var(--border)] rounded-lg w-[min(640px,95vw)] max-h-[85vh] flex flex-col">
          <div className="flex items-center justify-between p-4 border-b border-[var(--border)]">
            <h2 className="text-lg font-medium">All runs</h2>
            <button type="button" className="p-1 hover:bg-[var(--bg-tertiary)] rounded" onClick={onClose}>
              <X size={18} />
            </button>
          </div>
          <div className="overflow-auto p-3 space-y-1">
            {runs.map((run) => (
              <button
                key={run.id}
                type="button"
                className="w-full text-left px-3 py-2 rounded hover:bg-[var(--bg-tertiary)] border border-[var(--border)]"
                onClick={() => {
                  setListOnly(false)
                  onRunChange?.(run.id)
                }}
              >
                <div className="flex items-center gap-2 flex-wrap text-sm">
                  <span className={`px-1.5 py-0.5 rounded text-xs ${runStatusBadgeClass(run.status)}`}>
                    {runStatusLabel(run.status)}
                  </span>
                  <span className="truncate flex-1 min-w-0" title={runDisplayLabel(run)}>
                    {runDisplayLabel(run)}
                  </span>
                  {run.current_stage && <span className="text-[var(--text-secondary)] shrink-0">{run.current_stage}</span>}
                </div>
              </button>
            ))}
          </div>
        </div>
      </div>
    )
  }

  const status = detail?.status || 'pending'
  const snapshotCount = detail?.promote_snapshot?.paths?.length || 0
  const awaitingClarification = status === 'awaiting_clarification'

  const detailBody = (
    <>
          <div className={`flex items-start justify-between gap-3 shrink-0 ${inline ? 'p-3 border-b border-[var(--border)]' : 'p-4 border-b border-[var(--border)]'}`}>
            <div className="min-w-0">
              <h2 className="text-lg font-medium truncate" title={detail ? runDisplayLabel({ id: runId || '', display_name: detail.display_name }) : undefined}>
                {detail ? runDisplayLabel({ id: runId || '', display_name: detail.display_name }) : 'Run details'}
              </h2>
              {runId && (
                <div className="flex items-center gap-2 mt-1 flex-wrap">
                  <code className="text-xs font-mono truncate max-w-full">{runId}</code>
                  <Button variant="ghost" className="text-xs h-6" onClick={copyRunId}>Copy ID</Button>
                  <span className={`text-xs px-2 py-0.5 rounded ${runStatusBadgeClass(status)}`}>
                    {runStatusLabel(status)}
                  </span>
                </div>
              )}
              {detail && (
                <p className="text-xs text-[var(--text-secondary)] mt-1">
                  Created {new Date(detail.created_at).toLocaleString()}
                  {' · '}
                  Updated {new Date(detail.updated_at).toLocaleString()}
                  {detail.review_attempts > 0 && ` · Review attempts: ${detail.review_attempts}`}
                </p>
              )}
              {detail?.error_message && (
                <p className="text-xs text-[var(--error)] mt-1">{detail.error_message}</p>
              )}
              {detail?.failure_class && (
                <p className="text-xs text-[var(--text-secondary)] mt-1">
                  Failure class: {detail.failure_class}
                  {detail.recovery_status ? ` · Recovery: ${detail.recovery_status}` : ''}
                </p>
              )}
              {detail?.approval_override && (
                <p className="text-xs text-[var(--warning)] mt-1">Approved with readiness warnings.</p>
              )}
            </div>
            {!inline && (
              <button type="button" className="p-1 hover:bg-[var(--bg-tertiary)] rounded shrink-0" onClick={onClose}>
                <X size={18} />
              </button>
            )}
          </div>

          <div className={`flex gap-1 pt-2 border-b border-[var(--border)] shrink-0 ${inline ? 'px-3' : 'px-4'}`}>
            <button
              type="button"
              className={`text-xs px-3 py-1.5 rounded-t border-b-2 -mb-px ${
                activeTab === 'conversation'
                  ? 'border-[var(--accent)] text-[var(--text-primary)]'
                  : 'border-transparent text-[var(--text-secondary)] hover:text-[var(--text-primary)]'
              }`}
              onClick={() => setActiveTab('conversation')}
            >
              Conversation
            </button>
            <button
              type="button"
              className={`text-xs px-3 py-1.5 rounded-t border-b-2 -mb-px ${
                activeTab === 'pipeline'
                  ? 'border-[var(--accent)] text-[var(--text-primary)]'
                  : 'border-transparent text-[var(--text-secondary)] hover:text-[var(--text-primary)]'
              }`}
              onClick={() => setActiveTab('pipeline')}
            >
              Pipeline
            </button>
            {awaitingClarification && activeTab === 'pipeline' && (
              <button
                type="button"
                className="ml-auto text-xs text-[var(--warning)] hover:underline"
                onClick={() => setActiveTab('conversation')}
              >
                Answer clarification →
              </button>
            )}
          </div>

          {loading && !detail ? (
            <p className={`text-sm text-[var(--text-secondary)] ${inline ? 'p-3' : 'p-4'}`}>Loading run…</p>
          ) : (
            <div className="flex-1 min-h-0 flex flex-col">
              <div className={`flex-1 min-h-0 overflow-auto ${inline ? 'p-3' : 'p-4'}`}>
                {activeTab === 'conversation' ? (
                  <RunConversationPanel
                    detail={detail}
                    thread={thread}
                    loading={threadLoading || loading}
                  />
                ) : (
                  <div className="space-y-4">
                    <PipelineTimeline events={events} />

                    <button
                      type="button"
                      className="text-xs text-[var(--accent)] hover:underline"
                      onClick={() => {
                        if (runId) {
                          useUIStore.getState().setRightPanelTab('agents')
                          useUIStore.getState().requestOpenRunDrawer(runId, 'conversation')
                        }
                      }}
                    >
                      Open in Agents for pipeline actions →
                    </button>

                    {reviewArtifact && (
                      <div className="border border-[var(--border)] rounded p-3">
                        <p className="text-xs text-[var(--text-secondary)] mb-2 uppercase tracking-wide">Review</p>
                        <ReviewArtifactPanel
                          artifact={reviewArtifact}
                          runId={runId}
                          artifacts={artifacts}
                          busy={busy}
                          retryDisabled={!isRetryableStatus(status)}
                          onRetryWithFeedback={handleRetry}
                        />
                      </div>
                    )}

                    {(detail?.deliverable_kind || clarificationWarnings.length > 0 || (detail?.expected_targets?.length || 0) > 0) && (
                      <div className="border border-[var(--border)] rounded p-3 space-y-3">
                        <p className="text-xs text-[var(--text-secondary)] uppercase tracking-wide">Run intent and readiness</p>
                        <div className="grid gap-3 md:grid-cols-3 text-xs">
                          <div>
                            <p className="text-[var(--text-secondary)] mb-1">Requested intent</p>
                            <p>{detail?.deliverable_kind || 'unknown'}</p>
                          </div>
                          <div>
                            <p className="text-[var(--text-secondary)] mb-1">Expected targets</p>
                            <p>{detail?.expected_targets?.join(', ') || 'none'}</p>
                          </div>
                          <div>
                            <p className="text-[var(--text-secondary)] mb-1">Validation family</p>
                            <p>{detail?.expected_validation_family || 'unknown'}</p>
                          </div>
                        </div>
                        {!!clarificationWarnings.length && (
                          <div className="border border-[var(--warning)]/40 rounded p-3 bg-[var(--warning)]/8">
                            <p className="text-xs text-[var(--warning)] mb-2">Warnings</p>
                            <ul className="text-xs space-y-1">
                              {clarificationWarnings.map((warning) => (
                                <li key={warning}>• {warning}</li>
                              ))}
                            </ul>
                          </div>
                        )}
                        {awaitingClarification && (
                          <p className="text-xs text-[var(--text-secondary)]">
                            Clarification is required — switch to the{' '}
                            <button type="button" className="text-[var(--accent)] hover:underline" onClick={() => setActiveTab('conversation')}>
                              Conversation
                            </button>
                            {' '}tab to answer.
                          </p>
                        )}
                      </div>
                    )}

                    {(resolvedVisualEvidence || needsBrowserClient || deploymentGates.some((g) => g.id === 'visual_evidence' && g.required)) && runId && (
                      <div className="border border-[var(--border)] rounded p-3">
                        <p className="text-xs text-[var(--text-secondary)] mb-2 uppercase tracking-wide">
                          Visual testing
                        </p>
                        <VisualEvidencePanel
                          runId={runId}
                          evidence={resolvedVisualEvidence}
                          showActions={needsBrowserClient}
                          onContinueVisual={handleContinueVisual}
                          continueBusy={busy}
                        />
                      </div>
                    )}

                    {deploymentGates.length > 0 && (
                      <div className="border border-[var(--border)] rounded p-3">
                        <p className="text-xs text-[var(--text-secondary)] mb-2 uppercase tracking-wide">
                          Deployment gates
                        </p>
                        <ul className="text-xs space-y-1">
                          {deploymentGates.filter((g) => g.required).map((g) => (
                            <li key={g.id} className={g.passed ? 'text-[var(--success)]' : 'text-[var(--error)]'}>
                              {g.passed ? '✓' : '✗'} {g.label}
                              {!g.passed && g.detail ? ` — ${g.detail}` : ''}
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}

                    <RunLogPanel events={events} />

                    {(postmortem || projectLessons.length > 0 || globalSkills.length > 0) && (
                      <div className="grid gap-3 lg:grid-cols-3">
                        <div className="border border-[var(--border)] rounded p-3">
                          <p className="text-xs text-[var(--text-secondary)] mb-2 uppercase tracking-wide">Postmortem</p>
                          {postmortem ? (
                            <div className="space-y-2 text-xs">
                              <p className="font-medium">{postmortem.content.root_cause_summary}</p>
                              <p className="text-[var(--text-secondary)]">{postmortem.content.fix_recommendation}</p>
                              <p className="text-[var(--text-secondary)]">
                                Symptom: {postmortem.content.operator_visible_symptom}
                              </p>
                            </div>
                          ) : (
                            <p className="text-xs text-[var(--text-secondary)]">No postmortem for this run.</p>
                          )}
                        </div>

                        <div className="border border-[var(--border)] rounded p-3">
                          <p className="text-xs text-[var(--text-secondary)] mb-2 uppercase tracking-wide">Project Lessons</p>
                          <div className="space-y-2 text-xs">
                            {projectLessons.length === 0 ? (
                              <p className="text-[var(--text-secondary)]">No project lessons available.</p>
                            ) : (
                              projectLessons.slice(0, 3).map((lesson) => (
                                <div key={lesson.id}>
                                  <p className="font-medium">{lesson.title}</p>
                                  <p className="text-[var(--text-secondary)]">{lesson.content.guidance || lesson.content.summary}</p>
                                </div>
                              ))
                            )}
                          </div>
                        </div>

                        <div className="border border-[var(--border)] rounded p-3">
                          <p className="text-xs text-[var(--text-secondary)] mb-2 uppercase tracking-wide">Global Skills</p>
                          <div className="space-y-2 text-xs">
                            {globalSkills.length === 0 ? (
                              <p className="text-[var(--text-secondary)]">No global skills available.</p>
                            ) : (
                              globalSkills.slice(0, 3).map((skill) => (
                                <div key={skill.id}>
                                  <p className="font-medium">{skill.name}</p>
                                  <p className="text-[var(--text-secondary)]">{skill.summary}</p>
                                </div>
                              ))
                            )}
                          </div>
                        </div>
                      </div>
                    )}

                    <ArtifactViewer
                      artifacts={artifacts}
                      loading={loading}
                      runId={runId}
                      onRetryWithFeedback={handleRetry}
                      retryBusy={busy}
                    />
                  </div>
                )}
              </div>

              {runId && !inline && (
                <RunComposer
                  status={status}
                  busy={busy}
                  onClarify={handleClarify}
                  onRetry={handleRetry}
                  onOpenChat={detail?.chat_session_id ? handleOpenChat : undefined}
                  onApprove={() => setShowApprove(true)}
                />
              )}
            </div>
          )}
    </>
  )

  return (
    <>
      <div className={shellClass}>
        <div className={panelClass}>
          {detailBody}
        </div>
      </div>

      {showApprove && runId && projectId && !inline && (
        <ApproveDialog
          runId={runId}
          projectId={projectId}
          artifacts={artifacts}
          onClose={() => setShowApprove(false)}
          onApproved={() => {
            setRunStatus('completed')
            void hydrateRun(runId, true)
          }}
        />
      )}

      {confirmRollback && (
        <div className="fixed inset-0 bg-black/70 z-[60] flex items-center justify-center p-4">
          <div className="bg-[var(--bg-secondary)] border border-[var(--border)] rounded-lg p-4 w-96">
            <p className="text-sm font-medium mb-2">
              {confirmRollback === 'workspace'
                ? 'Discard workspace changes?'
                : 'Undo promotion?'}
            </p>
            <p className="text-xs text-[var(--text-secondary)] mb-4">
              {confirmRollback === 'workspace'
                ? 'This resets the run workspace from your project source. You will need to re-run the pipeline.'
                : `This restores ${snapshotCount} file(s) in your project source to their pre-promotion state.`}
            </p>
            <div className="flex gap-2 justify-end">
              <Button variant="secondary" onClick={() => setConfirmRollback(null)}>Cancel</Button>
              <Button
                variant="danger"
                loading={busy}
                onClick={() => void (
                  confirmRollback === 'workspace'
                    ? handleRollbackWorkspace()
                    : handleRollbackPromote()
                )}
              >
                Confirm
              </Button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
