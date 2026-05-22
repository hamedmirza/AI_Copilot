import { useEffect, useState } from 'react'
import { FolderOpen } from 'lucide-react'
import { api } from '@/api/client'
import { useEditorStore, useProjectStore, useRunStore } from '@/store'
import { showError, showSuccess } from '@/lib/toast'
import { Button } from '@/components/ui/primitives'
import {
  ProjectAddWizard,
  VALIDATION_PROFILES,
  emptyWizardForm,
  type ProjectWizardForm,
} from './ProjectAddWizard'

interface ProjectRow {
  id: string
  name: string
  description: string
  source_repo_spec: string
  validation_profile: string
}

interface Props {
  open: boolean
  onClose: () => void
  initialMode?: 'list' | 'add'
  onProjectsChanged?: (opts?: { selectId?: string; clearWorkspace?: boolean }) => void
}

type SourceType = 'workspace' | 'git'

type FormState = ProjectWizardForm

const emptyForm = emptyWizardForm

function inferSourceType(spec: string): SourceType {
  return spec.trim().startsWith('https://') ? 'git' : 'workspace'
}

function validateForm(form: FormState): string | null {
  if (!form.name.trim()) return 'Project name is required'
  if (form.source_type === 'git') {
    if (!form.source_repo_spec.trim()) return 'Git URL is required'
    if (!form.source_repo_spec.trim().startsWith('https://')) {
      return 'Git URL must start with https://'
    }
  } else if (!form.source_repo_spec.trim()) {
    return 'Workspace folder is required'
  }
  return null
}

function ProjectForm({
  form,
  setForm,
  onSubmit,
  onCancel,
  submitting,
  submitLabel,
}: {
  form: FormState
  setForm: (f: FormState) => void
  onSubmit: () => void
  onCancel: () => void
  submitting: boolean
  submitLabel: string
}) {
  const [error, setError] = useState('')
  const [browsing, setBrowsing] = useState(false)

  const handleSubmit = () => {
    const err = validateForm(form)
    if (err) {
      setError(err)
      return
    }
    setError('')
    onSubmit()
  }

  const handleBrowse = async () => {
    setBrowsing(true)
    try {
      const result = await api.dialog.pickDirectory('Select or create a project folder')
      if (result.error === 'timeout') {
        showError('Folder picker timed out. Try again or enter the path manually.')
        return
      }
      if (result.error) {
        showError(`Folder picker failed: ${result.error}`)
        return
      }
      if (!result.cancelled && result.path) {
        setForm({ ...form, source_repo_spec: result.path })
        setError('')
      }
    } catch (e) {
      showError(e)
    } finally {
      setBrowsing(false)
    }
  }

  const setSourceType = (sourceType: SourceType) => {
    setForm({
      ...form,
      source_type: sourceType,
      source_repo_spec: sourceType === form.source_type ? form.source_repo_spec : '',
    })
    setError('')
  }

  return (
    <div className="border border-[var(--border)] rounded-lg p-4 mb-4 bg-[var(--bg-tertiary)]">
      <div className="space-y-3">
        <div>
          <label className="block text-xs text-[var(--text-secondary)] mb-1">Name *</label>
          <input
            className="w-full bg-[var(--bg-secondary)] border border-[var(--border)] rounded px-3 py-2 text-sm"
            value={form.name}
            onChange={(e) => { setForm({ ...form, name: e.target.value }); setError('') }}
            placeholder="My Project"
          />
        </div>
        <div>
          <label className="block text-xs text-[var(--text-secondary)] mb-1">Description</label>
          <input
            className="w-full bg-[var(--bg-secondary)] border border-[var(--border)] rounded px-3 py-2 text-sm"
            value={form.description}
            onChange={(e) => setForm({ ...form, description: e.target.value })}
            placeholder="Optional description"
          />
        </div>
        <div>
          <label className="block text-xs text-[var(--text-secondary)] mb-1">Source *</label>
          <div className="flex gap-2 mb-2">
            <button
              type="button"
              className={`flex-1 px-3 py-2 text-sm rounded border transition-colors ${
                form.source_type === 'workspace'
                  ? 'border-[var(--accent)] bg-[var(--accent)]/10 text-[var(--text-primary)]'
                  : 'border-[var(--border)] bg-[var(--bg-secondary)] text-[var(--text-secondary)] hover:text-[var(--text-primary)]'
              }`}
              onClick={() => setSourceType('workspace')}
            >
              Local workspace
            </button>
            <button
              type="button"
              className={`flex-1 px-3 py-2 text-sm rounded border transition-colors ${
                form.source_type === 'git'
                  ? 'border-[var(--accent)] bg-[var(--accent)]/10 text-[var(--text-primary)]'
                  : 'border-[var(--border)] bg-[var(--bg-secondary)] text-[var(--text-secondary)] hover:text-[var(--text-primary)]'
              }`}
              onClick={() => setSourceType('git')}
            >
              Git repository
            </button>
          </div>
          {form.source_type === 'workspace' ? (
            <>
              <div className="flex gap-2">
                <input
                  className="flex-1 min-w-0 bg-[var(--bg-secondary)] border border-[var(--border)] rounded px-3 py-2 text-sm"
                  value={form.source_repo_spec}
                  onChange={(e) => { setForm({ ...form, source_repo_spec: e.target.value }); setError('') }}
                  placeholder="/path/to/project"
                />
                <Button
                  type="button"
                  variant="secondary"
                  loading={browsing}
                  onClick={handleBrowse}
                  className="shrink-0"
                >
                  <FolderOpen size={14} />
                  Browse
                </Button>
              </div>
              <p className="text-xs text-[var(--text-secondary)] mt-1">
                Choose an existing folder or create one in Finder. The folder will be used as the project workspace.
              </p>
            </>
          ) : (
            <>
              <input
                className="w-full bg-[var(--bg-secondary)] border border-[var(--border)] rounded px-3 py-2 text-sm"
                value={form.source_repo_spec}
                onChange={(e) => { setForm({ ...form, source_repo_spec: e.target.value }); setError('') }}
                placeholder="https://github.com/org/repo"
              />
              <p className="text-xs text-[var(--text-secondary)] mt-1">
                Supported hosts: GitHub and GitLab. The repo will be cloned into backend/repos/.
              </p>
            </>
          )}
        </div>
        <div>
          <label className="block text-xs text-[var(--text-secondary)] mb-1">Validation profile</label>
          <select
            className="w-full bg-[var(--bg-secondary)] border border-[var(--border)] rounded px-3 py-2 text-sm"
            value={form.validation_profile}
            onChange={(e) => setForm({ ...form, validation_profile: e.target.value })}
          >
            {VALIDATION_PROFILES.map((p) => (
              <option key={p.value} value={p.value}>{p.label}</option>
            ))}
          </select>
        </div>
        {error && <p className="text-[var(--error)] text-xs">{error}</p>}
        <div className="flex gap-2 justify-end">
          <Button variant="secondary" onClick={onCancel} disabled={submitting}>Cancel</Button>
          <Button loading={submitting} onClick={handleSubmit}>{submitLabel}</Button>
        </div>
      </div>
    </div>
  )
}

function DeleteConfirm({
  project,
  onCancel,
  onDeleted,
}: {
  project: ProjectRow
  onCancel: () => void
  onDeleted: () => void
}) {
  const { projects, setProjects, currentProjectId, setCurrentProject } = useProjectStore()
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
        useEditorStore.getState().clearWorkspace()
        useRunStore.getState().resetRunPanel()
        setCurrentProject(remaining.length > 0 ? String(remaining[0].id) : null)
      }
      showSuccess(`Deleted project "${project.name}"`)
      onDeleted()
    } catch (e) {
      showError(e)
    } finally {
      setDeleting(false)
    }
  }

  return (
    <div className="border border-[var(--error)]/40 rounded-lg p-4 mt-2 bg-[var(--bg-tertiary)]">
      <p className="text-sm text-[var(--text-secondary)] mb-2">
        Type <span className="text-[var(--text-primary)]">{project.name}</span> to confirm deletion
      </p>
      <input
        autoFocus
        className="w-full bg-[var(--bg-secondary)] border border-[var(--border)] rounded px-3 py-2 text-sm mb-2"
        value={confirmName}
        onChange={(e) => { setConfirmName(e.target.value); setError('') }}
        placeholder={project.name}
      />
      {error && <p className="text-[var(--error)] text-xs mb-2">{error}</p>}
      <div className="flex gap-2 justify-end">
        <Button variant="secondary" onClick={onCancel} disabled={deleting}>Cancel</Button>
        <Button variant="danger" loading={deleting} disabled={!canDelete} onClick={handleDelete}>
          Delete Project
        </Button>
      </div>
    </div>
  )
}

export function ProjectManagerDialog({ open, onClose, initialMode = 'list', onProjectsChanged }: Props) {
  const { projects, setProjects, setCurrentProject } = useProjectStore()
  const [mode, setMode] = useState<'list' | 'add' | 'edit'>(initialMode === 'add' ? 'add' : 'list')
  const [addForm, setAddForm] = useState<FormState>(emptyForm())
  const [editForm, setEditForm] = useState<FormState>(emptyForm())
  const [editingId, setEditingId] = useState<string | null>(null)
  const [deletingId, setDeletingId] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    if (open) {
      setMode(initialMode === 'add' ? 'add' : 'list')
      setAddForm(emptyForm())
      setEditingId(null)
      setDeletingId(null)
    }
  }, [open, initialMode])

  if (!open) return null

  const rows: ProjectRow[] = projects.map((p) => ({
    id: String(p.id),
    name: String(p.name),
    description: String(p.description || ''),
    source_repo_spec: String(p.source_repo_spec || ''),
    validation_profile: String(p.validation_profile || 'python'),
  }))

  const refreshProjects = async (selectId?: string, clearWorkspace = false) => {
    const updated = await api.projects.list()
    setProjects(updated)
    if (selectId) {
      if (clearWorkspace) {
        useEditorStore.getState().clearWorkspace()
        useRunStore.getState().resetRunPanel()
      }
      setCurrentProject(selectId)
    }
    onProjectsChanged?.({ selectId, clearWorkspace })
  }

  const handleCreate = async () => {
    setSubmitting(true)
    try {
      const created = await api.projects.create({
        name: addForm.name.trim(),
        description: addForm.description.trim(),
        source_repo_spec: addForm.source_repo_spec.trim(),
        validation_profile: addForm.validation_profile,
      }) as { id: string }
      await refreshProjects(String(created.id), true)
      showSuccess(`Created project "${addForm.name.trim()}"`)
      setAddForm(emptyForm())
      setMode('list')
    } catch (e) {
      showError(e)
    } finally {
      setSubmitting(false)
    }
  }

  const handleUpdate = async () => {
    if (!editingId) return
    setSubmitting(true)
    try {
      await api.projects.update(editingId, {
        name: editForm.name.trim(),
        description: editForm.description.trim(),
        source_repo_spec: editForm.source_repo_spec.trim(),
        validation_profile: editForm.validation_profile,
      })
      await refreshProjects(editingId, true)
      showSuccess(`Updated project "${editForm.name.trim()}"`)
      setEditingId(null)
      setMode('list')
    } catch (e) {
      showError(e)
    } finally {
      setSubmitting(false)
    }
  }

  const startEdit = (row: ProjectRow) => {
    setEditingId(row.id)
    setEditForm({
      name: row.name,
      description: row.description,
      source_type: inferSourceType(row.source_repo_spec),
      source_repo_spec: row.source_repo_spec,
      validation_profile: row.validation_profile,
    })
    setDeletingId(null)
    setMode('edit')
  }

  return (
    <div className="fixed inset-0 bg-black/60 z-50 flex items-center justify-center">
      <div className="bg-[var(--bg-secondary)] border border-[var(--border)] rounded-lg p-6 w-[640px] max-h-[80vh] flex flex-col">
        <div className="flex items-center justify-between mb-4 shrink-0">
          <h2 className="text-lg font-medium">Manage Projects</h2>
          <button
            className="text-xs text-[var(--text-secondary)] hover:text-white"
            onClick={onClose}
          >
            Close
          </button>
        </div>

        <div className="overflow-y-auto flex-1">
          {mode === 'add' && (
            <ProjectAddWizard
              form={addForm}
              setForm={setAddForm}
              onSubmit={handleCreate}
              onCancel={() => { setMode('list'); setAddForm(emptyForm()) }}
              submitting={submitting}
            />
          )}

          {mode === 'edit' && editingId && (
            <ProjectForm
              form={editForm}
              setForm={setEditForm}
              onSubmit={handleUpdate}
              onCancel={() => { setMode('list'); setEditingId(null) }}
              submitting={submitting}
              submitLabel="Save Changes"
            />
          )}

          {mode === 'list' && (
            <div className="mb-4">
              <Button onClick={() => { setMode('add'); setAddForm(emptyForm()) }}>+ Add Project</Button>
            </div>
          )}

          {rows.length === 0 && mode === 'list' ? (
            <p className="text-sm text-[var(--text-secondary)] text-center py-8">
              No projects yet. Click &quot;+ Add Project&quot; to create one.
            </p>
          ) : (
            mode === 'list' && (
              <div className="space-y-2">
                {rows.map((row) => (
                  <div
                    key={row.id}
                    className="border border-[var(--border)] rounded-lg p-3 bg-[var(--bg-tertiary)]"
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0 flex-1">
                        <p className="text-sm font-medium truncate">{row.name}</p>
                        <p className="text-xs text-[var(--text-secondary)] truncate mt-0.5" title={row.source_repo_spec}>
                          {row.source_repo_spec}
                        </p>
                        <p className="text-xs text-[var(--text-secondary)] mt-0.5 capitalize">
                          {row.validation_profile}
                        </p>
                      </div>
                      <div className="flex gap-2 shrink-0">
                        <Button variant="secondary" onClick={() => startEdit(row)}>Edit</Button>
                        <Button
                          variant="danger"
                          onClick={() => setDeletingId(deletingId === row.id ? null : row.id)}
                        >
                          Remove
                        </Button>
                      </div>
                    </div>
                    {deletingId === row.id && (
                      <DeleteConfirm
                        project={row}
                        onCancel={() => setDeletingId(null)}
                        onDeleted={() => {
                          setDeletingId(null)
                          onProjectsChanged?.()
                        }}
                      />
                    )}
                  </div>
                ))}
              </div>
            )
          )}
        </div>
      </div>
    </div>
  )
}
