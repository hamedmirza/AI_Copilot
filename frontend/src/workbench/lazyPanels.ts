import { lazy } from 'react'

export const FileTreePanel = lazy(async () => ({ default: (await import('@/components/FileTree/FileTree')).FileTree }))
export const SearchWorkbenchPanel = lazy(async () => ({ default: (await import('@/components/Search/SearchPanel')).SearchPanel }))
export const AgentWorkbenchPanel = lazy(async () => ({ default: (await import('@/components/AgentPanel/AgentPanel')).AgentPanel }))
export const BrowserWorkbenchPanel = lazy(async () => ({ default: (await import('@/components/Browser/BrowserPanel')).BrowserPanel }))
export const KanbanCenterPanel = lazy(async () => ({ default: (await import('@/components/Kanban/KanbanWorkbenchPanel')).KanbanWorkbenchPanel }))
