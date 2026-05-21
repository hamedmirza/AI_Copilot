import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '@/api/client'
import { useProjectStore, useEditorStore } from '@/store'
import { showError, showSuccess } from '@/lib/toast'
import { EmptyState, Skeleton } from '@/components/ui/primitives'
import { getLanguage } from '@/lib/utils'
import { FilePlus, FolderPlus, RefreshCw } from 'lucide-react'

export function FileTree() {
  const projectId = useProjectStore((s) => s.currentProjectId)
  const treeItems = useEditorStore((s) => s.treeItems)
  const treeRefreshTick = useEditorStore((s) => s.treeRefreshTick)
  const expandedFolders = useEditorStore((s) => s.expandedFolders)
  const setTreeItems = useEditorStore((s) => s.setTreeItems)
  const toggleFolder = useEditorStore((s) => s.toggleFolder)
  const openTab = useEditorStore((s) => s.openTab)
  const renameTabPath = useEditorStore((s) => s.renameTabPath)
  const [loading, setLoading] = useState(false)
  const [creating, setCreating] = useState<{ parent: string; type: 'file' | 'folder' } | null>(null)
  const [newName, setNewName] = useState('')
  const [renaming, setRenaming] = useState<string | null>(null)
  const [renameValue, setRenameValue] = useState('')
  const [dragPath, setDragPath] = useState<string | null>(null)
  const [dropTarget, setDropTarget] = useState<string | null>(null)
  const [contextMenu, setContextMenu] = useState<{ path: string; x: number; y: number } | null>(null)
  const menuRef = useRef<HTMLDivElement>(null)

  const refresh = useCallback(async () => {
    if (!projectId) return
    setLoading(true)
    try {
      const data = await api.projects.tree(projectId)
      setTreeItems(data.items)
    } catch (e) {
      showError(e)
    } finally {
      setLoading(false)
    }
  }, [projectId, setTreeItems])

  useEffect(() => { refresh() }, [refresh, treeRefreshTick])

  useEffect(() => {
    if (!contextMenu) return
    const close = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setContextMenu(null)
    }
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [contextMenu])

  const openFile = async (path: string) => {
    if (!projectId) return
    try {
      const data = await api.files.read(projectId, path)
      openTab({ path, content: data.content, dirty: false, language: getLanguage(path) })
    } catch (e) {
      showError(e)
    }
  }

  const handleCreate = async () => {
    if (!projectId || !creating || !newName.trim()) return
    const path = creating.parent ? `${creating.parent}/${newName}` : newName
    try {
      await api.files.create(projectId, path, '', creating.type === 'folder')
      setCreating(null)
      setNewName('')
      await refresh()
      if (creating.type === 'file') await openFile(path)
    } catch (e) {
      showError(e)
    }
  }

  const handleDelete = async (path: string) => {
    if (!projectId || !confirm(`Delete ${path}?`)) return
    try {
      await api.files.delete(projectId, path)
      useEditorStore.getState().closeTab(path)
      showSuccess(`Deleted ${path.split('/').pop()}`)
      await refresh()
    } catch (e) {
      showError(e)
    }
  }

  const startRename = (path: string) => {
    setRenaming(path)
    setRenameValue(path.split('/').pop() || path)
  }

  const commitRename = async () => {
    if (!projectId || !renaming || !renameValue.trim()) {
      setRenaming(null)
      return
    }
    const parent = renaming.includes('/') ? renaming.slice(0, renaming.lastIndexOf('/')) : ''
    const newPath = parent ? `${parent}/${renameValue.trim()}` : renameValue.trim()
    if (newPath === renaming) {
      setRenaming(null)
      return
    }
    try {
      await api.files.rename(projectId, renaming, newPath)
      renameTabPath(renaming, newPath)
      showSuccess(`Renamed to ${renameValue.trim()}`)
      setRenaming(null)
      await refresh()
    } catch (e) {
      showError(e)
    }
  }

  const handleMove = async (srcPath: string, destFolder: string) => {
    if (!projectId) return
    const name = srcPath.split('/').pop()!
    const newPath = destFolder ? `${destFolder}/${name}` : name
    if (newPath === srcPath || newPath.startsWith(srcPath + '/')) return
    try {
      await api.files.rename(projectId, srcPath, newPath)
      renameTabPath(srcPath, newPath)
      showSuccess(`Moved to ${newPath}`)
      await refresh()
    } catch (e) {
      showError(e)
    }
  }

  const dirs = treeItems.filter((i) => i.type === 'directory')
  const files = treeItems.filter((i) => i.type === 'file')

  const renderFile = (f: { path: string }, indent = 0) => {
    const isRenaming = renaming === f.path
    return (
      <div
        key={f.path}
        draggable={!isRenaming}
        className={`py-0.5 hover:bg-[var(--bg-tertiary)] cursor-pointer truncate flex items-center ${
          dropTarget === f.path ? 'bg-[var(--accent)]/20' : ''
        }`}
        style={{ paddingLeft: indent * 12 + 8 }}
        onDoubleClick={() => !isRenaming && openFile(f.path)}
        onContextMenu={(e) => {
          e.preventDefault()
          setContextMenu({ path: f.path, x: e.clientX, y: e.clientY })
        }}
        onDragStart={(e) => {
          setDragPath(f.path)
          e.dataTransfer.effectAllowed = 'move'
        }}
        onDragEnd={() => { setDragPath(null); setDropTarget(null) }}
      >
        {isRenaming ? (
          <input
            autoFocus
            className="w-full bg-[var(--bg-tertiary)] border border-[var(--border)] px-1 py-0 rounded text-sm"
            value={renameValue}
            onChange={(e) => setRenameValue(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') commitRename()
              if (e.key === 'Escape') setRenaming(null)
            }}
            onBlur={commitRename}
          />
        ) : (
          f.path.split('/').pop()
        )}
      </div>
    )
  }

  const renderDir = (d: { path: string }) => (
    <div key={d.path}>
      <div
        className={`flex items-center gap-1 px-2 py-0.5 hover:bg-[var(--bg-tertiary)] cursor-pointer ${
          dropTarget === d.path ? 'bg-[var(--accent)]/20 ring-1 ring-[var(--accent)]' : ''
        }`}
        onClick={() => toggleFolder(d.path)}
        onDragOver={(e) => {
          e.preventDefault()
          if (dragPath && dragPath !== d.path) setDropTarget(d.path)
        }}
        onDragLeave={() => setDropTarget(null)}
        onDrop={(e) => {
          e.preventDefault()
          if (dragPath) handleMove(dragPath, d.path)
          setDragPath(null)
          setDropTarget(null)
        }}
      >
        <span>{expandedFolders[d.path] !== false ? '▼' : '▶'}</span>
        <span>{d.path.split('/').pop()}</span>
      </div>
      {expandedFolders[d.path] !== false &&
        files.filter((f) => {
          const rel = f.path.slice(d.path.length + 1)
          return f.path.startsWith(d.path + '/') && !rel.includes('/')
        }).map((f) => renderFile(f, 2))}
    </div>
  )

  if (!projectId) {
    return <EmptyState title="No project selected" description="Create or select a project to browse files" />
  }

  if (loading && treeItems.length === 0) {
    return (
      <div className="p-3 space-y-2">
        {[1, 2, 3, 4].map((i) => <Skeleton key={i} className="h-5 w-full" />)}
      </div>
    )
  }

  return (
    <div className="h-full flex flex-col relative">
      {contextMenu && (
        <div
          ref={menuRef}
          className="fixed z-50 bg-[var(--bg-secondary)] border border-[var(--border)] rounded shadow-lg py-1 text-sm min-w-[140px]"
          style={{ left: contextMenu.x, top: contextMenu.y }}
        >
          <button
            className="w-full text-left px-3 py-1 hover:bg-[var(--bg-tertiary)]"
            onClick={() => { startRename(contextMenu.path); setContextMenu(null) }}
          >
            Rename
          </button>
          <button
            className="w-full text-left px-3 py-1 hover:bg-[var(--bg-tertiary)] text-[var(--error)]"
            onClick={() => { handleDelete(contextMenu.path); setContextMenu(null) }}
          >
            Delete
          </button>
          <button
            className="w-full text-left px-3 py-1 hover:bg-[var(--bg-tertiary)]"
            onClick={() => {
              navigator.clipboard.writeText(contextMenu.path)
              showSuccess('Path copied')
              setContextMenu(null)
            }}
          >
            Copy path
          </button>
        </div>
      )}
      <div className="flex items-center gap-1 px-2 py-1 border-b border-[var(--border)]">
        <button title="New File" className="p-1 hover:bg-[var(--bg-tertiary)] rounded" onClick={() => setCreating({ parent: '', type: 'file' })}>
          <FilePlus size={14} />
        </button>
        <button title="New Folder" className="p-1 hover:bg-[var(--bg-tertiary)] rounded" onClick={() => setCreating({ parent: '', type: 'folder' })}>
          <FolderPlus size={14} />
        </button>
        <button title="Refresh" className="p-1 hover:bg-[var(--bg-tertiary)] rounded ml-auto" onClick={refresh}>
          <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
        </button>
      </div>
      <div className="flex-1 overflow-auto p-1 text-sm">
        {creating && (
          <div className="px-2 py-1">
            <input
              autoFocus
              className="w-full bg-[var(--bg-tertiary)] border border-[var(--border)] px-2 py-0.5 rounded text-sm"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') handleCreate()
                if (e.key === 'Escape') setCreating(null)
              }}
              placeholder={creating.type === 'file' ? 'filename.py' : 'folder name'}
            />
          </div>
        )}
        {dirs.map(renderDir)}
        {files.filter((f) => !f.path.includes('/')).map((f) => renderFile(f))}
        {treeItems.length === 0 && (
          <EmptyState title="Empty workspace" description="Create a file to get started" />
        )}
      </div>
    </div>
  )
}
