import { Files, GitBranch, Bot, Settings, Search } from 'lucide-react'
import { useUIStore, useAppStore } from '@/store'
import type { Panel } from '@/store'

const icons: { id: Panel; Icon: typeof Files; title: string }[] = [
  { id: 'explorer', Icon: Files, title: 'Explorer' },
  { id: 'search', Icon: Search, title: 'Search' },
  { id: 'git', Icon: GitBranch, title: 'Git' },
  { id: 'agents', Icon: Bot, title: 'Agents' },
  { id: 'settings', Icon: Settings, title: 'Settings' },
]

export function ActivityBar() {
  const activePanel = useUIStore((s) => s.activePanel)
  const setActivePanel = useUIStore((s) => s.setActivePanel)
  const setShowSettings = useAppStore((s) => s.setShowSettings)

  return (
    <div className="w-12 flex flex-col items-center py-2 bg-[#333333] border-r border-[var(--border)] shrink-0">
      {icons.map(({ id, Icon, title }) => (
        <button
          key={id}
          title={title}
          className={`w-10 h-10 flex items-center justify-center mb-1 rounded ${
            activePanel === id ? 'text-white border-l-2 border-[var(--accent)] bg-[#404040]' : 'text-[var(--text-secondary)] hover:text-white'
          }`}
          onClick={() => {
            if (id === 'settings') {
              setShowSettings(true)
            } else {
              setActivePanel(id)
            }
          }}
        >
          <Icon size={22} />
        </button>
      ))}
    </div>
  )
}
