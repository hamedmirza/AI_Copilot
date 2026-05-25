import { MessageSquare, Settings } from 'lucide-react'
import { useUIStore, useAppStore } from '@/store'
import type { CenterView, SidebarPanel } from '@/store'
import { getContributions } from '@/workbench/registry'

export function ActivityBar() {
  const activePanel = useUIStore((s) => s.activePanel)
  const sidebarCollapsed = useUIStore((s) => s.sidebarCollapsed)
  const openSidebarPanel = useUIStore((s) => s.openSidebarPanel)
  const toggleSidebar = useUIStore((s) => s.toggleSidebar)
  const activeCenterView = useUIStore((s) => s.activeCenterView)
  const toggleCenterView = useUIStore((s) => s.toggleCenterView)
  const rightPanelCollapsed = useUIStore((s) => s.rightPanelCollapsed)
  const rightPanelTab = useUIStore((s) => s.rightPanelTab)
  const agentPanelPlacement = useUIStore((s) => s.agentPanelPlacement)
  const toggleRightPanel = useUIStore((s) => s.toggleRightPanel)
  const setRightPanelTab = useUIStore((s) => s.setRightPanelTab)
  const openAgentsPanel = useUIStore((s) => s.openAgentsPanel)
  const setShowSettings = useAppStore((s) => s.setShowSettings)

  const sidebarItems = getContributions('sidebar')
  const centerItems = getContributions('center')

  const handleSidebarClick = (id: string) => {
    const panel = id as SidebarPanel
    if (activePanel === panel && !sidebarCollapsed) {
      toggleSidebar()
    } else {
      openSidebarPanel(panel)
    }
  }

  const chatActive = !rightPanelCollapsed && rightPanelTab === 'chat'
  const agentsOnRight = agentPanelPlacement === 'right'
  const agentsActive = agentsOnRight
    ? !rightPanelCollapsed && rightPanelTab === 'agents'
    : activePanel === 'agents' && !sidebarCollapsed

  const handleAgentsClick = () => {
    if (agentsOnRight) {
      if (agentsActive) {
        toggleRightPanel()
      } else {
        openAgentsPanel()
      }
      return
    }
    handleSidebarClick('agents')
  }

  return (
    <div className="w-12 flex flex-col items-center py-2 bg-[#333333] border-r border-[var(--border)] shrink-0">
      {sidebarItems.map(({ id, icon: Icon, title }) => {
        if (id === 'agents') {
          return (
            <button
              key={id}
              title={title}
              className={`w-10 h-10 flex items-center justify-center mb-1 rounded ${
                agentsActive
                  ? 'text-white border-l-2 border-[var(--accent)] bg-[#404040]'
                  : 'text-[var(--text-secondary)] hover:text-white'
              }`}
              onClick={handleAgentsClick}
            >
              <Icon size={22} />
            </button>
          )
        }
        return (
          <button
            key={id}
            title={title}
            className={`w-10 h-10 flex items-center justify-center mb-1 rounded ${
              activePanel === id && !sidebarCollapsed
                ? 'text-white border-l-2 border-[var(--accent)] bg-[#404040]'
                : 'text-[var(--text-secondary)] hover:text-white'
            }`}
            onClick={() => handleSidebarClick(id)}
          >
            <Icon size={22} />
          </button>
        )
      })}

      {centerItems.map(({ id, icon: Icon, title }) => (
        <button
          key={id}
          title={title}
          className={`w-10 h-10 flex items-center justify-center mb-1 rounded ${
            activeCenterView === id
              ? 'text-white border-l-2 border-[var(--accent)] bg-[#404040]'
              : 'text-[var(--text-secondary)] hover:text-white'
          }`}
          onClick={() => toggleCenterView(id as CenterView)}
        >
          <Icon size={22} />
        </button>
      ))}

      <button
        title="Settings"
        className="w-10 h-10 flex items-center justify-center mb-1 rounded text-[var(--text-secondary)] hover:text-white"
        onClick={() => setShowSettings(true)}
      >
        <Settings size={22} />
      </button>

      <button
        title="Chat"
        className={`w-10 h-10 mt-auto flex items-center justify-center rounded ${
          chatActive
            ? 'text-white border-l-2 border-[var(--accent)] bg-[#404040]'
            : 'text-[var(--text-secondary)] hover:text-white'
        }`}
        onClick={() => {
          if (chatActive) {
            toggleRightPanel()
          } else {
            if (rightPanelCollapsed) toggleRightPanel()
            setRightPanelTab('chat')
          }
        }}
      >
        <MessageSquare size={22} />
      </button>
    </div>
  )
}
