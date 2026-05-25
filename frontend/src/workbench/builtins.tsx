import { Files, GitBranch, Bot, Search, Globe, LayoutGrid, BarChart3 } from 'lucide-react'
import { KanbanWorkbenchPanel } from '@/components/Kanban/KanbanWorkbenchPanel'
import { ReportingWorkbenchPanel } from '@/components/Reporting/ReportingWorkbenchPanel'
import { FileTree } from '@/components/FileTree/FileTree'
import { SearchPanel } from '@/components/Search/SearchPanel'
import { GitPanel } from '@/components/GitPanel/GitPanel'
import { AgentPanel } from '@/components/AgentPanel/AgentPanel'
import { BrowserPanel } from '@/components/Browser/BrowserPanel'
import { ClarificationDrawerPage } from '@/pages/ClarificationDrawerPage'
import { useUIStore } from '@/store'
import { registerContribution } from './registry'

function GitSidebarPanel() {
  const activePanel = useUIStore((s) => s.activePanel)
  const bottomTab = useUIStore((s) => s.bottomTab)
  const bottomPanelCollapsed = useUIStore((s) => s.bottomPanelCollapsed)
  const pollWhenVisible =
    activePanel === 'git' || (bottomTab === 'git' && !bottomPanelCollapsed)
  return <GitPanel pollWhenVisible={pollWhenVisible} />
}

registerContribution({
  id: 'explorer',
  zone: 'sidebar',
  title: 'Explorer',
  icon: Files,
  order: 0,
  Component: FileTree,
})

registerContribution({
  id: 'search',
  zone: 'sidebar',
  title: 'Search',
  icon: Search,
  order: 1,
  Component: SearchPanel,
})

registerContribution({
  id: 'git',
  zone: 'sidebar',
  title: 'Git',
  icon: GitBranch,
  order: 2,
  Component: GitSidebarPanel,
})

registerContribution({
  id: 'agents',
  zone: 'sidebar',
  title: 'Agents',
  icon: Bot,
  order: 3,
  Component: AgentPanel,
})

registerContribution({
  id: 'browser',
  zone: 'center',
  title: 'Browser',
  icon: Globe,
  order: 0,
  Component: BrowserPanel,
})

registerContribution({
  id: 'kanban',
  zone: 'center',
  title: 'Kanban',
  icon: LayoutGrid,
  order: 1,
  Component: KanbanWorkbenchPanel,
})

registerContribution({
  id: 'reporting',
  zone: 'center',
  title: 'Reporting',
  icon: BarChart3,
  order: 2,
  Component: ReportingWorkbenchPanel,
})

registerContribution({
  id: 'clarification-drawer',
  zone: 'center',
  title: 'Clarification Drawer',
  icon: LayoutGrid,
  order: 3,
  Component: ClarificationDrawerPage,
})
