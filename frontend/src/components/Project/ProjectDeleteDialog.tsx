import { useState } from 'react'
import { api } from '@/api/client'
import { useProjectStore } from '@/store'
import { showError, showSuccess } from '@/lib/toast'
import { Button } from '@/components/ui/primitives'

interface Props {
  project: { id: string; name: string }
  onClose: () => void
}

export function ProjectDeleteDialog({ project, onClose }: Props) {
  const { projects, setProjects, setCurrentProject, currentProjectId } = useProjectStore()
  const [confirmName, setConfirmName] = useState('')
  const [deleting, setDeleting] = useState(false)
  const [error, setError] = useState('')

  const canDelete = confirmName === project.name

  const handleDelete = async () => {
    if (!canDelete) {
      setError('Project name must match exactly')
      return
    }
    setDeleting(true)
    setError('')
    try {
      await api.projects.delete(project.id)
      const remaining = projects.filter((p) => String(p.id) !== project.id)
      setProjects(remaining)
      if (currentProjectId === project.id) {
        setCurrentProject(remaining.length > 0 ? String(remaining[0].id) : null)
      }
      showSuccess(`Deleted project "${project.name}"`)
      onClose()
    } catch (e) {
      showError(e)
    } finally {
      setDeleting(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/60 z-50 flex items-center justify-center">
      <div className="bg-[var(--bg-secondary)] border border-[var(--border)] rounded-lg p-6 w-[420px]">
        <h2 className="text-lg font-medium mb-2 text-[var(--error)]">Delete Project</h2>
        <p className="text-sm text-[var(--text-secondary)] mb-4">
          This permanently removes <strong className="text-[var(--text-primary)]">{project.name}</strong> and all
          associated runs. This action cannot be undone.
        </p>
        <label className="block text-xs text-[var(--text-secondary)] mb-1">
          Type <span className="text-[var(--text-primary)]">{project.name}</span> to confirm
        </label>
        <input
          autoFocus
          className="w-full bg-[var(--bg-tertiary)] border border-[var(--border)] rounded px-3 py-2 text-sm mb-2"
          value={confirmName}
          onChange={(e) => { setConfirmName(e.target.value); setError('') }}
          placeholder={project.name}
        />
        {error && <p className="text-[var(--error)] text-xs mb-2">{error}</p>}
        <div className="flex gap-2 justify-end mt-4">
          <Button variant="secondary" onClick={onClose} disabled={deleting}>Cancel</Button>
          <Button variant="danger" loading={deleting} disabled={!canDelete} onClick={handleDelete}>
            Delete Project
          </Button>
        </div>
      </div>
    </div>
  )
}
