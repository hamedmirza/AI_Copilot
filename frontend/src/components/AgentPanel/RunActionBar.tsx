import { useMemo } from 'react'
import { Button } from '@/components/ui/primitives'
import {
  canRollbackPromote,
  canRollbackWorkspace,
  isResumableStatus,
  isRetryableStatus,
} from '@/types/runs'
import type { PromoteSnapshot } from '@/types/runs'
import type { RunEvent } from '@/store'

interface RunActionBarProps {
  status: string
  busy?: boolean
  events?: RunEvent[]
  promoteSnapshot?: PromoteSnapshot | null
  onApprove?: () => void
  onReject?: () => void
  onRetry?: () => void
  onResume?: () => void
  onContinueVisual?: () => void
  onRollbackWorkspace?: () => void
  onRollbackPromote?: () => void
  className?: string
}

export function RunActionBar({
  status,
  busy,
  events = [],
  promoteSnapshot,
  onApprove,
  onReject,
  onRetry,
  onResume,
  onContinueVisual,
  onRollbackWorkspace,
  onRollbackPromote,
  className = '',
}: RunActionBarProps) {
  const needsBrowserClient = useMemo(
    () => events.some((e) => String(e.type || '') === 'browser_client_required'),
    [events],
  )
  const visualBlocked = status === 'blocked' && needsBrowserClient

  return (
    <div className={`flex flex-wrap gap-2 ${className}`}>
      {visualBlocked && onContinueVisual && (
        <Button variant="secondary" className="text-xs" disabled={busy} onClick={onContinueVisual}>
          Continue visual
        </Button>
      )}
      {onApprove && (
        <Button disabled={status !== 'awaiting_approval' || busy} onClick={onApprove}>
          Approve
        </Button>
      )}
      {onReject && (
        <Button variant="danger" disabled={status !== 'awaiting_approval' || busy} onClick={onReject}>
          Reject
        </Button>
      )}
      {onRetry && (
        <Button variant="secondary" disabled={!isRetryableStatus(status) || busy} onClick={onRetry}>
          Retry
        </Button>
      )}
      {onResume && isResumableStatus(status) && (
        <Button variant="secondary" disabled={busy} onClick={onResume} title="Re-queue a stuck pending or running run">
          Resume
        </Button>
      )}
      {onRollbackWorkspace && canRollbackWorkspace(status) && (
        <Button variant="secondary" disabled={busy} onClick={onRollbackWorkspace}>
          Discard workspace
        </Button>
      )}
      {onRollbackPromote && canRollbackPromote(status, promoteSnapshot) && (
        <Button variant="danger" disabled={busy} onClick={onRollbackPromote}>
          Undo promotion
        </Button>
      )}
    </div>
  )
}
