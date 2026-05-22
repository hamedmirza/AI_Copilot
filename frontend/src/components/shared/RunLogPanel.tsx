import { useEffect, useMemo, useState, type UIEvent } from 'react'
import type { RunEvent } from '@/types/runs'
import {
  filterSignificantRunEvents,
  formatRunEventLine,
  runEventSeverityClass,
} from '@/lib/runEvents'
import { Button } from '@/components/ui/primitives'

interface RunLogPanelProps {
  events: RunEvent[]
  defaultExpanded?: boolean
  emptyLabel?: string
  className?: string
  logClassName?: string
  fullHeight?: boolean
  onExpandedChange?: (expanded: boolean) => void
  onLogScroll?: (event: UIEvent<HTMLDivElement>) => void
}

export function RunLogPanel({
  events,
  defaultExpanded = false,
  emptyLabel = 'No updates yet',
  className = '',
  logClassName = 'max-h-48',
  fullHeight = false,
  onExpandedChange,
  onLogScroll,
}: RunLogPanelProps) {
  const [expanded, setExpanded] = useState(defaultExpanded)
  const [showAll, setShowAll] = useState(false)

  useEffect(() => {
    onExpandedChange?.(expanded)
  }, [expanded, onExpandedChange])

  const significantEvents = useMemo(() => filterSignificantRunEvents(events), [events])
  const displayEvents = showAll ? events : significantEvents
  const latestSignificant = significantEvents[significantEvents.length - 1]

  if (!expanded) {
    return (
      <div className={`space-y-2 ${className}`}>
        {latestSignificant ? (
          <p className={`text-xs ${runEventSeverityClass(latestSignificant)}`}>
            {formatRunEventLine(latestSignificant)}
          </p>
        ) : (
          <p className="text-xs text-[var(--text-secondary)]">{emptyLabel}</p>
        )}
        {events.length > 0 && (
          <Button variant="ghost" className="text-xs h-7 px-2" onClick={() => setExpanded(true)}>
            Show log ({events.length})
          </Button>
        )}
      </div>
    )
  }

  return (
    <div className={`space-y-2 ${className}`}>
      <div className="flex items-center justify-between gap-2">
        <p className="text-xs text-[var(--text-secondary)] uppercase tracking-wide">Activity</p>
        <div className="flex items-center gap-2">
          {significantEvents.length < events.length && (
            <button
              type="button"
              className="text-xs text-[var(--accent)] hover:underline"
              onClick={() => setShowAll((value) => !value)}
            >
              {showAll ? 'Important only' : `All events (${events.length})`}
            </button>
          )}
          <Button variant="ghost" className="text-xs h-7 px-2" onClick={() => setExpanded(false)}>
            Hide log
          </Button>
        </div>
      </div>
      <div
        data-run-log-scroll
        onScroll={onLogScroll}
        className={`overflow-auto bg-[#1a1a1a] rounded p-2 text-xs font-mono ${
          fullHeight ? 'flex-1 min-h-0' : logClassName
        }`}
      >
        {displayEvents.length === 0 && (
          <p className="text-[var(--text-secondary)]">
            {showAll ? 'No events' : 'No important events — switch to all events'}
          </p>
        )}
        {displayEvents.map((event, index) => (
          <div
            key={`${String(event.type || 'event')}-${index}`}
            className={`py-0.5 ${runEventSeverityClass(event)}`}
          >
            {formatRunEventLine(event)}
          </div>
        ))}
      </div>
    </div>
  )
}
