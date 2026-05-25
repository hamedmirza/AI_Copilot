import { useEffect, useMemo, useState } from 'react'
import { api } from '@/api/client'
import { runStatusFromEvents } from '@/lib/runEvents'
import {
  runDisplayLabel,
  runStatusBadgeClass,
  runStatusLabel,
} from '@/types/runs'
import type { RunEvent } from '@/store'
import { useUIStore } from '@/store'

interface RunStatusChipProps {
  runId: string
  displayName?: string | null
  status?: string
  events?: RunEvent[]
  showViewLink?: boolean
  onOpen?: () => void
  className?: string
}

export function RunStatusChip({
  runId,
  displayName,
  status: statusProp,
  events = [],
  showViewLink = true,
  onOpen,
  className = '',
}: RunStatusChipProps) {
  const requestOpenRunDrawer = useUIStore((s) => s.requestOpenRunDrawer)
  const setRightPanelTab = useUIStore((s) => s.setRightPanelTab)
  const [polledStatus, setPolledStatus] = useState<string | null>(null)

  const eventStatus = useMemo(
    () => runStatusFromEvents(events.map((e) => ({ ...e, type: String(e.type || '') }))),
    [events],
  )
  const status = statusProp || polledStatus || eventStatus
  const title = runDisplayLabel({ id: runId, display_name: displayName ?? '' })

  useEffect(() => {
    let cancelled = false
    const refresh = async () => {
      try {
        const run = await api.runs.get(runId) as { status?: string }
        if (!cancelled) setPolledStatus(run.status ? String(run.status) : null)
      } catch {
        if (!cancelled) setPolledStatus(null)
      }
    }
    void refresh()
    if (!['pending', 'running', 'awaiting_approval', 'awaiting_clarification'].includes(status)) {
      return () => { cancelled = true }
    }
    const id = window.setInterval(() => void refresh(), 4000)
    return () => {
      cancelled = true
      window.clearInterval(id)
    }
  }, [runId, status])

  const openInAgents = onOpen ?? (() => {
    setRightPanelTab('agents')
    requestOpenRunDrawer(runId, 'conversation')
  })

  return (
    <div
      className={`flex flex-wrap items-center gap-2 rounded-md border border-[var(--border)] bg-[var(--bg-tertiary)] px-2.5 py-2 text-xs ${className}`}
    >
      <div className="min-w-0 flex-1">
        <p className="truncate font-medium text-sm text-[var(--text-primary)]" title={title}>
          {title}
        </p>
        <p className="font-mono text-[10px] text-[var(--text-secondary)] truncate" title={runId}>
          {runId.slice(0, 8)}…
        </p>
      </div>
      <span className={`shrink-0 rounded px-1.5 py-0.5 text-[10px] uppercase ${runStatusBadgeClass(status)}`}>
        {runStatusLabel(status)}
      </span>
      {showViewLink && (
        <button
          type="button"
          className="shrink-0 text-[var(--accent)] hover:underline"
          onClick={openInAgents}
        >
          View in Agents →
        </button>
      )}
    </div>
  )
}
