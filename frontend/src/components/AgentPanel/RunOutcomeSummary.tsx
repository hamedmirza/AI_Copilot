import {
  runDisplayLabel,
  runStatusBadgeClass,
  runStatusLabel,
  type RunDetail,
} from '@/types/runs'

function formatDuration(ms: number): string {
  const totalSec = Math.floor(ms / 1000)
  const min = Math.floor(totalSec / 60)
  const sec = totalSec % 60
  if (min > 0) return `${min}m ${sec}s`
  return `${sec}s`
}

interface RunOutcomeSummaryProps {
  detail: RunDetail | null
  status: string
  elapsedMs: number
  runId: string
  displayName?: string | null
  onOpenConversation?: () => void
  onRetry?: () => void
  className?: string
}

export function RunOutcomeSummary({
  detail,
  status,
  elapsedMs,
  runId,
  displayName,
  onOpenConversation,
  onRetry,
  className = '',
}: RunOutcomeSummaryProps) {
  const title = runDisplayLabel({ id: runId, display_name: displayName ?? detail?.display_name })
  const failureClass = detail?.failure_class || detail?.primary_failure_class

  return (
    <div className={`rounded border border-[var(--border)] bg-[var(--bg-tertiary)] p-3 text-xs space-y-2 ${className}`}>
      <div className="flex flex-wrap items-center gap-2">
        <p className="font-medium text-sm text-[var(--text-primary)] truncate flex-1" title={title}>
          {title}
        </p>
        <span className={`shrink-0 rounded px-1.5 py-0.5 text-[10px] uppercase ${runStatusBadgeClass(status)}`}>
          {runStatusLabel(status)}
        </span>
      </div>
      <p className="text-[var(--text-secondary)]">
        Duration {formatDuration(elapsedMs)}
        {detail?.current_stage ? ` · last stage ${detail.current_stage}` : ''}
      </p>
      {failureClass && (
        <p className="text-[var(--warning)]">Failure class: {failureClass}</p>
      )}
      {detail?.error_message && (
        <p className="text-[var(--error)] line-clamp-3">{detail.error_message}</p>
      )}
      <div className="flex flex-wrap gap-2 pt-1">
        {onOpenConversation && detail?.chat_session_id && (
          <button
            type="button"
            className="text-[var(--accent)] hover:underline"
            onClick={onOpenConversation}
          >
            View conversation
          </button>
        )}
        {onRetry && (
          <button
            type="button"
            className="text-[var(--accent)] hover:underline"
            onClick={onRetry}
          >
            Retry pipeline
          </button>
        )}
      </div>
    </div>
  )
}
