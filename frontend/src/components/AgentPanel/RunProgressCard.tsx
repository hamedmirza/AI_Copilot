import { useEffect, useMemo, useState } from 'react'
import { useRunLive } from '@/hooks/useRunLive'
import { isActiveRunStatus } from '@/lib/runEvents'
import {
  runDisplayLabel,
  runStatusBadgeClass,
  runStatusLabel,
} from '@/types/runs'
import type { RunDetail, RunEvent } from '@/types/runs'
import { RunActivityFeed } from './RunActivityFeed'
import { RunOutcomeSummary } from './RunOutcomeSummary'

function formatElapsed(ms: number): string {
  const totalSec = Math.floor(ms / 1000)
  const min = Math.floor(totalSec / 60)
  const sec = totalSec % 60
  if (min > 0) return `${min}m ${sec.toString().padStart(2, '0')}s`
  return `${sec}s`
}

export type RunProgressLiveSnapshot = {
  events: RunEvent[]
  detail: RunDetail | null
  status: string
  currentStage: string | null
  elapsedMs: number
  latestActivityLine: string
}

interface RunProgressCardProps {
  runId: string
  displayName?: string | null
  status?: string
  showViewLink?: boolean
  onOpen?: () => void
  className?: string
  /** When provided, skips a nested `useRunLive` subscription (parent should own one). */
  live?: RunProgressLiveSnapshot
}

export function RunProgressCard({
  runId,
  displayName,
  status: statusProp,
  showViewLink = true,
  onOpen,
  className = '',
  live: liveFromParent,
}: RunProgressCardProps) {
  const ownLive = useRunLive(runId, { enabled: !liveFromParent })
  const live = liveFromParent ?? ownLive

  const {
    events,
    detail,
    status: liveStatus,
    currentStage,
    elapsedMs,
    latestActivityLine,
  } = live

  const status = statusProp || liveStatus
  const active = isActiveRunStatus(status)
  const title = runDisplayLabel({ id: runId, display_name: displayName ?? detail?.display_name })
  const [tick, setTick] = useState(0)

  useEffect(() => {
    if (!active) return
    const id = window.setInterval(() => setTick((n) => n + 1), 1000)
    return () => window.clearInterval(id)
  }, [active])

  const stageLine = useMemo(() => {
    void tick
    if (!currentStage) return null
    return `${currentStage.replaceAll('_', ' ')} · ${formatElapsed(elapsedMs)}`
  }, [currentStage, elapsedMs, tick])

  if (!active && ['completed', 'failed', 'blocked', 'cancelled', 'changes_requested'].includes(status)) {
    return (
      <RunOutcomeSummary
        runId={runId}
        displayName={displayName}
        detail={detail}
        status={status}
        elapsedMs={elapsedMs}
        onOpenConversation={onOpen}
        className={className}
      />
    )
  }

  return (
    <div
      className={`flex flex-col gap-2 rounded-md border border-[var(--border)] bg-[var(--bg-tertiary)] px-2.5 py-2 text-xs ${className}`}
    >
      <div className="flex flex-wrap items-center gap-2">
        <div className="min-w-0 flex-1">
          <p className="truncate font-medium text-sm text-[var(--text-primary)]" title={title}>
            {title}
          </p>
          {stageLine && (
            <p className="text-[10px] text-[var(--text-secondary)] truncate">{stageLine}</p>
          )}
          {!stageLine && latestActivityLine && (
            <p className="text-[10px] text-[var(--text-secondary)] truncate">{latestActivityLine}</p>
          )}
        </div>
        <span className={`shrink-0 rounded px-1.5 py-0.5 text-[10px] uppercase ${runStatusBadgeClass(status)}`}>
          {runStatusLabel(status)}
        </span>
        {showViewLink && onOpen && (
          <button
            type="button"
            className="shrink-0 text-[var(--accent)] hover:underline"
            onClick={onOpen}
          >
            View →
          </button>
        )}
      </div>
      <RunActivityFeed events={events} status={status} compact />
    </div>
  )
}
