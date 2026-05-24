import { useEffect, useMemo, useState } from 'react'
import { api } from '@/api/client'
import { Button } from '@/components/ui/primitives'
import { RunLogPanel } from '@/components/shared/RunLogPanel'
import { filterSignificantRunEvents, normalizeRunEvent, runStatusFromEvents, stageStatusFromEvents } from '@/lib/runEvents'
import { runDisplayLabel } from '@/types/runs'
import type { RunEvent } from '@/store'
import { STAGES } from './types'

interface RunCardProps {
  runId: string
  displayName?: string | null
  events: RunEvent[]
  busy?: boolean
  onApprove: (runId: string) => void | Promise<void>
  onReject: (runId: string) => void | Promise<void>
  onRetry: (runId: string) => void | Promise<void>
}

export function RunCard({ runId, displayName, events, busy, onApprove, onReject, onRetry }: RunCardProps) {
  const title = runDisplayLabel({ id: runId, display_name: displayName ?? '' })
  const [polledStatus, setPolledStatus] = useState<string | null>(null)
  const displayEvents = useMemo(
    () => events.map((event) => normalizeRunEvent(event as Record<string, unknown>)),
    [events],
  )
  const eventStatus = runStatusFromEvents(displayEvents)
  const runStatus = polledStatus || eventStatus
  const hasLog = filterSignificantRunEvents(displayEvents).length > 0 || displayEvents.length > 0

  useEffect(() => {
    let cancelled = false
    const refreshStatus = async () => {
      try {
        const run = await api.runs.get(runId) as { status?: string }
        if (!cancelled) {
          setPolledStatus(run.status ? String(run.status) : null)
        }
      } catch {
        if (!cancelled) {
          setPolledStatus(null)
        }
      }
    }
    void refreshStatus()
    if (!['pending', 'running', 'awaiting_approval'].includes(eventStatus)) {
      return () => {
        cancelled = true
      }
    }
    const intervalId = window.setInterval(() => {
      void refreshStatus()
    }, 4000)
    return () => {
      cancelled = true
      window.clearInterval(intervalId)
    }
  }, [eventStatus, runId])

  return (
    <div className="border border-[var(--border)] rounded-md bg-[var(--bg-tertiary)] p-3 space-y-3">
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0">
          <p className="text-sm font-medium truncate" title={title}>{title}</p>
          <p className="text-xs text-[var(--text-secondary)] font-mono truncate" title={runId}>
            {runId.slice(0, 8)}…
          </p>
        </div>
        <span className={`text-xs uppercase shrink-0 ${
          runStatus === 'completed' ? 'text-[var(--success)]' :
          runStatus === 'failed' || runStatus === 'blocked' ? 'text-[var(--error)]' :
          runStatus === 'awaiting_approval' ? 'text-[var(--warning)]' :
          'text-[var(--accent)]'
        }`}>
          {runStatus.replaceAll('_', ' ')}
        </span>
      </div>

      <div className="flex gap-1 flex-wrap">
        {STAGES.map((stage) => {
          const status = stageStatusFromEvents(displayEvents, stage)
          return (
            <div key={stage} className="flex items-center gap-1 text-xs px-2 py-1 rounded bg-black/20">
              <span className={`w-2 h-2 rounded-full ${
                status === 'done' ? 'bg-[var(--success)]' :
                status === 'running' ? 'bg-[var(--accent)] animate-pulse' :
                status === 'failed' ? 'bg-[var(--error)]' :
                'bg-gray-500'
              }`} />
              {stage}
            </div>
          )
        })}
      </div>

      {hasLog && (
        <RunLogPanel events={displayEvents} logClassName="max-h-32" />
      )}

      <div className="flex gap-2">
        <Button disabled={runStatus !== 'awaiting_approval' || busy} onClick={() => onApprove(runId)}>
          Approve
        </Button>
        <Button variant="danger" disabled={runStatus !== 'awaiting_approval' || busy} onClick={() => onReject(runId)}>
          Reject
        </Button>
        <Button variant="secondary" disabled={!['blocked', 'changes_requested'].includes(runStatus) || busy} onClick={() => onRetry(runId)}>
          Retry
        </Button>
      </div>
    </div>
  )
}
