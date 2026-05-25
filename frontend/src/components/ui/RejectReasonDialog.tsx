import { useRef, useState, useEffect } from 'react'
import { cn } from '@/lib/utils'

interface RejectReasonDialogProps {
  open: boolean
  title?: string
  placeholder?: string
  onSubmit: (reason: string) => void
  onCancel: () => void
}

export function RejectReasonDialog({
  open,
  title = 'Request Changes',
  placeholder,
  onSubmit,
  onCancel,
}: RejectReasonDialogProps) {
  const [value, setValue] = useState('')
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    if (open) {
      setValue('')
      // Focus the textarea when modal opens
      setTimeout(() => textareaRef.current?.focus(), 50)
    }
  }, [open])

  if (!open) return null

  const handleSubmit = () => {
    const trimmed = value.trim()
    if (!trimmed) return
    onSubmit(trimmed)
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
      handleSubmit()
    }
    if (e.key === 'Escape') {
      onCancel()
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center"
      role="dialog"
      aria-modal="true"
      aria-labelledby="reject-dialog-title"
    >
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/60"
        onClick={onCancel}
        aria-hidden="true"
      />

      {/* Panel */}
      <div className="relative z-10 w-full max-w-md rounded-lg border border-[var(--border)] bg-[var(--bg-secondary)] p-6 shadow-xl">
        <h2
          id="reject-dialog-title"
          className="mb-3 text-base font-semibold text-[var(--text-primary)]"
        >
          {title}
        </h2>

        <textarea
          ref={textareaRef}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={placeholder}
          rows={4}
          className={cn(
            'w-full resize-y rounded border border-[var(--border)] bg-[var(--bg-tertiary)]',
            'px-3 py-2 text-sm text-[var(--text-primary)] placeholder-[var(--text-secondary)]',
            'focus:outline-none focus:ring-1 focus:ring-[var(--accent)]',
            'min-h-[80px]',
          )}
        />

        <p className="mb-4 mt-1 text-xs text-[var(--text-secondary)]">
          Tip: ⌘↵ to submit
        </p>

        <div className="flex justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            className="rounded px-3 py-1.5 text-sm font-medium text-[var(--text-secondary)] transition-colors hover:bg-[var(--bg-tertiary)]"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={handleSubmit}
            disabled={!value.trim()}
            className={cn(
              'rounded px-3 py-1.5 text-sm font-medium text-white transition-colors',
              'bg-[var(--accent)] hover:bg-[var(--accent-hover)]',
              'disabled:opacity-40 disabled:cursor-not-allowed',
            )}
          >
            Submit
          </button>
        </div>
      </div>
    </div>
  )
}
