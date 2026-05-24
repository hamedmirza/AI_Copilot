import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api } from '@/api/client'
import { useEditorStore, useProjectStore } from '@/store'
import { showError } from '@/lib/toast'
import { EmptyState, Skeleton } from '@/components/ui/primitives'
import { getLanguage } from '@/lib/utils'
import { Search } from 'lucide-react'

export function SearchPanel() {
  const projectId = useProjectStore((s) => s.currentProjectId)
  const treeItems = useEditorStore((s) => s.treeItems)
  const treeRefreshTick = useEditorStore((s) => s.treeRefreshTick)
  const setTreeItems = useEditorStore((s) => s.setTreeItems)
  const openTab = useEditorStore((s) => s.openTab)
  const [query, setQuery] = useState('')
  const [loading, setLoading] = useState(false)
  const lastLoadedProjectRef = useRef<string | null>(null)
  const lastRefreshTickRef = useRef<number>(-1)

  const refresh = useCallback(async (force = false) => {
    if (!projectId) return
    if (!force && lastLoadedProjectRef.current === projectId && treeItems.length > 0) return
    setLoading(true)
    try {
      const data = await api.projects.tree(projectId)
      setTreeItems(data.items)
      lastLoadedProjectRef.current = projectId
    } catch (e) {
      showError(e)
    } finally {
      setLoading(false)
    }
  }, [projectId, setTreeItems, treeItems.length])

  useEffect(() => {
    if (!projectId) {
      lastLoadedProjectRef.current = null
      lastRefreshTickRef.current = treeRefreshTick
      return
    }
    const projectChanged = lastLoadedProjectRef.current !== projectId
    const refreshChanged = lastRefreshTickRef.current !== treeRefreshTick
    const forceRefresh = !projectChanged && refreshChanged
    if (projectChanged || forceRefresh || treeItems.length === 0) {
      void refresh(forceRefresh)
    }
    lastRefreshTickRef.current = treeRefreshTick
  }, [projectId, refresh, treeItems.length, treeRefreshTick])

  const results = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return []
    return treeItems
      .filter((i) => i.type === 'file' && i.path.toLowerCase().includes(q))
      .slice(0, 50)
  }, [query, treeItems])

  const openFile = async (path: string) => {
    if (!projectId) return
    try {
      const data = await api.files.read(projectId, path)
      openTab({ path, content: data.content, dirty: false, language: getLanguage(path) })
    } catch (e) {
      showError(e)
    }
  }

  if (!projectId) {
    return <EmptyState title="No project selected" description="Select a project to search files" />
  }

  return (
    <div className="h-full flex flex-col">
      <div className="flex items-center gap-2 px-2 py-2 border-b border-[var(--border)]">
        <Search size={14} className="text-[var(--text-secondary)] shrink-0" />
        <input
          autoFocus
          className="flex-1 bg-[var(--bg-tertiary)] border border-[var(--border)] rounded px-2 py-1 text-sm outline-none"
          placeholder="Search files by name..."
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
      </div>
      <div className="flex-1 overflow-auto p-1 text-sm">
        {loading && treeItems.length === 0 ? (
          <div className="p-3 space-y-2">
            {[1, 2, 3].map((i) => <Skeleton key={i} className="h-5 w-full" />)}
          </div>
        ) : query.trim() === '' ? (
          <EmptyState title="Search files" description="Type a filename or path fragment to filter" />
        ) : results.length === 0 ? (
          <EmptyState title="No matches" description={`No files matching "${query.trim()}"`} />
        ) : (
          results.map((f) => (
            <button
              key={f.path}
              type="button"
              className="w-full text-left px-2 py-1 hover:bg-[var(--bg-tertiary)] cursor-pointer truncate rounded"
              onClick={() => openFile(f.path)}
              title={f.path}
            >
              <span className="text-[var(--text-primary)]">{f.path.split('/').pop()}</span>
              <span className="text-[var(--text-secondary)] text-xs ml-2">{f.path}</span>
            </button>
          ))
        )}
      </div>
    </div>
  )
}
