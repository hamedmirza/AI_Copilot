import { Button } from '@/components/ui/primitives'
import {
  formatRunRelativeTime,
  runDisplayLabel,
  hasRecoveryMetadata,
  runStatusBadgeClass,
  runStatusLabel,
  type RunSummary,
} from '@/types/runs'

interface RunHistoryListProps {
  runs: RunSummary[]
  currentRunId: string | null
  maxRows?: number
  onSelect: (runId: string) => void
  onOpenDetails: (runId: string) => void
  onViewAll?: () => void
}

export function RunHistoryList({
  runs,
  currentRunId,
  maxRows = 5,
  onSelect,
  onOpenDetails,
  onViewAll,
}: RunHistoryListProps) {
  const visible = runs.slice(0, maxRows)
  const hasMore = runs.length > maxRows

  if (runs.length === 0) {
    return <p className="text-xs text-[var(--text-secondary)]">No runs yet</p>
  }

  return (
    <div className="space-y-1">
      {visible.map((run) => {
        const selected = currentRunId === run.id
        return (
          <div
            key={run.id}
            className={`flex items-center gap-2 text-xs px-2 py-1.5 rounded border ${
              selected
                ? 'border-[var(--accent)] bg-[var(--accent)]/10'
                : 'border-transparent hover:bg-[var(--bg-tertiary)]'
            }`}
          >
            <button
              type="button"
              className="flex-1 min-w-0 text-left"
              onClick={() => onSelect(run.id)}
            >
              <div className="flex items-center gap-2 flex-wrap">
                <span className={`px-1.5 py-0.5 rounded uppercase text-[10px] ${runStatusBadgeClass(run.status)}`}>
                  {runStatusLabel(run.status)}
                </span>
                {hasRecoveryMetadata(run) && (
                  <span className="text-[10px] text-[var(--text-secondary)] shrink-0" title="Recovery metadata present">
                    (R)
                  </span>
                )}
                <span className="flex-1 min-w-0 truncate">{runDisplayLabel(run)}</span>
                <span className="text-[var(--text-secondary)] shrink-0">{formatRunRelativeTime(run.created_at)}</span>
                {run.current_stage && (
                  <span className="text-[var(--text-secondary)] truncate shrink-0">{run.current_stage}</span>
                )}
              </div>
            </button>
            <Button
              variant="ghost"
              className="text-[10px] h-6 px-2 shrink-0"
              onClick={() => onOpenDetails(run.id)}
            >
              Details
            </Button>
          </div>
        )
      })}
      {hasMore && onViewAll && (
        <Button variant="ghost" className="text-xs w-full" onClick={onViewAll}>
          View all runs ({runs.length})
        </Button>
      )}
    </div>
  )
}
