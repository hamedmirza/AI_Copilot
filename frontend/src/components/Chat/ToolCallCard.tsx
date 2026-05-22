import { useMemo, useState } from 'react'
import type { ChatToolCall } from '@/store'
import { summarizeToolResult } from './types'

interface ToolCallCardProps {
  toolCall: ChatToolCall
  defaultOpen?: boolean
}

export function ToolCallCard({ toolCall, defaultOpen = false }: ToolCallCardProps) {
  const [open, setOpen] = useState(defaultOpen)

  const statusClass = useMemo(() => {
    if (toolCall.status === 'completed') return 'text-[var(--success)]'
    if (toolCall.status === 'error') return 'text-[var(--error)]'
    return 'text-[var(--accent)]'
  }, [toolCall.status])

  return (
    <div className="border border-[var(--border)] rounded-md bg-[var(--bg-tertiary)] overflow-hidden">
      <button
        className="w-full flex items-center justify-between px-3 py-2 text-left hover:bg-black/10"
        onClick={() => setOpen((value) => !value)}
      >
        <div className="flex items-center gap-2 min-w-0">
          <span className={`text-xs font-medium uppercase shrink-0 ${statusClass}`}>{toolCall.status}</span>
          <span className="text-sm truncate">{toolCall.name}</span>
        </div>
        <span className="text-xs text-[var(--text-secondary)]">{open ? 'Hide' : 'Show'}</span>
      </button>
      {open && (
        <div className="px-3 pb-3 space-y-2 text-xs">
          <div>
            <p className="mb-1 text-[var(--text-secondary)]">Arguments</p>
            <pre className="m-0 p-2 rounded bg-black/20 overflow-auto whitespace-pre-wrap break-words">
              {summarizeToolResult(toolCall.args) || '{}'}
            </pre>
          </div>
          {(toolCall.result !== undefined || toolCall.error) && (
            <div>
              <p className="mb-1 text-[var(--text-secondary)]">Result</p>
              <pre className="m-0 p-2 rounded bg-black/20 overflow-auto whitespace-pre-wrap break-words">
                {toolCall.error || summarizeToolResult(toolCall.result)}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
