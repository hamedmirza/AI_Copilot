import { useEffect, useState } from 'react'
import type { ChatMessage, RunEvent } from '@/store'
import { formatAnswerDuration, formatChatTimestamp, resolveAnswerDurationMs } from './types'
import { ToolCallCard } from './ToolCallCard'
import { RunCard } from './RunCard'
import { RunFollowUpCard } from './RunFollowUpCard'
import { ThinkingIndicator } from './ThinkingIndicator'

interface MessageBubbleProps {
  message: ChatMessage
  runEventsById: Record<string, RunEvent[]>
  runActionBusy?: boolean
  thinkingLabel?: string | null
  onApproveRun: (runId: string) => void | Promise<void>
  onRejectRun: (runId: string) => void | Promise<void>
  onRetryRun: (runId: string, feedback?: string) => void | Promise<void>
}

export function MessageBubble({
  message,
  runEventsById,
  runActionBusy,
  thinkingLabel,
  onApproveRun,
  onRejectRun,
  onRetryRun,
}: MessageBubbleProps) {
  const [now, setNow] = useState(Date.now())

  useEffect(() => {
    if (message.role !== 'assistant' || !message.pending) return
    const timer = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [message.id, message.pending, message.role])

  if (message.role === 'tool' || message.role === 'system') {
    return null
  }

  const isUser = message.role === 'user'
  const answerDurationMs = !isUser ? resolveAnswerDurationMs(message, now) : null
  const answerDurationLabel = answerDurationMs != null
    ? `${formatAnswerDuration(answerDurationMs)}${message.pending ? '…' : ''}`
    : null
  const runId = message.metadata?.run_id ? String(message.metadata.run_id) : null
  const runDisplayName = message.metadata?.display_name
    ? String(message.metadata.display_name)
    : null
  const metaType = String(message.metadata?.type || '')
  const isRunCard = metaType === 'run_spawned' && !!runId
  const isRunSummary = metaType === 'run_summary' && !!runId
  const runEvents = runId ? (runEventsById[runId] || []) : []
  const runStatus = String(message.metadata?.run_status || message.metadata?.status || '')

  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}>
      <div className={`max-w-[92%] rounded-lg border px-3 py-2 ${
        isUser
          ? 'bg-[var(--accent)] border-[var(--accent)] text-white'
          : 'bg-[var(--bg-secondary)] border-[var(--border)]'
      }`}>
        <div className="flex items-center gap-2 mb-1 text-[11px] uppercase tracking-wide opacity-80">
          <span>{message.role}</span>
          {message.created_at && <span>{formatChatTimestamp(message.created_at)}</span>}
          {answerDurationLabel && (
            <span className="normal-case tracking-normal">{answerDurationLabel}</span>
          )}
          {!isUser && (message.metadata?.provider || message.metadata?.model) && (
            <span className="ml-auto normal-case tracking-normal text-[var(--text-secondary)]">
              {String(message.metadata?.model || '')}
              {message.metadata?.provider ? ` · ${String(message.metadata.provider)}` : ''}
            </span>
          )}
        </div>

        {message.content && (
          <div className="whitespace-pre-wrap break-words text-sm">{message.content}</div>
        )}

        {!message.content && message.pending && !message.error && (
          <ThinkingIndicator label={thinkingLabel || 'Thinking'} />
        )}

        {message.error && (
          <p className="text-sm text-[var(--error)]">{message.error}</p>
        )}

        {message.tool_calls && message.tool_calls.length > 0 && (
          <div className={message.content ? 'mt-3 space-y-2' : 'space-y-2'}>
            {!message.content && !message.pending && (
              <p className="text-xs text-[var(--text-secondary)]">
                Used tools to gather context (expand for details).
              </p>
            )}
            {message.tool_calls.map((toolCall) => (
              <ToolCallCard key={toolCall.id} toolCall={toolCall} />
            ))}
          </div>
        )}

        {isRunCard && runId && (
          <div className={message.content ? 'mt-3' : ''}>
            <RunCard
              runId={runId}
              displayName={runDisplayName}
              events={runEvents}
              busy={runActionBusy}
              onApprove={onApproveRun}
              onReject={onRejectRun}
              onRetry={onRetryRun}
            />
            <RunFollowUpCard
              runId={runId}
              runStatus={runStatus}
              events={runEvents}
              busy={runActionBusy}
              onRetry={onRetryRun}
            />
          </div>
        )}

        {isRunSummary && runId && !isRunCard && (
          <RunFollowUpCard
            runId={runId}
            runStatus={runStatus}
            events={runEvents}
            busy={runActionBusy}
            onRetry={onRetryRun}
          />
        )}
      </div>
    </div>
  )
}
