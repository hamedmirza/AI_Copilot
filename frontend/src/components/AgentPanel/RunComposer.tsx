import { useMemo, useState } from 'react'
import { Button } from '@/components/ui/primitives'
import { runComposerLabels } from './runComposerLabels'

interface RunComposerProps {
  status: string
  busy?: boolean
  onClarify: (answer: string) => void | Promise<void>
  onRetry: (feedback: string) => void | Promise<void>
  onOpenChat?: () => void
  onApprove?: () => void
}

export function RunComposer({
  status,
  busy,
  onClarify,
  onRetry,
  onOpenChat,
  onApprove,
}: RunComposerProps) {
  const [value, setValue] = useState('')
  const labels = useMemo(() => runComposerLabels(status), [status])

  const handlePrimary = async () => {
    const trimmed = value.trim()
    if (busy || labels.primaryDisabled) return
    if (status === 'awaiting_clarification') {
      if (!trimmed) return
      await onClarify(trimmed)
      setValue('')
      return
    }
    if (status === 'awaiting_approval') {
      onApprove?.()
      return
    }
    if (['changes_requested', 'failed', 'blocked', 'completed'].includes(status)) {
      await onRetry(trimmed)
      if (trimmed) setValue('')
      return
    }
  }

  return (
    <div className="shrink-0 border-t border-[var(--border)] bg-[var(--bg-secondary)] p-3 space-y-2">
      {labels.hint && (
        <p className="text-[11px] text-[var(--text-secondary)]">{labels.hint}</p>
      )}
      <textarea
        className="w-full min-h-[72px] resize-none rounded border border-[var(--border)] bg-[var(--bg-tertiary)] p-2 text-sm outline-none focus:border-[var(--accent)] disabled:opacity-60"
        placeholder={labels.placeholder}
        value={value}
        onChange={(e) => setValue(e.target.value)}
        disabled={busy || (status === 'running')}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && !e.shiftKey && !busy && labels.showPrimary) {
            e.preventDefault()
            void handlePrimary()
          }
        }}
      />
      <div className="flex justify-end gap-2 flex-wrap">
        {onOpenChat && (
          <Button variant="ghost" className="text-xs" disabled={busy} onClick={onOpenChat}>
            Open in Chat
          </Button>
        )}
        {labels.showPrimary && (
          <Button
            loading={busy}
            disabled={busy || labels.primaryDisabled || (status === 'awaiting_clarification' && !value.trim())}
            onClick={() => void handlePrimary()}
          >
            {labels.primaryLabel}
          </Button>
        )}
      </div>
    </div>
  )
}
