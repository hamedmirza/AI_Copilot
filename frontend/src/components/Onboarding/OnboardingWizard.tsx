import { useState } from 'react'
import { FolderOpen } from 'lucide-react'
import { api } from '@/api/client'
import { useAppStore, useProjectStore } from '@/store'
import { showError, showSuccess } from '@/lib/toast'
import { Button } from '@/components/ui/primitives'

export function OnboardingWizard() {
  const show = useAppStore((s) => s.showOnboarding)
  const setShowOnboarding = useAppStore((s) => s.setShowOnboarding)
  const projects = useProjectStore((s) => s.projects)
  const setProjects = useProjectStore((s) => s.setProjects)
  const allowSkip = projects.length > 0
  const setCurrentProject = useProjectStore((s) => s.setCurrentProject)
  const [step, setStep] = useState(1)
  const [lmUrl, setLmUrl] = useState('http://192.168.128.70:1234/v1')
  const [testing, setTesting] = useState(false)
  const [testOk, setTestOk] = useState<boolean | null>(null)
  const [name, setName] = useState('')
  const [sourceType, setSourceType] = useState<'workspace' | 'git'>('workspace')
  const [repoPath, setRepoPath] = useState('')
  const [profile, setProfile] = useState('python')
  const [creating, setCreating] = useState(false)
  const [browsing, setBrowsing] = useState(false)

  if (!show) return null

  const testLm = async () => {
    setTesting(true)
    try {
      await api.settings.update({ lmstudio_base_url: lmUrl })
      const health = await api.providerHealth()
      const connected = health.lmstudio === 'healthy'
      setTestOk(connected)
      if (!connected) showError(health.error || 'Connection failed')
    } catch (e) {
      setTestOk(false)
      showError(e)
    } finally {
      setTesting(false)
    }
  }

  const finish = async () => {
    if (!name.trim() || !repoPath.trim()) return
    if (sourceType === 'git' && !repoPath.trim().startsWith('https://')) return
    setCreating(true)
    try {
      const project = await api.projects.create({
        name,
        source_repo_spec: repoPath,
        validation_profile: profile,
      }) as { id: string }
      const projects = await api.projects.list()
      setProjects(projects)
      setCurrentProject(String(project.id))
      setShowOnboarding(false)
      showSuccess('Welcome to AI Copilot!')
    } catch (e) {
      showError(e)
    } finally {
      setCreating(false)
    }
  }

  const handleBrowse = async () => {
    setBrowsing(true)
    try {
      const result = await api.dialog.pickDirectory('Select or create a project folder')
      if (!result.cancelled && result.path) setRepoPath(result.path)
    } catch (e) {
      showError(e)
    } finally {
      setBrowsing(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-[var(--bg-primary)] z-50 flex items-center justify-center">
      <div className="relative bg-[var(--bg-secondary)] border border-[var(--border)] rounded-lg p-8 w-[500px]">
        <h1 className="text-xl font-medium mb-2">Welcome to AI Copilot</h1>
        <p className="text-[var(--text-secondary)] text-sm mb-6">Step {step} of 3</p>
        {allowSkip && (
          <button
            className="absolute top-4 right-4 text-xs text-[var(--text-secondary)] hover:text-white"
            onClick={() => setShowOnboarding(false)}
          >
            Skip
          </button>
        )}

        {step === 1 && (
          <>
            <h2 className="mb-2">Connect LM Studio</h2>
            <input
              className="w-full bg-[var(--bg-tertiary)] border border-[var(--border)] rounded px-3 py-2 text-sm mb-2"
              value={lmUrl}
              onChange={(e) => setLmUrl(e.target.value)}
              placeholder="http://192.168.128.70:1234/v1"
            />
            <Button loading={testing} onClick={testLm}>Test Connection</Button>
            {testOk === true && <p className="text-[var(--success)] text-sm mt-2">✓ Connected</p>}
            {testOk === false && <p className="text-[var(--error)] text-sm mt-2">✕ Connection failed</p>}
            <Button className="mt-4 w-full" onClick={() => setStep(2)}>Next</Button>
          </>
        )}

        {step === 2 && (
          <>
            <h2 className="mb-2">Create First Project</h2>
            <input
              className="w-full bg-[var(--bg-tertiary)] border border-[var(--border)] rounded px-3 py-2 text-sm mb-2"
              placeholder="Project name"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
            <div className="flex gap-2 mb-2">
              <button
                type="button"
                className={`flex-1 px-3 py-2 text-sm rounded border ${
                  sourceType === 'workspace'
                    ? 'border-[var(--accent)] bg-[var(--accent)]/10'
                    : 'border-[var(--border)] bg-[var(--bg-tertiary)] text-[var(--text-secondary)]'
                }`}
                onClick={() => { setSourceType('workspace'); setRepoPath('') }}
              >
                Local workspace
              </button>
              <button
                type="button"
                className={`flex-1 px-3 py-2 text-sm rounded border ${
                  sourceType === 'git'
                    ? 'border-[var(--accent)] bg-[var(--accent)]/10'
                    : 'border-[var(--border)] bg-[var(--bg-tertiary)] text-[var(--text-secondary)]'
                }`}
                onClick={() => { setSourceType('git'); setRepoPath('') }}
              >
                Git repository
              </button>
            </div>
            {sourceType === 'workspace' ? (
              <div className="flex gap-2 mb-2">
                <input
                  className="flex-1 min-w-0 bg-[var(--bg-tertiary)] border border-[var(--border)] rounded px-3 py-2 text-sm"
                  placeholder="/path/to/project"
                  value={repoPath}
                  onChange={(e) => setRepoPath(e.target.value)}
                />
                <Button type="button" variant="secondary" loading={browsing} onClick={handleBrowse}>
                  <FolderOpen size={14} />
                  Browse
                </Button>
              </div>
            ) : (
              <input
                className="w-full bg-[var(--bg-tertiary)] border border-[var(--border)] rounded px-3 py-2 text-sm mb-2"
                placeholder="https://github.com/org/repo"
                value={repoPath}
                onChange={(e) => setRepoPath(e.target.value)}
              />
            )}
            <select
              className="w-full bg-[var(--bg-tertiary)] border border-[var(--border)] rounded px-3 py-2 text-sm mb-4"
              value={profile}
              onChange={(e) => setProfile(e.target.value)}
            >
              <option value="python">Python</option>
              <option value="react">React</option>
              <option value="fullstack">Fullstack</option>
            </select>
            <div className="flex gap-2">
              <Button variant="secondary" onClick={() => setStep(1)}>Back</Button>
              <Button className="flex-1" disabled={!name || !repoPath} onClick={() => setStep(3)}>Next</Button>
            </div>
          </>
        )}

        {step === 3 && (
          <>
            <h2 className="mb-4">Ready to launch!</h2>
            <p className="text-sm text-[var(--text-secondary)] mb-4">
              Project: {name}<br />
              Source: {sourceType === 'workspace' ? 'Local workspace' : 'Git repository'}<br />
              {sourceType === 'workspace' ? 'Folder' : 'URL'}: {repoPath}<br />
              Profile: {profile}
            </p>
            <div className="flex gap-2">
              <Button variant="secondary" onClick={() => setStep(2)}>Back</Button>
              <Button loading={creating} className="flex-1" onClick={finish}>Launch IDE</Button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
