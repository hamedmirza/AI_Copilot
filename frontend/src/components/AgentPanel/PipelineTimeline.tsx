import { useEffect, useMemo, useState } from 'react'
import { normalizeRunEvents, stageStatusFromEvents } from '@/lib/runEvents'
import { parseApiDateTime } from '@/lib/datetime'
import { STAGES } from '@/components/Chat/types'

function stageElapsedLabel(events: ReturnType<typeof normalizeRunEvents>, stage: string): string | null {
  const started = events.find((e) => e.type === `${stage}_started`)
  if (!started?.created_at) return null
  const start = parseApiDateTime(started.created_at)
  if (!start) return null
  const complete = events.find((e) => e.type === `${stage}_complete`)
  const end = complete?.created_at ? parseApiDateTime(complete.created_at) : new Date()
  if (!end) return null
  const sec = Math.max(0, Math.floor((end.getTime() - start.getTime()) / 1000))
  if (sec < 60) return `${sec}s`
  return `${Math.floor(sec / 60)}m ${sec % 60}s`
}

interface PipelineTimelineProps {
  events: unknown[]
  workflowStages?: string[]
  compact?: boolean
  activeStage?: string | null
  className?: string
}

export function PipelineTimeline({
  events,
  workflowStages,
  compact = false,
  activeStage = null,
  className = '',
}: PipelineTimelineProps) {
  const normalized = normalizeRunEvents(events as Array<Record<string, unknown>>)
  const stages = workflowStages?.length ? workflowStages : STAGES
  const [now, setNow] = useState(Date.now())

  const runningStage = useMemo(() => {
    if (activeStage) return activeStage
    for (let i = normalized.length - 1; i >= 0; i -= 1) {
      const type = String(normalized[i].type || '')
      if (type.endsWith('_started')) return type.replace(/_started$/, '')
    }
    return null
  }, [activeStage, normalized])

  useEffect(() => {
    if (!runningStage) return
    const id = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(id)
  }, [runningStage])

  const runningElapsed = useMemo(() => {
    void now
    if (!runningStage) return null
    const st = stageStatusFromEvents(normalized, runningStage)
    if (st !== 'running') return stageElapsedLabel(normalized, runningStage)
    const started = normalized.find((e) => e.type === `${runningStage}_started`)
    if (!started?.created_at) return null
    const start = parseApiDateTime(started.created_at)
    if (!start) return null
    const sec = Math.max(0, Math.floor((Date.now() - start.getTime()) / 1000))
    if (sec < 60) return `${sec}s`
    return `${Math.floor(sec / 60)}m ${sec % 60}s`
  }, [normalized, now, runningStage])

  return (
    <div className={`flex items-center gap-0 w-full overflow-x-auto py-1 ${className}`} role="list" aria-label="Pipeline stages">
      {stages.map((stage, index) => {
        const st = stageStatusFromEvents(normalized, stage)
        const dotClass =
          st === 'done' ? 'bg-[var(--success)]' :
          st === 'running' ? 'bg-[var(--accent)] animate-pulse' :
          st === 'failed' ? 'bg-[var(--error)]' :
          st === 'skipped' ? 'bg-gray-600' :
          'bg-gray-500'
        const isLast = index === stages.length - 1
        const showElapsed = stage === runningStage && (runningElapsed || st === 'running')
        return (
          <div key={stage} className="flex items-center shrink-0" role="listitem">
            <div className="flex flex-col items-center gap-0.5 min-w-[3rem]" title={stage}>
              <span className={`rounded-full ${compact ? 'w-2 h-2' : 'w-2.5 h-2.5'} ${dotClass}`} />
              {!compact && (
                <span className="text-[9px] text-[var(--text-secondary)] truncate max-w-[4rem]">
                  {stage.replace('_', ' ')}
                </span>
              )}
              {showElapsed && runningElapsed && (
                <span className="text-[8px] text-[var(--accent)]">{runningElapsed}</span>
              )}
            </div>
            {!isLast && (
              <div
                className={`h-px w-3 sm:w-4 shrink-0 ${
                  st === 'done' ? 'bg-[var(--success)]/50' : 'bg-[var(--border)]'
                }`}
                aria-hidden
              />
            )}
          </div>
        )
      })}
    </div>
  )
}
