import { useEffect, useMemo, useRef, useState } from 'react'
import type { ChatMode, TreeItem } from '@/store'
import { Button } from '@/components/ui/primitives'
import { showError } from '@/lib/toast'
import { ModeSelector } from './ModeSelector'
import { normalizeChatMode } from './types'

export type ComposerCommand =
  | { type: 'send'; content: string }
  | { type: 'mode'; mode: ChatMode }
  | { type: 'task'; description: string }
  | { type: 'clear' }
  | { type: 'mcp-list' }
  | { type: 'model'; model: string }

interface ChatComposerProps {
  value: string
  mode: ChatMode
  treeItems: TreeItem[]
  disabled?: boolean
  submitting?: boolean
  pendingRunId?: string | null
  onChange: (value: string) => void
  onModeChange: (mode: ChatMode) => void
  onCommand: (command: ComposerCommand) => void | Promise<void>
  onSendAndRetry?: (content: string, runId: string) => void | Promise<void>
}

export function ChatComposer({
  value,
  mode,
  treeItems,
  disabled,
  submitting,
  pendingRunId,
  onChange,
  onModeChange,
  onCommand,
  onSendAndRetry,
}: ChatComposerProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const [mentionQuery, setMentionQuery] = useState('')
  const [mentionStart, setMentionStart] = useState<number | null>(null)

  const fileSuggestions = useMemo(() => {
    if (mentionStart === null) return []
    const files = treeItems.filter((item) => item.type === 'file')
    return files
      .filter((item) => item.path.toLowerCase().includes(mentionQuery.toLowerCase()))
      .slice(0, 8)
  }, [mentionQuery, mentionStart, treeItems])

  useEffect(() => {
    const textarea = textareaRef.current
    if (!textarea) return
    const cursor = textarea.selectionStart
    const textBeforeCursor = value.slice(0, cursor)
    const match = textBeforeCursor.match(/(?:^|\s)@([^\s]*)$/)
    if (!match || match.index === undefined) {
      setMentionQuery('')
      setMentionStart(null)
      return
    }
    setMentionQuery(match[1] || '')
    setMentionStart(match.index + match[0].lastIndexOf('@'))
  }, [value])

  const executeCommand = async () => {
    const trimmed = value.trim()
    if (!trimmed || disabled) return

    if (!trimmed.startsWith('/')) {
      await onCommand({ type: 'send', content: trimmed })
      return
    }

    const [command, ...rest] = trimmed.slice(1).split(/\s+/)
    const payload = rest.join(' ').trim()

    switch (command.toLowerCase()) {
      case 'mode': {
        const parsed = normalizeChatMode(payload)
        if (!payload) {
          showError('Usage: /mode <general|agent|planner|debugger|architect>')
          return
        }
        await onCommand({ type: 'mode', mode: parsed })
        return
      }
      case 'task':
        if (!payload) {
          showError('Usage: /task <description>')
          return
        }
        await onCommand({ type: 'task', description: payload })
        return
      case 'clear':
        await onCommand({ type: 'clear' })
        return
      case 'mcp':
        if (payload.toLowerCase() !== 'list') {
          showError('Usage: /mcp list')
          return
        }
        await onCommand({ type: 'mcp-list' })
        return
      case 'model':
        if (!payload) {
          showError('Usage: /model <name>')
          return
        }
        await onCommand({ type: 'model', model: payload })
        return
      default:
        showError(`Unknown slash command: /${command}`)
    }
  }

  const insertMention = (path: string) => {
    const textarea = textareaRef.current
    if (!textarea || mentionStart === null) return
    const cursor = textarea.selectionStart
    const nextValue = `${value.slice(0, mentionStart)}@${path} ${value.slice(cursor)}`
    onChange(nextValue)
    requestAnimationFrame(() => {
      const nextCursor = mentionStart + path.length + 2
      textarea.focus()
      textarea.setSelectionRange(nextCursor, nextCursor)
      setMentionStart(null)
    })
  }

  return (
    <div className="border-t border-[var(--border)] p-3 space-y-2 bg-[var(--bg-secondary)]">
      <div className="flex items-center justify-between gap-2">
        <ModeSelector value={mode} onChange={onModeChange} disabled={disabled || submitting} />
        <span className="text-[11px] text-[var(--text-secondary)]">
          `/mode`, `/task`, `/clear`, `/mcp list`, `/model`
        </span>
      </div>

      <div className="relative">
        <textarea
          ref={textareaRef}
          className="w-full min-h-24 resize-none rounded border border-[var(--border)] bg-[var(--bg-tertiary)] p-3 text-sm outline-none focus:border-[var(--accent)]"
          placeholder="Ask anything about this project, or use /task to run the pipeline..."
          value={value}
          onChange={(event) => onChange(event.target.value)}
          disabled={disabled}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && !event.shiftKey) {
              event.preventDefault()
              void executeCommand()
            }
            if (event.key === 'Escape') {
              setMentionStart(null)
            }
          }}
        />

        {mentionStart !== null && fileSuggestions.length > 0 && (
          <div className="absolute left-0 right-0 bottom-[calc(100%+8px)] rounded border border-[var(--border)] bg-[var(--bg-secondary)] shadow-lg overflow-hidden z-20">
            {fileSuggestions.map((item) => (
              <button
                key={item.path}
                className="w-full text-left px-3 py-2 text-sm hover:bg-[var(--bg-tertiary)]"
                onMouseDown={(event) => {
                  event.preventDefault()
                  insertMention(item.path)
                }}
              >
                {item.path}
              </button>
            ))}
          </div>
        )}
      </div>

      {pendingRunId && (
        <p className="text-[11px] text-[var(--warning)]">
          Linked to run {pendingRunId.slice(0, 8)}… — send a message or retry the pipeline with your note.
        </p>
      )}

      <div className="flex justify-end gap-2">
        {pendingRunId && onSendAndRetry && (
          <Button
            variant="secondary"
            onClick={() => {
              const trimmed = value.trim()
              if (!trimmed || disabled) return
              void onSendAndRetry(trimmed, pendingRunId)
            }}
            loading={submitting}
            disabled={disabled || !value.trim()}
          >
            Send and retry
          </Button>
        )}
        <Button onClick={() => void executeCommand()} loading={submitting} disabled={disabled}>
          Send
        </Button>
      </div>
    </div>
  )
}
