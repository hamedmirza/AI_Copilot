import { useCallback, useEffect, useMemo, useState } from 'react'
import { api } from '@/api/client'
import { ReviewArtifactPanel } from '@/components/AgentPanel/ReviewArtifactPanel'
import { runStatusFromEvents } from '@/lib/runEvents'
import { Button } from '@/components/ui/primitives'
import {
  isRetryableStatus,
  latestReviewArtifact,
  parseReviewContent,
  type RunArtifact,
} from '@/types/runs'
import type { RunEvent } from '@/store'
import { useChatStore } from '@/store'

interface RunFollowUpCardProps {
  runId: string
  events: RunEvent[]
  runStatus?: string
  busy?: boolean
  onRetry: (runId: string, feedback?: string) => void | Promise<void>
}

const ACTIONABLE_STATUSES = new Set([
  'awaiting_approval',
  'changes_requested',
  'blocked',
  'failed',
  'completed',
])

export function RunFollowUpCard({ runId, events, runStatus, busy, onRetry }: RunFollowUpCardProps) {
  const setPendingRunId = useChatStore((s) => s.setPendingRunId)
  const setComposerPrefill = useChatStore((s) => s.setComposerPrefill)
  const [artifacts, setArtifacts] = useState<RunArtifact[]>([])
  const [loading, setLoading] = useState(false)
  const [expanded, setExpanded] = useState(false)

  const status = runStatus || runStatusFromEvents(
    events.map((e) => ({ ...e, type: String(e.type || '') })),
    'running',
  )
  const showCard = ACTIONABLE_STATUSES.has(status)

  useEffect(() => {
    if (!showCard) return
    setLoading(true)
    api.runs.artifacts(runId)
      .then((rows) => setArtifacts(rows as RunArtifact[]))
      .catch(() => setArtifacts([]))
      .finally(() => setLoading(false))
  }, [runId, showCard])

  const reviewArtifact = useMemo(() => latestReviewArtifact(artifacts), [artifacts])
  const review = useMemo(
    () => (reviewArtifact ? parseReviewContent(reviewArtifact.content) : null),
    [reviewArtifact],
  )

  const topSuggestions = useMemo(() => (review?.suggestions || []).slice(0, 3), [review])

  const discussInChat = useCallback((text: string) => {
    const prompt = `Please address run ${runId}:\n\n${text}`
    setComposerPrefill(prompt)
    setPendingRunId(runId)
  }, [runId, setComposerPrefill, setPendingRunId])

  if (!showCard) return null

  return (
    <div className="mt-3 border border-[var(--border)] rounded-md p-3 bg-black/20 space-y-3">
      <p className="text-xs font-medium uppercase tracking-wide text-[var(--text-secondary)]">
        Suggested next steps
      </p>

      {loading && <p className="text-xs text-[var(--text-secondary)]">Loading review…</p>}

      {!loading && topSuggestions.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {topSuggestions.map((suggestion) => (
            <button
              key={suggestion}
              type="button"
              className="text-xs px-2 py-1 rounded-full border border-[var(--border)] hover:bg-[var(--bg-tertiary)] max-w-full truncate"
              title={suggestion}
              onClick={() => discussInChat(suggestion)}
            >
              {suggestion.length > 48 ? `${suggestion.slice(0, 48)}…` : suggestion}
            </button>
          ))}
          {(review?.suggestions?.length || 0) > 3 && (
            <Button variant="ghost" className="text-xs h-7" onClick={() => setExpanded(!expanded)}>
              {expanded ? 'Show less' : 'Show all'}
            </Button>
          )}
        </div>
      )}

      {expanded && reviewArtifact && (
        <ReviewArtifactPanel
          artifact={reviewArtifact}
          compact
          runId={runId}
          artifacts={artifacts}
          busy={busy}
          retryDisabled={!isRetryableStatus(status)}
          onRetryWithFeedback={(feedback) => onRetry(runId, feedback)}
        />
      )}

      <div className="flex flex-wrap gap-2">
        {topSuggestions[0] && (
          <Button
            variant="secondary"
            className="text-xs"
            disabled={busy || !isRetryableStatus(status)}
            onClick={() => void onRetry(runId, topSuggestions[0])}
          >
            Retry with this
          </Button>
        )}
        <Button
          variant="ghost"
          className="text-xs"
          onClick={() => discussInChat(review?.summary || 'Please review the pipeline output.')}
        >
          Discuss in chat
        </Button>
      </div>

      {!isRetryableStatus(status) && status === 'awaiting_approval' && (
        <p className="text-[11px] text-[var(--text-secondary)]">Approve or reject from the run card above.</p>
      )}
    </div>
  )
}
