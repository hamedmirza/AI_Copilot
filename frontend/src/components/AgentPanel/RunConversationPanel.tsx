import { useMemo } from 'react'
import type { RunDetail, RunThreadEntry } from '@/types/runs'
import { formatChatTimestamp } from '@/components/Chat/types'

function severityClass(severity?: string): string {
  switch (severity) {
    case 'error':
      return 'border-[var(--error)]/40 text-[var(--error)]'
    case 'warning':
      return 'border-[var(--warning)]/40 text-[var(--warning)]'
    default:
      return 'border-[var(--border)] text-[var(--text-primary)]'
  }
}

function normalizeThreadEntry(row: Record<string, unknown>): RunThreadEntry {
  return {
    id: Number(row.id),
    run_id: String(row.run_id || ''),
    session_id: row.session_id != null ? String(row.session_id) : null,
    role: String(row.role || 'assistant'),
    entry_type: String(row.entry_type || ''),
    stage: row.stage != null ? String(row.stage) : null,
    severity: row.severity != null ? String(row.severity) : undefined,
    message: String(row.message || ''),
    payload: (row.payload && typeof row.payload === 'object')
      ? row.payload as Record<string, unknown>
      : undefined,
    created_at: String(row.created_at || ''),
  }
}

interface RunConversationPanelProps {
  detail: RunDetail | null
  thread: RunThreadEntry[]
  loading?: boolean
}

export function RunConversationPanel({ detail, thread, loading }: RunConversationPanelProps) {
  const entries = useMemo(() => thread.map((e) => e), [thread])
  const awaitingClarification = detail?.status === 'awaiting_clarification'
  const question = detail?.clarification_question?.trim()
  const assumption = detail?.recommended_assumption?.trim()
  const resolvedQuestion = useMemo(() => {
    const entries = thread.filter((e) => e.entry_type === 'clarification_answered')
    const last = entries[entries.length - 1]
    return last?.payload?.question ? String(last.payload.question) : null
  }, [thread])
  const resolvedAnswer = useMemo(() => {
    const entries = thread.filter((e) => e.entry_type === 'clarification_answered')
    const last = entries[entries.length - 1]
    return last?.payload?.answer ? String(last.payload.answer) : null
  }, [thread])

  return (
    <div className="space-y-3">
      {!awaitingClarification && resolvedQuestion && resolvedAnswer && (
        <div className="border border-[var(--border)] rounded-lg p-3 bg-[var(--bg-tertiary)]/40 space-y-1">
          <p className="text-xs uppercase tracking-wide text-[var(--text-secondary)]">Clarification answered</p>
          <p className="text-sm text-[var(--text-secondary)]">{resolvedQuestion}</p>
          <p className="text-sm whitespace-pre-wrap">{resolvedAnswer}</p>
        </div>
      )}

      {awaitingClarification && question && (
        <div className="border border-[var(--warning)]/50 rounded-lg p-3 bg-[var(--warning)]/10 space-y-2">
          <p className="text-xs uppercase tracking-wide text-[var(--warning)] font-medium">
            Clarification needed
            {detail?.clarification_stage ? ` · ${detail.clarification_stage}` : ''}
          </p>
          <p className="text-sm whitespace-pre-wrap">{question}</p>
          {assumption && (
            <p className="text-xs text-[var(--text-secondary)]">
              If you do not answer, we may assume: {assumption}
            </p>
          )}
        </div>
      )}

      {loading && entries.length === 0 && (
        <p className="text-sm text-[var(--text-secondary)]">Loading conversation…</p>
      )}

      {!loading && entries.length === 0 && (
        <p className="text-sm text-[var(--text-secondary)]">
          No thread messages yet. Pipeline updates will appear here as the run progresses.
        </p>
      )}

      <div className="space-y-2">
        {entries.map((entry) => {
          const isUser = entry.role === 'user'
          return (
            <div
              key={entry.id}
              className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}
            >
              <div
                className={`max-w-[90%] rounded-lg border px-3 py-2 text-sm ${
                  isUser
                    ? 'bg-[var(--accent)]/15 border-[var(--accent)]/40'
                    : `bg-[var(--bg-tertiary)] ${severityClass(entry.severity)}`
                }`}
              >
                <div className="flex items-center gap-2 text-[10px] uppercase tracking-wide opacity-70 mb-1">
                  <span>{entry.role}</span>
                  {entry.stage && <span>{entry.stage}</span>}
                  {entry.entry_type && entry.entry_type !== entry.stage && (
                    <span className="normal-case">{entry.entry_type.replaceAll('_', ' ')}</span>
                  )}
                  {entry.created_at && (
                    <span className="ml-auto normal-case">{formatChatTimestamp(entry.created_at)}</span>
                  )}
                </div>
                <p className="whitespace-pre-wrap break-words">{entry.message}</p>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

export { normalizeThreadEntry }
