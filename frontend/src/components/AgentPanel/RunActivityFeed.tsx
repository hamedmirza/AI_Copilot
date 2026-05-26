import { useEffect, useMemo, useRef, useState } from 'react'
import {
  formatRunActivityLine,
  isActivityVisibleRunEvent,
  isActiveRunStatus,
} from '@/lib/runEvents'
import type { RunEvent } from '@/types/runs'

const MAX_VISIBLE_LINES = 40
const SILENCE_MS = 15_000

interface RunActivityFeedProps {
  events: RunEvent[]
  status: string
  compact?: boolean
  className?: string
}

export function RunActivityFeed({
  events,
  status,
  compact = false,
  className = '',
}: RunActivityFeedProps) {
  const scrollRef = useRef<HTMLDivElement>(null)
  const [now, setNow] = useState(Date.now())

  const active = isActiveRunStatus(status)
  const visibleEvents = useMemo(
    () => events.filter(isActivityVisibleRunEvent),
    [events],
  )
  const displayEvents = useMemo(
    () => visibleEvents.slice(-MAX_VISIBLE_LINES),
    [visibleEvents],
  )

  const lastEventAt = useMemo(() => {
    for (let i = events.length - 1; i >= 0; i -= 1) {
      const created = events[i].created_at
      if (!created) continue
      const ts = Date.parse(created)
      if (!Number.isNaN(ts)) return ts
    }
    return null
  }, [events])

  useEffect(() => {
    if (!active) return
    const id = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(id)
  }, [active])

  useEffect(() => {
    const el = scrollRef.current
    if (!el) return
    el.scrollTop = el.scrollHeight
  }, [displayEvents.length])

  const showThinking = active && (
    lastEventAt == null || now - lastEventAt > SILENCE_MS
  )

  if (!active && displayEvents.length === 0) {
    return null
  }

  return (
    <div
      className={`rounded border border-[var(--border)] bg-[var(--bg-tertiary)] ${compact ? 'text-[10px]' : 'text-xs'} ${className}`}
    >
      <p className="px-2 py-1 text-[10px] uppercase tracking-wide text-[var(--text-secondary)] border-b border-[var(--border)]">
        Live activity
      </p>
      <div
        ref={scrollRef}
        className={`overflow-y-auto px-2 py-1.5 space-y-1 ${compact ? 'max-h-24' : 'max-h-40'}`}
        role="log"
        aria-live="polite"
        aria-label="Run activity"
      >
        {displayEvents.length === 0 && !showThinking && (
          <p className="text-[var(--text-secondary)]">Waiting for updates…</p>
        )}
        {displayEvents.map((event, index) => (
          <p key={`${event.id ?? index}-${event.type}-${event.created_at}`} className="text-[var(--text-primary)] leading-snug">
            {formatRunActivityLine(event)}
          </p>
        ))}
        {showThinking && (
          <p className="text-[var(--text-secondary)] animate-pulse">Still working…</p>
        )}
      </div>
    </div>
  )
}
