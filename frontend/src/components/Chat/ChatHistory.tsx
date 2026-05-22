import { History, MessageSquarePlus, Search, Trash2 } from 'lucide-react'
import { Button, EmptyState, Skeleton } from '@/components/ui/primitives'
import { cn } from '@/lib/utils'
import type { ChatSession } from '@/store'
import { formatRelativeChatTime } from './types'

interface ChatHistoryProps {
  sessions: ChatSession[]
  currentSessionId: string | null
  loading?: boolean
  deleting?: boolean
  searchQuery: string
  onSearchChange: (value: string) => void
  onSelect: (sessionId: string) => void
  onNew: () => void
  onDelete: (sessionId: string) => void
}

function matchesSearch(session: ChatSession, query: string) {
  const normalized = query.trim().toLowerCase()
  if (!normalized) return true
  const haystack = [
    session.title,
    session.last_message_preview || '',
    String(session.mode || ''),
  ].join(' ').toLowerCase()
  return haystack.includes(normalized)
}

function formatMessageCount(count: number) {
  return `${count} message${count === 1 ? '' : 's'}`
}

function formatModeLabel(value: string) {
  if (!value) return 'General'
  return value.charAt(0).toUpperCase() + value.slice(1)
}

export function ChatHistory({
  sessions,
  currentSessionId,
  loading,
  deleting,
  searchQuery,
  onSearchChange,
  onSelect,
  onNew,
  onDelete,
}: ChatHistoryProps) {
  const filteredSessions = sessions.filter((session) => matchesSearch(session, searchQuery))

  return (
    <aside className="w-64 shrink-0 border-r border-[var(--border)] bg-[var(--bg-secondary)] overflow-hidden flex flex-col">
      <div className="p-3 border-b border-[var(--border)] space-y-3">
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2 text-sm font-medium text-[var(--text-primary)]">
            <History className="h-4 w-4" />
            <span>History</span>
          </div>
          <Button variant="secondary" className="px-2" onClick={onNew} disabled={loading}>
            <MessageSquarePlus className="h-4 w-4" />
            <span>New chat</span>
          </Button>
        </div>

        <label className="relative block">
          <Search className="absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-[var(--text-secondary)]" />
          <input
            value={searchQuery}
            onChange={(event) => onSearchChange(event.target.value)}
            placeholder="Search chats"
            className="w-full rounded border border-[var(--border)] bg-[var(--bg-tertiary)] py-1.5 pl-7 pr-2 text-sm outline-none focus:border-[var(--accent)]"
          />
        </label>
      </div>

      <div className="flex-1 overflow-auto p-2 space-y-2">
        {loading ? (
          Array.from({ length: 5 }).map((_, index) => (
            <div key={index} className="rounded border border-[var(--border)] bg-[var(--bg-tertiary)] p-3 space-y-2">
              <Skeleton className="h-4 w-2/3" />
              <Skeleton className="h-3 w-full" />
              <Skeleton className="h-3 w-1/2" />
            </div>
          ))
        ) : filteredSessions.length === 0 ? (
          <EmptyState
            title={searchQuery.trim() ? 'No matching chats' : 'No previous chats'}
            description={
              searchQuery.trim()
                ? 'Try a different title or keyword.'
                : 'No previous chats - start a new conversation'
            }
            action={!searchQuery.trim() ? <Button onClick={onNew}>New chat</Button> : undefined}
          />
        ) : (
          filteredSessions.map((session) => {
            const isActive = session.id === currentSessionId
            const preview = session.last_message_preview || 'No messages yet'
            const timestamp = formatRelativeChatTime(
              session.last_message_at || session.updated_at || session.created_at || null
            )

            return (
              <div
                key={session.id}
                className={cn(
                  'group flex items-start gap-2 rounded border p-2 transition-colors',
                  isActive
                    ? 'border-[var(--accent)] bg-[var(--bg-tertiary)]'
                    : 'border-[var(--border)] bg-[var(--bg-tertiary)] hover:bg-[#303030]'
                )}
              >
                <button
                  type="button"
                  onClick={() => onSelect(session.id)}
                  className="min-w-0 flex-1 text-left"
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="truncate text-sm font-medium text-[var(--text-primary)]">
                      {session.title || 'Untitled chat'}
                    </div>
                    {timestamp ? (
                      <span className="shrink-0 text-[11px] text-[var(--text-secondary)]">{timestamp}</span>
                    ) : null}
                  </div>
                  <div className="mt-1 truncate text-xs text-[var(--text-secondary)]">
                    {preview}
                  </div>
                  <div className="mt-2 flex items-center gap-2 text-[11px] text-[var(--text-secondary)]">
                    <span className="rounded border border-[var(--border)] px-1.5 py-0.5">
                      {formatModeLabel(String(session.mode || 'general'))}
                    </span>
                    <span>{formatMessageCount(Number(session.message_count || 0))}</span>
                  </div>
                </button>

                <Button
                  variant="ghost"
                  className="px-2 py-2 opacity-80 group-hover:opacity-100"
                  disabled={deleting || sessions.length <= 1}
                  onClick={() => onDelete(session.id)}
                  title={sessions.length <= 1 ? 'Create another chat before deleting this one' : 'Delete chat'}
                >
                  <Trash2 className="h-4 w-4" />
                </Button>
              </div>
            )
          })
        )}
      </div>
    </aside>
  )
}
