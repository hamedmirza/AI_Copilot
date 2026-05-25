import { RunStatusChip } from '@/components/AgentPanel/RunStatusChip'
import { useUIStore } from '@/store'
import type { RunEvent } from '@/store'

interface RunCardProps {
  runId: string
  displayName?: string | null
  events: RunEvent[]
  status?: string
  onOpen?: () => void
}

/** Thin wrapper — run actions live in the Agents tab. */
export function RunCard({ runId, displayName, events, status, onOpen }: RunCardProps) {
  const requestOpenRunDrawer = useUIStore((s) => s.requestOpenRunDrawer)
  const setRightPanelTab = useUIStore((s) => s.setRightPanelTab)

  const handleOpen = onOpen ?? (() => {
    setRightPanelTab('agents')
    requestOpenRunDrawer(runId, 'conversation')
  })

  return (
    <RunStatusChip
      runId={runId}
      displayName={displayName}
      status={status}
      events={events}
      showViewLink
      onOpen={handleOpen}
    />
  )
}
