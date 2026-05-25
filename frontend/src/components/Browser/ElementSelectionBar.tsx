import { Copy, MessageSquarePlus, Sparkles, X } from 'lucide-react'
import type { PageElementSelection } from '@/store'
import { Button } from '@/components/ui/primitives'
import { formatElementLabel } from '@/lib/pageElementContext'
import { showError, showSuccess } from '@/lib/toast'

interface ElementSelectionBarProps {
  selection: PageElementSelection
  uiTaskDisabled?: boolean
  uiTaskDisabledReason?: string
  onFixInChat: () => void
  onUiTask: () => void
  onClear: () => void
}

export function ElementSelectionBar({
  selection,
  uiTaskDisabled,
  uiTaskDisabledReason,
  onFixInChat,
  onUiTask,
  onClear,
}: ElementSelectionBarProps) {
  const copySelector = async () => {
    try {
      await navigator.clipboard.writeText(selection.selector)
      showSuccess('Selector copied')
    } catch (error) {
      showError(error)
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-2 border-b border-[var(--border)] bg-[var(--bg-secondary)] px-3 py-2 shrink-0">
      <div className="min-w-0 flex-1">
        <p className="text-[11px] uppercase tracking-wide text-[var(--text-secondary)]">Selected element</p>
        <p className="truncate text-sm text-[var(--text-primary)]" title={selection.selector}>
          {formatElementLabel(selection)}
        </p>
      </div>

      <div className="flex items-center gap-2 flex-wrap">
        <Button variant="secondary" className="text-xs" onClick={onFixInChat}>
          <MessageSquarePlus className="h-4 w-4" />
          <span>Fix in Chat</span>
        </Button>
        <Button
          variant="secondary"
          className="text-xs"
          onClick={onUiTask}
          disabled={uiTaskDisabled}
          title={uiTaskDisabledReason}
        >
          <Sparkles className="h-4 w-4" />
          <span>UI Task</span>
        </Button>
        <Button variant="ghost" className="text-xs" onClick={() => void copySelector()}>
          <Copy className="h-4 w-4" />
          <span>Copy selector</span>
        </Button>
        <Button variant="ghost" className="text-xs" onClick={onClear}>
          <X className="h-4 w-4" />
          <span>Clear</span>
        </Button>
      </div>
    </div>
  )
}
