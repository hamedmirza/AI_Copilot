import { PanelLeft, PanelRight } from 'lucide-react'
import { useUIStore, type AgentPanelPlacement } from '@/store'

interface AgentPanelLayoutToggleProps {
  compact?: boolean
}

export function AgentPanelLayoutToggle({ compact = false }: AgentPanelLayoutToggleProps) {
  const placement = useUIStore((s) => s.agentPanelPlacement)
  const setAgentPanelPlacement = useUIStore((s) => s.setAgentPanelPlacement)

  const next: AgentPanelPlacement = placement === 'sidebar' ? 'right' : 'sidebar'
  const label = placement === 'sidebar' ? 'Move pipeline to right panel' : 'Move pipeline to left sidebar'
  const shortLabel = placement === 'sidebar' ? 'Right panel' : 'Left sidebar'

  return (
    <button
      type="button"
      title={label}
      aria-label={label}
      className={
        compact
          ? 'p-1 rounded text-[var(--text-secondary)] hover:text-white hover:bg-[var(--bg-tertiary)]'
          : 'flex items-center gap-1 text-xs px-2 py-1 rounded border border-[var(--border)] text-[var(--text-secondary)] hover:text-white hover:bg-[var(--bg-tertiary)]'
      }
      onClick={() => setAgentPanelPlacement(next)}
    >
      {placement === 'sidebar' ? <PanelRight size={compact ? 14 : 16} /> : <PanelLeft size={compact ? 14 : 16} />}
      {!compact && <span>{shortLabel}</span>}
    </button>
  )
}
