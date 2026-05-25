import { useCallback, useEffect, useState } from 'react'
import { DndProvider } from 'react-dnd'
import { HTML5Backend } from 'react-dnd-html5-backend'
import { api } from '@/api/client'
import { useProjectStore } from '@/store'
import Column from './Column'

interface Task {
  id: string
  title: string
  description: string
  status: 'todo' | 'in-progress' | 'review' | 'done'
}

export function KanbanWorkbenchPanel() {
  const projectId = useProjectStore((s) => s.currentProjectId)
  const projects = useProjectStore((s) => s.projects)
  const [tasks, setTasks] = useState<Task[]>([])
  const [loading, setLoading] = useState(false)

  const loadTasks = useCallback(async (id: string) => {
    setLoading(true)
    try {
      const data = await api.kanban.tasks(id)
      setTasks(
        (data as Array<Record<string, unknown>>).map((row) => ({
          id: String(row.id ?? ''),
          title: String(row.title ?? ''),
          description: String(row.description ?? ''),
          status: (row.status as Task['status']) || 'todo',
        })),
      )
    } catch (e) {
      console.error(e)
      setTasks([])
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (!projectId) {
      setTasks([])
      return
    }
    void loadTasks(projectId)
  }, [projectId, loadTasks])

  const handleStatusChange = async (taskId: string, status: Task['status']) => {
    try {
      await api.kanban.patchTask(taskId, status)
      if (projectId) await loadTasks(projectId)
    } catch (e) {
      console.error(e)
    }
  }

  if (!projectId) {
    return (
      <p className="p-4 text-sm text-[var(--text-secondary)]">
        Select a project in Manage Projects to use the Kanban board.
      </p>
    )
  }

  const projectName = String(projects.find((p) => p.id === projectId)?.name ?? projectId)

  const columns: { id: Task['status']; title: string }[] = [
    { id: 'todo', title: 'To Do' },
    { id: 'in-progress', title: 'In Progress' },
    { id: 'review', title: 'Review' },
    { id: 'done', title: 'Done' },
  ]

  return (
    <div className="flex flex-col h-full overflow-hidden p-3">
      <h2 className="text-sm font-medium mb-3 shrink-0">{projectName} — Kanban</h2>
      <p className="text-[11px] text-[var(--text-secondary)] mb-2 shrink-0">
        Stub task data from the API until persistent Kanban storage ships. See docs/KANBAN_STUB_DATA.md.
      </p>
      {loading ? (
        <p className="text-xs text-[var(--text-secondary)]">Loading tasks…</p>
      ) : (
        <DndProvider backend={HTML5Backend}>
          <div className="flex gap-3 flex-1 min-h-0 overflow-x-auto">
            {columns.map((col) => (
              <Column
                key={col.id}
                title={col.title}
                status={col.id}
                tasks={tasks.filter((t) => t.status === col.id)}
                onDrop={handleStatusChange}
              />
            ))}
          </div>
        </DndProvider>
      )}
    </div>
  )
}
