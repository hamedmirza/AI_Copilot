import { cn } from '@/lib/utils'

interface ConfirmModalProps {
  open: boolean
  title: string
  description?: string
  confirmLabel?: string
  cancelLabel?: string
  variant?: 'default' | 'destructive'
  onConfirm: () => void
  onCancel: () => void
}

export function ConfirmModal({
  open,
  title,
  description,
  confirmLabel = 'Confirm',
  cancelLabel = 'Cancel',
  variant = 'default',
  onConfirm,
  onCancel,
}: ConfirmModalProps) {
  if (!open) return null

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center"
      role="dialog"
      aria-modal="true"
      aria-labelledby="confirm-modal-title"
    >
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/60"
        onClick={onCancel}
        aria-hidden="true"
      />

      {/* Panel */}
      <div className="relative z-10 w-full max-w-sm rounded-lg border border-[var(--border)] bg-[var(--bg-secondary)] p-6 shadow-xl">
        <h2
          id="confirm-modal-title"
          className="mb-2 text-base font-semibold text-[var(--text-primary)]"
        >
          {title}
        </h2>

        {description && (
          <p className="mb-5 text-sm text-[var(--text-secondary)]">{description}</p>
        )}

        <div className="flex justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            className="rounded px-3 py-1.5 text-sm font-medium text-[var(--text-secondary)] transition-colors hover:bg-[var(--bg-tertiary)]"
          >
            {cancelLabel}
          </button>
          <button
            type="button"
            onClick={onConfirm}
            className={cn(
              'rounded px-3 py-1.5 text-sm font-medium text-white transition-colors',
              variant === 'destructive'
                ? 'bg-[var(--error)] hover:opacity-90'
                : 'bg-[var(--accent)] hover:bg-[var(--accent-hover)]',
            )}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  )
}
