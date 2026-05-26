import { RunProgressCard } from '@/components/AgentPanel/RunProgressCard'
import { useUIStore } from '@/store'

interface RunCardProps {
  runId: string
  displayName?: string | null
  status?: string
  onOpen?: () => void
}

/** Thin wrapper — run actions live in the Agents tab. */
export function RunCard({ runId, displayName, status, onOpen }: RunCardProps) {
  const requestOpenRunDrawer = useUIStore((s) => s.requestOpenRunDrawer)
  const setRightPanelTab = useUIStore((s) => s.setRightPanelTab)

  const handleOpen = onOpen ?? (() => {
    setRightPanelTab('agents')
    requestOpenRunDrawer(runId, 'conversation')
  })

  return (
    <RunProgressCard
      runId={runId}
      displayName={displayName}
      status={status}
      showViewLink
      onOpen={handleOpen}
    />
  )
}
