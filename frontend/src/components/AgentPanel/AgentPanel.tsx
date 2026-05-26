import { useCallback, useEffect, useMemo, useState } from 'react'
import { ChevronDown, ChevronRight } from 'lucide-react'
import { api } from '@/api/client'
import { useRunDetail } from '@/hooks/useRunDetail'
import { useRunLive } from '@/hooks/useRunLive'
import { formatElementForAgentTask } from '@/lib/pageElementContext'
import { isActiveRunStatus, shouldRefreshRunThread } from '@/lib/runEvents'
import { useEditorStore, useProjectStore, useRunStore, useUIStore } from '@/store'
import { showError, showSuccess } from '@/lib/toast'
import { Button, EmptyState, Skeleton } from '@/components/ui/primitives'
import { RejectReasonDialog } from '@/components/ui/RejectReasonDialog'
import type { FailureSummaryResponse, GlobalSkillRecord, ImprovementRecord, LessonRecord } from '@/types/runs'
import { isRetryableStatus } from '@/types/runs'
import { AgentPanelLayoutToggle } from './AgentPanelLayoutToggle'
import { ApproveDialog } from './ApproveDialog'
import { ArtifactViewer } from './ArtifactViewer'
import { PipelineTimeline } from './PipelineTimeline'
import { RunActionBar } from './RunActionBar'
import { RunComposer } from './RunComposer'
import { RunConversationPanel } from './RunConversationPanel'
import { RunProgressCard } from './RunProgressCard'

const ACTIVE_RUN_STATUSES = new Set([
  'pending',
  'running',
  'awaiting_clarification',
  'awaiting_approval',
  'blocked',
])

function improvementEvidenceLine(improvement: ImprovementRecord): string {
  const baselineSize = Number(improvement.baseline_metrics?.sample_size ?? 0)
  const trialSize = Number(improvement.trial_metrics?.sample_size ?? 0)
  if (trialSize <= 0 && Number(improvement.exposure_count ?? 0) <= 0) {
    if (baselineSize > 0) {
      return `Awaiting comparable trial runs. Baseline cohort: ${baselineSize} run${baselineSize === 1 ? '' : 's'}.`
    }
    return 'Awaiting comparable trial runs.'
  }
  const delta = Number(improvement.decision_metadata?.success_rate_delta_pct ?? 0)
  return `Baseline ${improvement.baseline_metrics?.success_rate ?? 0}% → Trial ${improvement.trial_metrics?.success_rate ?? 0}% (${delta >= 0 ? '+' : ''}${delta}%)`
}

type AgentTab = 'conversation' | 'artifacts' | 'learn'

export function AgentPanel() {
  const projectId = useProjectStore((s) => s.currentProjectId)
  const pageElementSelection = useUIStore((s) => s.pageElementSelection)
  const setPageElementSelection = useUIStore((s) => s.setPageElementSelection)
  const runDrawerRequest = useUIStore((s) => s.runDrawerRequest)
  const clearRunDrawerRequest = useUIStore((s) => s.clearRunDrawerRequest)
  const rightPanelTab = useUIStore((s) => s.rightPanelTab)
  const { currentRunId, runStatus, setCurrentRun, setRunStatus, setRuns } = useRunStore()
  const {
    detail,
    artifacts,
    thread,
    threadLoading,
    loading: detailLoading,
    hydrateRun,
    refreshThread,
  } = useRunDetail()
  const runLive = useRunLive(currentRunId, { syncPanel: true, enabled: Boolean(currentRunId) })
  const {
    events: liveEvents,
    status: liveStatus,
    currentStage,
    detail: liveDetail,
    elapsedMs: liveElapsedMs,
    latestActivityLine: liveLatestActivityLine,
  } = runLive
  const [description, setDescription] = useState('')
  const [validationProfile, setValidationProfile] = useState('python')
  const [allowWebSearch, setAllowWebSearch] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [descError, setDescError] = useState('')
  const [newRunExpanded, setNewRunExpanded] = useState(true)
  const [showReject, setShowReject] = useState(false)
  const [showApprove, setShowApprove] = useState(false)
  const [actionBusy, setActionBusy] = useState(false)
  const [loading, setLoading] = useState(false)
  const [activeTab, setActiveTab] = useState<AgentTab>('conversation')
  const [failureSummary, setFailureSummary] = useState<FailureSummaryResponse | null>(null)
  const [projectLessons, setProjectLessons] = useState<LessonRecord[]>([])
  const [globalSkills, setGlobalSkills] = useState<GlobalSkillRecord[]>([])
  const [improvements, setImprovements] = useState<ImprovementRecord[]>([])
  const [learningBusy, setLearningBusy] = useState(false)

  const normalizedEvents = useMemo(
    () => liveEvents,
    [liveEvents],
  )

  const effectiveStatus = liveStatus || runStatus
  const runActive = ACTIVE_RUN_STATUSES.has(effectiveStatus) || isActiveRunStatus(effectiveStatus)

  const loadRuns = useCallback(async () => {
    if (!projectId) {
      setRuns([])
      setCurrentRun(null)
      setRunStatus('idle')
      return
    }
    setLoading(true)
    try {
      const data = await api.projects.runs(projectId)
      const nextRuns = data as Array<Record<string, unknown>>
      setRuns(nextRuns)
      const awaitingApproval = nextRuns.find((run) => String(run.status) === 'awaiting_approval')
      const activeRun = nextRuns.find((run) => String(run.id) === currentRunId)
      const fallbackRun = awaitingApproval || activeRun || nextRuns[0]
      if (!fallbackRun) {
        setCurrentRun(null)
        setRunStatus('idle')
        return
      }
      if (String(fallbackRun.id) !== currentRunId) {
        await hydrateRun(String(fallbackRun.id), true)
      }
    } catch (e) {
      showError(e)
    } finally {
      setLoading(false)
    }
  }, [currentRunId, hydrateRun, projectId, setCurrentRun, setRunStatus, setRuns])

  const loadLearning = useCallback(async () => {
    if (!projectId) {
      setFailureSummary(null)
      setProjectLessons([])
      setGlobalSkills([])
      setImprovements([])
      return
    }
    setLearningBusy(true)
    try {
      const [summary, lessons, skills, nextImprovements] = await Promise.all([
        api.runs.failureSummary(projectId) as Promise<FailureSummaryResponse>,
        api.projects.lessons(projectId) as Promise<LessonRecord[]>,
        api.skills.listGlobal() as Promise<GlobalSkillRecord[]>,
        api.projects.improvements(projectId) as Promise<ImprovementRecord[]>,
      ])
      setFailureSummary(summary)
      setProjectLessons(lessons)
      setGlobalSkills(skills)
      setImprovements(nextImprovements)
    } catch (e) {
      showError(e)
    } finally {
      setLearningBusy(false)
    }
  }, [projectId])

  useEffect(() => { void loadRuns() }, [loadRuns])
  useEffect(() => { void loadLearning() }, [loadLearning])

  useEffect(() => {
    if (!currentRunId) return
    void hydrateRun(currentRunId, true)
  }, [currentRunId, hydrateRun])

  useEffect(() => {
    if (runActive) setNewRunExpanded(false)
  }, [runActive])

  useEffect(() => {
    if (!runDrawerRequest || rightPanelTab !== 'agents') return
    void hydrateRun(runDrawerRequest.runId, true)
    if (runDrawerRequest.tab === 'pipeline') {
      setActiveTab('artifacts')
    } else {
      setActiveTab('conversation')
    }
    clearRunDrawerRequest()
  }, [runDrawerRequest, rightPanelTab, clearRunDrawerRequest, hydrateRun])

  const bumpTreeRefresh = useEditorStore((s) => s.bumpTreeRefresh)

  useEffect(() => {
    if (!currentRunId || liveEvents.length === 0) return
    const last = liveEvents[liveEvents.length - 1]
    const type = String(last.type || '')
    if (shouldRefreshRunThread(type)) {
      void refreshThread(currentRunId)
    }
    if (['run_completed', 'code_patch_applied', 'awaiting_approval'].includes(type)) {
      window.setTimeout(() => bumpTreeRefresh(), 3000)
      void loadRuns()
    }
  }, [bumpTreeRefresh, currentRunId, liveEvents, loadRuns, refreshThread])

  const handleRetryWithFeedback = useCallback(async (feedback: string) => {
    if (!currentRunId) return
    setActionBusy(true)
    try {
      await api.runs.retry(currentRunId, feedback ? { feedback } : undefined)
      setRunStatus('running')
      showSuccess('Retrying pipeline')
      await hydrateRun(currentRunId, true)
      await refreshThread(currentRunId)
      await loadLearning()
    } catch (e) {
      showError(e)
    } finally {
      setActionBusy(false)
    }
  }, [currentRunId, hydrateRun, loadLearning, refreshThread, setRunStatus])

  const handleClarify = useCallback(async (answer: string) => {
    if (!currentRunId) return
    setActionBusy(true)
    try {
      await api.runs.clarify(currentRunId, answer)
      setRunStatus('running')
      showSuccess('Clarification sent')
      await hydrateRun(currentRunId, true)
      await refreshThread(currentRunId)
    } catch (e) {
      showError(e)
    } finally {
      setActionBusy(false)
    }
  }, [currentRunId, hydrateRun, refreshThread, setRunStatus])

  const handleContinueVisual = useCallback(async () => {
    if (!currentRunId) return
    setActionBusy(true)
    try {
      useUIStore.getState().setActiveCenterView('browser')
      await api.runs.continueVisual(currentRunId)
      showSuccess('Visual verification resumed')
      await hydrateRun(currentRunId, true)
    } catch (e) {
      showError(e)
    } finally {
      setActionBusy(false)
    }
  }, [currentRunId, hydrateRun])

  const handleResume = useCallback(async () => {
    if (!currentRunId) return
    setActionBusy(true)
    try {
      await api.runs.resume(currentRunId)
      setRunStatus('running')
      showSuccess('Run re-queued')
      await hydrateRun(currentRunId, true)
    } catch (e) {
      showError(e)
    } finally {
      setActionBusy(false)
    }
  }, [currentRunId, hydrateRun, setRunStatus])

  const handleReject = useCallback(async (reason: string) => {
    if (!currentRunId) return
    setActionBusy(true)
    try {
      await api.runs.reject(currentRunId, reason)
      showSuccess('Run rejected')
      setShowReject(false)
      await hydrateRun(currentRunId, true)
    } catch (e) {
      showError(e)
    } finally {
      setActionBusy(false)
    }
  }, [currentRunId, hydrateRun])

  const handlePromoteLesson = useCallback(async (lessonId: number) => {
    setLearningBusy(true)
    try {
      await api.lessons.promoteGlobal(lessonId)
      showSuccess('Lesson promoted to global skill')
      await loadLearning()
    } catch (e) {
      showError(e)
    } finally {
      setLearningBusy(false)
    }
  }, [loadLearning])

  const handleImprovementOverride = useCallback(async (improvementId: string, status: string, scope?: string) => {
    setLearningBusy(true)
    try {
      await api.improvements.override(improvementId, { status, scope })
      showSuccess(`Improvement marked ${status}`)
      await loadLearning()
    } catch (e) {
      showError(e)
    } finally {
      setLearningBusy(false)
    }
  }, [loadLearning])

  const submitTask = async () => {
    const taskBody = pageElementSelection
      ? formatElementForAgentTask(pageElementSelection, description)
      : description.trim()
    if (taskBody.length < 10) {
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
        description: taskBody,
        validation_profile: validationProfile,
        allow_web_search: allowWebSearch,
      }) as { run: { id: string; status: string } }
      setPageElementSelection(null)
      const run = result.run
      setCurrentRun(run.id)
      setRunStatus(run.status)
      setActiveTab('conversation')
      await hydrateRun(run.id, true)
      showSuccess('Task submitted')
      await loadRuns()
    } catch (e) {
      showError(e)
    } finally {
      setSubmitting(false)
    }
  }

  if (!projectId) {
    return <EmptyState title="No project" description="Select a project to run agent tasks" />
  }

  const displayName = detail?.display_name

  return (
    <div className="h-full flex flex-col overflow-hidden p-3">
      <div className="flex items-center justify-between gap-2 shrink-0 mb-2">
        <p className="text-xs uppercase tracking-wide text-[var(--text-secondary)]">Pipeline</p>
        <AgentPanelLayoutToggle compact />
      </div>

      {currentRunId ? (
        <div className="shrink-0 space-y-2 mb-2">
          <RunProgressCard
            runId={currentRunId}
            displayName={displayName}
            status={effectiveStatus}
            showViewLink={false}
            live={{
              events: liveEvents,
              detail: liveDetail,
              status: liveStatus,
              currentStage,
              elapsedMs: liveElapsedMs,
              latestActivityLine: liveLatestActivityLine,
            }}
          />
          <PipelineTimeline
            events={normalizedEvents}
            workflowStages={detail?.workflow_stages}
            compact
            activeStage={currentStage}
          />
          <RunActionBar
            status={effectiveStatus}
            busy={actionBusy}
            events={liveEvents}
            promoteSnapshot={detail?.promote_snapshot ?? null}
            onApprove={() => setShowApprove(true)}
            onReject={() => setShowReject(true)}
            onRetry={() => void handleRetryWithFeedback('')}
            onResume={() => void handleResume()}
            onContinueVisual={() => void handleContinueVisual()}
          />
        </div>
      ) : (
        <p className="text-xs text-[var(--text-secondary)] shrink-0 mb-2">No active run — start a task below.</p>
      )}

      <div className="shrink-0 border border-[var(--border)] rounded mb-2 overflow-hidden">
        <button
          type="button"
          className="w-full flex items-center gap-2 px-2 py-1.5 text-xs text-[var(--text-secondary)] hover:bg-[var(--bg-tertiary)]"
          onClick={() => setNewRunExpanded((v) => !v)}
        >
          {newRunExpanded ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
          <span className="font-medium text-[var(--text-primary)]">New run</span>
          {runActive && <span className="ml-auto text-[10px]">collapsed while run active</span>}
        </button>
        {newRunExpanded && (
          <div className="px-2 pb-2 border-t border-[var(--border)]">
            {pageElementSelection && (
              <div className="mb-2 mt-2 flex items-center gap-2 text-xs px-2 py-1.5 rounded border border-[var(--accent)]/40 bg-[var(--accent)]/10">
                <span className="text-[var(--accent)] truncate flex-1" title={pageElementSelection.selector}>
                  Attached: {pageElementSelection.tagName} · {pageElementSelection.selector}
                </span>
                <button
                  type="button"
                  className="text-[var(--text-secondary)] hover:text-white shrink-0"
                  onClick={() => setPageElementSelection(null)}
                >
                  Remove
                </button>
              </div>
            )}
            <textarea
              className="w-full h-20 mt-2 bg-[var(--bg-tertiary)] border border-[var(--border)] rounded p-2 text-sm resize-none"
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
              <label className="flex items-center gap-2 text-xs text-[var(--text-secondary)]">
                <input
                  type="checkbox"
                  className="rounded border-[var(--border)]"
                  checked={allowWebSearch}
                  onChange={(e) => setAllowWebSearch(e.target.checked)}
                />
                Web search
              </label>
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
        )}
      </div>

      <div className="flex gap-1 border-b border-[var(--border)] shrink-0 mb-2">
        {(['conversation', 'artifacts', 'learn'] as const).map((tab) => (
          <button
            key={tab}
            type="button"
            className={`text-xs px-3 py-1.5 rounded-t border-b-2 -mb-px capitalize ${
              activeTab === tab
                ? 'border-[var(--accent)] text-[var(--text-primary)]'
                : 'border-transparent text-[var(--text-secondary)] hover:text-[var(--text-primary)]'
            }`}
            onClick={() => setActiveTab(tab)}
          >
            {tab}
          </button>
        ))}
      </div>

      <div className="flex-1 min-h-0 overflow-auto">
        {activeTab === 'conversation' && (
          currentRunId ? (
            <RunConversationPanel
              detail={detail}
              thread={thread}
              loading={threadLoading || detailLoading || loading}
            />
          ) : (
            <EmptyState title="No runs yet" description="Submit a task to start the pipeline" />
          )
        )}

        {activeTab === 'artifacts' && (
          currentRunId ? (
            <ArtifactViewer
              artifacts={artifacts}
              loading={detailLoading}
              runId={currentRunId}
              onRetryWithFeedback={handleRetryWithFeedback}
              retryBusy={actionBusy}
              retryDisabled={!isRetryableStatus(runStatus)}
            />
          ) : (
            <EmptyState title="No artifacts" description="Artifacts appear after a run starts" />
          )
        )}

        {activeTab === 'learn' && (
          <div className="space-y-3 text-xs">
            <div>
              <p className="text-[var(--text-secondary)] mb-1 uppercase tracking-wide">Failed Run Recovery</p>
              {learningBusy && !failureSummary ? (
                <Skeleton className="h-14 w-full" />
              ) : !failureSummary || failureSummary.total_runs === 0 ? (
                <p className="text-[var(--text-secondary)]">No failed-run recovery backlog for this project.</p>
              ) : (
                <div className="space-y-1 max-h-32 overflow-auto">
                  {Object.entries(failureSummary.groups).map(([failureClass, group]) => (
                    <div key={failureClass} className="rounded border border-[var(--border)] px-2 py-1.5">
                      <div className="flex items-center justify-between gap-2">
                        <span className="font-medium">{failureClass.replaceAll('_', ' ')}</span>
                        <span className="text-[var(--text-secondary)]">{group.actionable}/{group.count} actionable</span>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>

            <div>
              <p className="text-[var(--text-secondary)] mb-1 uppercase tracking-wide">Improvements</p>
              {improvements.length === 0 ? (
                <p className="text-[var(--text-secondary)]">No structured improvements yet.</p>
              ) : (
                <div className="space-y-1 max-h-40 overflow-auto">
                  {improvements.slice(0, 8).map((improvement) => (
                    <div key={improvement.id} className="rounded border border-[var(--border)] px-2 py-1.5">
                      <div className="flex items-start justify-between gap-2">
                        <div className="min-w-0">
                          <p className="font-medium truncate">{improvement.display_title || improvement.title}</p>
                          <p className="text-[var(--text-secondary)] mt-0.5 line-clamp-2">
                            {improvement.content.summary || improvement.content.guidance || improvement.hypothesis}
                          </p>
                          <p className="text-[var(--text-secondary)] mt-0.5">{improvementEvidenceLine(improvement)}</p>
                        </div>
                        <div className="flex gap-1 shrink-0">
                          {improvement.status !== 'approved' && (
                            <Button
                              variant="ghost"
                              className="h-6 px-2 text-[10px]"
                              disabled={learningBusy}
                              onClick={() => void handleImprovementOverride(improvement.id, 'approved', 'global')}
                            >
                              Approve
                            </Button>
                          )}
                          {improvement.status !== 'deprecated' && (
                            <Button
                              variant="ghost"
                              className="h-6 px-2 text-[10px]"
                              disabled={learningBusy}
                              onClick={() => void handleImprovementOverride(improvement.id, 'deprecated')}
                            >
                              Deprecate
                            </Button>
                          )}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>

            <div>
              <p className="text-[var(--text-secondary)] mb-1 uppercase tracking-wide">Project Lessons</p>
              {projectLessons.length === 0 ? (
                <p className="text-[var(--text-secondary)]">No project lessons yet.</p>
              ) : (
                <div className="space-y-1 max-h-32 overflow-auto">
                  {projectLessons.slice(0, 6).map((lesson) => (
                    <div key={lesson.id} className="rounded border border-[var(--border)] px-2 py-1.5">
                      <div className="flex items-start justify-between gap-2">
                        <div className="min-w-0">
                          <p className="font-medium truncate">{lesson.title}</p>
                          <p className="text-[var(--text-secondary)] mt-0.5 line-clamp-2">
                            {lesson.content.summary || lesson.content.guidance || 'No summary'}
                          </p>
                        </div>
                        <Button
                          variant="ghost"
                          className="h-6 px-2 text-[10px]"
                          disabled={learningBusy}
                          onClick={() => void handlePromoteLesson(lesson.id)}
                        >
                          Promote
                        </Button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>

            <div>
              <p className="text-[var(--text-secondary)] mb-1 uppercase tracking-wide">Global Skills</p>
              {globalSkills.length === 0 ? (
                <p className="text-[var(--text-secondary)]">No global skills promoted yet.</p>
              ) : (
                <div className="space-y-1 max-h-32 overflow-auto">
                  {globalSkills.slice(0, 6).map((skill) => (
                    <div key={skill.id} className="rounded border border-[var(--border)] px-2 py-1.5">
                      <p className="font-medium truncate">{skill.name}</p>
                      <p className="text-[var(--text-secondary)] mt-0.5 line-clamp-2">{skill.summary}</p>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}
      </div>

      {currentRunId && (
        <RunComposer
          status={runStatus}
          busy={actionBusy}
          onClarify={handleClarify}
          onRetry={handleRetryWithFeedback}
        />
      )}

      {showApprove && currentRunId && projectId && (
        <ApproveDialog
          runId={currentRunId}
          projectId={projectId}
          artifacts={artifacts}
          onClose={() => setShowApprove(false)}
          onApproved={() => setRunStatus('completed')}
        />
      )}

      <RejectReasonDialog
        open={showReject}
        title="Reject run"
        placeholder="Reason for rejection (required)"
        onSubmit={(reason) => void handleReject(reason)}
        onCancel={() => setShowReject(false)}
      />
    </div>
  )
}
