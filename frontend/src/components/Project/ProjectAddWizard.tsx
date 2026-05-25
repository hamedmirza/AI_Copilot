import { useState } from 'react'
import { FolderOpen } from 'lucide-react'
import { api } from '@/api/client'
import { showError } from '@/lib/toast'
import { Button } from '@/components/ui/primitives'
import {
  type ProjectWizardForm,
  type SourceType,
  VALIDATION_PROFILES,
} from './projectWizardConfig'

function validateStep(step: number, form: ProjectWizardForm): string | null {
  if (step === 1) {
    if (!form.name.trim()) return 'Project name is required'
    return null
  }
  if (step === 2) {
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
  return null
}

interface Props {
  onSubmit: () => void
  onCancel: () => void
  form: ProjectWizardForm
  setForm: (f: ProjectWizardForm) => void
  submitting: boolean
}

export function ProjectAddWizard({ onSubmit, onCancel, form, setForm, submitting }: Props) {
  const [step, setStep] = useState(1)
  const [error, setError] = useState('')
  const [browsing, setBrowsing] = useState(false)

  const advance = (next: number) => {
    const err = validateStep(step, form)
    if (err) {
      setError(err)
      return
    }
    setError('')
    setStep(next)
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

  const handleCreate = () => {
    const err = validateStep(2, form)
    if (err) {
      setError(err)
      return
    }
    setError('')
    onSubmit()
  }

  const profileLabel =
    VALIDATION_PROFILES.find((p) => p.value === form.validation_profile)?.label
    ?? form.validation_profile

  return (
    <div className="border border-[var(--border)] rounded-lg p-4 mb-4 bg-[var(--bg-tertiary)]">
      <p className="text-xs text-[var(--text-secondary)] mb-4">Step {step} of 3</p>

      {step === 1 && (
        <div className="space-y-3">
          <h3 className="text-sm font-medium">Project details</h3>
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
        </div>
      )}

      {step === 2 && (
        <div className="space-y-3">
          <h3 className="text-sm font-medium">Repository</h3>
          <div className="flex gap-2">
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
              <p className="text-xs text-[var(--text-secondary)]">
                Choose an existing folder or create one in Finder.
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
              <p className="text-xs text-[var(--text-secondary)]">
                Supported hosts: GitHub and GitLab. The repo will be cloned into backend/repos/.
              </p>
            </>
          )}
        </div>
      )}

      {step === 3 && (
        <div className="space-y-3">
          <h3 className="text-sm font-medium">Validation profile</h3>
          <select
            className="w-full bg-[var(--bg-secondary)] border border-[var(--border)] rounded px-3 py-2 text-sm"
            value={form.validation_profile}
            onChange={(e) => setForm({ ...form, validation_profile: e.target.value })}
          >
            {VALIDATION_PROFILES.map((p) => (
              <option key={p.value} value={p.value}>{p.label}</option>
            ))}
          </select>
          <div className="text-xs text-[var(--text-secondary)] space-y-1 border border-[var(--border)] rounded p-3 bg-[var(--bg-secondary)]">
            <p><span className="text-[var(--text-primary)]">Name:</span> {form.name.trim() || '—'}</p>
            {form.description.trim() && (
              <p><span className="text-[var(--text-primary)]">Description:</span> {form.description.trim()}</p>
            )}
            <p>
              <span className="text-[var(--text-primary)]">Source:</span>{' '}
              {form.source_type === 'workspace' ? 'Local workspace' : 'Git repository'}
            </p>
            <p className="truncate" title={form.source_repo_spec}>
              <span className="text-[var(--text-primary)]">Path:</span> {form.source_repo_spec}
            </p>
            <p><span className="text-[var(--text-primary)]">Profile:</span> {profileLabel}</p>
          </div>
        </div>
      )}

      {error && <p className="text-[var(--error)] text-xs mt-3">{error}</p>}

      <div className="flex gap-2 justify-end mt-4">
        <Button variant="secondary" onClick={onCancel} disabled={submitting}>Cancel</Button>
        {step > 1 && (
          <Button variant="secondary" onClick={() => { setError(''); setStep(step - 1) }} disabled={submitting}>
            Back
          </Button>
        )}
        {step < 3 && (
          <Button onClick={() => advance(step + 1)} disabled={submitting}>Next</Button>
        )}
        {step === 3 && (
          <Button loading={submitting} onClick={handleCreate}>Create Project</Button>
        )}
      </div>
    </div>
  )
}
