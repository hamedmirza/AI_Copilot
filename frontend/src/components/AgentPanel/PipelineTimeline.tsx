import { normalizeRunEvents, stageStatusFromEvents } from '@/lib/runEvents'
import { STAGES } from '@/components/Chat/types'

interface PipelineTimelineProps {
  events: unknown[]
  compact?: boolean
  className?: string
}

export function PipelineTimeline({ events, compact = false, className = '' }: PipelineTimelineProps) {
  const normalized = normalizeRunEvents(events as Array<Record<string, unknown>>)
  return (
    <div className={`flex items-center gap-0 w-full overflow-x-auto py-1 ${className}`} role="list" aria-label="Pipeline stages">
      {STAGES.map((stage, index) => {
        const st = stageStatusFromEvents(normalized, stage)
        const dotClass =
          st === 'done' ? 'bg-[var(--success)]' :
          st === 'running' ? 'bg-[var(--accent)] animate-pulse' :
          st === 'failed' ? 'bg-[var(--error)]' :
          'bg-gray-500'
        const isLast = index === STAGES.length - 1
        return (
          <div key={stage} className="flex items-center shrink-0" role="listitem">
            <div className="flex flex-col items-center gap-0.5 min-w-[3rem]" title={stage}>
              <span className={`rounded-full ${compact ? 'w-2 h-2' : 'w-2.5 h-2.5'} ${dotClass}`} />
              {!compact && (
                <span className="text-[9px] text-[var(--text-secondary)] truncate max-w-[4rem]">
                  {stage.replace('_', ' ')}
                </span>
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
