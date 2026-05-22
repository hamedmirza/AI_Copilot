import { useCallback, useEffect, useMemo, useState } from 'react'
import { X } from 'lucide-react'
import { api } from '@/api/client'
import { useRunDetail } from '@/hooks/useRunDetail'
import { stageStatusFromEvents } from '@/lib/runEvents'
import { showError, showSuccess } from '@/lib/toast'
import { Button } from '@/components/ui/primitives'
import { STAGES } from '@/components/Chat/types'
import {
  canRollbackPromote,
  canRollbackWorkspace,
  isRetryableStatus,
  latestReviewArtifact,
  runStatusBadgeClass,
  runStatusLabel,
  type RunSummary,
} from '@/types/runs'
import { useProjectStore, useRunStore } from '@/store'
import { ArtifactViewer } from './ArtifactViewer'
import { ApproveDialog } from './ApproveDialog'
import { ReviewArtifactPanel } from './ReviewArtifactPanel'
import { RunLogPanel } from '@/components/shared/RunLogPanel'

type DrawerMode = 'detail' | 'list'

interface RunDetailDrawerProps {
  open: boolean
  runId: string | null
  runs: RunSummary[]
  mode?: DrawerMode
  onClose: () => void
  onRunChange?: (runId: string) => void
}

export function RunDetailDrawer({
  open,
  runId,
  runs,
  mode = 'detail',
  onClose,
  onRunChange,
}: RunDetailDrawerProps) {
  const projectId = useProjectStore((s) => s.currentProjectId)
  const setRunStatus = useRunStore((s) => s.setRunStatus)
  const { detail, events, artifacts, loading, hydrateRun } = useRunDetail()
  const [listOnly, setListOnly] = useState(mode === 'list')
  const [showApprove, setShowApprove] = useState(false)
  const [busy, setBusy] = useState(false)
  const [confirmRollback, setConfirmRollback] = useState<'workspace' | 'promote' | null>(null)

  useEffect(() => {
    setListOnly(mode === 'list')
  }, [mode, open])

  useEffect(() => {
    if (!open || !runId || listOnly) return
    void hydrateRun(runId, true)
  }, [open, runId, listOnly, hydrateRun])

  const reviewArtifact = useMemo(() => latestReviewArtifact(artifacts), [artifacts])

  const handleRetry = useCallback(async (feedback = '') => {
    if (!runId) return
    setBusy(true)
    try {
      await api.runs.retry(runId, feedback ? { feedback } : undefined)
      setRunStatus('running')
      showSuccess('Pipeline retry started')
      await hydrateRun(runId, true)
    } catch (e) {
      showError(e)
    } finally {
      setBusy(false)
    }
  }, [hydrateRun, runId, setRunStatus])

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

  if (!open) return null

  if (listOnly) {
    return (
      <div className="fixed inset-0 bg-black/60 z-50 flex items-center justify-center p-4">
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
                  <span className="font-mono text-xs">{run.id}</span>
                  {run.current_stage && <span className="text-[var(--text-secondary)]">{run.current_stage}</span>}
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

  return (
    <>
      <div className="fixed inset-0 bg-black/60 z-50 flex items-center justify-center p-4">
        <div className="bg-[var(--bg-secondary)] border border-[var(--border)] rounded-lg w-[min(960px,95vw)] h-[min(820px,92vh)] flex flex-col">
          <div className="flex items-start justify-between gap-3 p-4 border-b border-[var(--border)] shrink-0">
            <div className="min-w-0">
              <h2 className="text-lg font-medium">Run details</h2>
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
            </div>
            <button type="button" className="p-1 hover:bg-[var(--bg-tertiary)] rounded shrink-0" onClick={onClose}>
              <X size={18} />
            </button>
          </div>

          {loading && !detail ? (
            <p className="p-4 text-sm text-[var(--text-secondary)]">Loading run…</p>
          ) : (
            <div className="flex-1 min-h-0 overflow-auto p-4 space-y-4">
              <div className="flex gap-1 flex-wrap">
                {STAGES.map((stage) => {
                  const st = stageStatusFromEvents(events, stage)
                  return (
                    <div key={stage} className="flex items-center gap-1 text-xs px-2 py-1 bg-[var(--bg-tertiary)] rounded">
                      <span className={`w-2 h-2 rounded-full ${
                        st === 'done' ? 'bg-[var(--success)]' :
                        st === 'running' ? 'bg-[var(--accent)] animate-pulse' :
                        st === 'failed' ? 'bg-[var(--error)]' : 'bg-gray-500'
                      }`} />
                      {stage}
                    </div>
                  )
                })}
              </div>

              <div className="flex flex-wrap gap-2">
                <Button
                  disabled={status !== 'awaiting_approval' || busy}
                  onClick={() => setShowApprove(true)}
                >
                  Approve
                </Button>
                <Button
                  variant="secondary"
                  disabled={!isRetryableStatus(status) || busy}
                  onClick={() => void handleRetry()}
                >
                  Retry pipeline
                </Button>
                {canRollbackWorkspace(status) && (
                  <Button
                    variant="secondary"
                    disabled={busy}
                    onClick={() => setConfirmRollback('workspace')}
                  >
                    Discard workspace changes
                  </Button>
                )}
                {canRollbackPromote(status, detail?.promote_snapshot) && (
                  <Button
                    variant="danger"
                    disabled={busy}
                    onClick={() => setConfirmRollback('promote')}
                  >
                    Undo promotion
                  </Button>
                )}
              </div>

              {reviewArtifact && (
                <div className="border border-[var(--border)] rounded p-3">
                  <p className="text-xs text-[var(--text-secondary)] mb-2 uppercase tracking-wide">Review</p>
                  <ReviewArtifactPanel
                    artifact={reviewArtifact}
                    busy={busy}
                    onRetryWithFeedback={handleRetry}
                  />
                </div>
              )}

              <RunLogPanel events={events} />

              <ArtifactViewer
                artifacts={artifacts}
                loading={loading}
                onRetryWithFeedback={handleRetry}
                retryBusy={busy}
              />
            </div>
          )}
        </div>
      </div>

      {showApprove && runId && projectId && (
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
