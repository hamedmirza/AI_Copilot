import { Files, GitBranch, Bot, Search, Globe, Columns3 } from 'lucide-react'
import { GitSidebarPanel } from './GitSidebarPanel'
import {
  AgentWorkbenchPanel,
  BrowserWorkbenchPanel,
  FileTreePanel,
  KanbanCenterPanel,
  SearchWorkbenchPanel,
} from './lazyPanels'
import { registerContribution } from './registry'

registerContribution({
  id: 'explorer',
  zone: 'sidebar',
  title: 'Explorer',
  icon: Files,
  order: 0,
  Component: FileTreePanel,
})

registerContribution({
  id: 'search',
  zone: 'sidebar',
  title: 'Search',
  icon: Search,
  order: 1,
  Component: SearchWorkbenchPanel,
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
  Component: AgentWorkbenchPanel,
})

registerContribution({
  id: 'browser',
  zone: 'center',
  title: 'Browser',
  icon: Globe,
  order: 0,
  Component: BrowserWorkbenchPanel,
})

registerContribution({
  id: 'kanban',
  zone: 'center',
  title: 'Kanban',
  icon: Columns3,
  order: 1,
  Component: KanbanCenterPanel,
})
