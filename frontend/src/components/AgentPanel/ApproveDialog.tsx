import { useEffect, useState } from 'react'
import { DiffEditor } from '@monaco-editor/react'
import { api } from '@/api/client'
import { showError, showSuccess } from '@/lib/toast'
import { Button } from '@/components/ui/primitives'
import {
  loadCoderPatchDiffs,
  monacoLanguageForPath,
  type PatchDiffFile,
} from './coderPatchDiff'

interface Artifact {
  artifact_type: string
  content: Record<string, unknown>
}

function buildDiffSummary(artifacts: Artifact[]): string {
  const coder = artifacts.find((a) => a.artifact_type === 'coder')
  if (!coder) return 'No coder patch artifact is available for this run.'
  const content = coder.content
  const summary = typeof content.summary === 'string' ? content.summary : ''
  const changes = Array.isArray(content.file_changes) ? content.file_changes : []
  const lines = changes.map((c) => {
    const row = c as Record<string, unknown>
    const path = String(row.path || row.file_path || 'unknown')
    const lineCount = Array.isArray(row.line_changes) ? row.line_changes.length : 0
    const full = row.full_content ? ' (full file)' : ''
    return `• ${path}${full}${lineCount ? ` — ${lineCount} hunk(s)` : ''}`
  })
  return [summary, lines.length ? 'Files:' : '', ...lines].filter(Boolean).join('\n')
}

interface Props {
  runId: string
  projectId: string
  artifacts: Artifact[]
  onClose: () => void
  onApproved: () => void
}

export function ApproveDialog({ runId, projectId, artifacts, onClose, onApproved }: Props) {
  const [approving, setApproving] = useState(false)
  const [loadingDiffs, setLoadingDiffs] = useState(true)
  const [diffFiles, setDiffFiles] = useState<PatchDiffFile[]>([])
  const [activePath, setActivePath] = useState<string | null>(null)
  const summary = buildDiffSummary(artifacts)

  useEffect(() => {
    let cancelled = false
    setLoadingDiffs(true)
    loadCoderPatchDiffs(projectId, artifacts)
      .then((files) => {
        if (cancelled) return
        setDiffFiles(files)
        setActivePath(files[0]?.path ?? null)
      })
      .catch((e) => showError(e))
      .finally(() => {
        if (!cancelled) setLoadingDiffs(false)
      })
    return () => { cancelled = true }
  }, [projectId, artifacts])

  const active = diffFiles.find((f) => f.path === activePath) ?? diffFiles[0] ?? null

  const handleApprove = async () => {
    setApproving(true)
    try {
      await api.runs.approve(runId)
      showSuccess('Approved — applying changes')
      onApproved()
      onClose()
    } catch (e) {
      showError(e)
    } finally {
      setApproving(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/60 z-50 flex items-center justify-center p-4">
      <div className="bg-[var(--bg-secondary)] border border-[var(--border)] rounded-lg p-6 w-[min(960px,95vw)] h-[min(720px,90vh)] flex flex-col">
        <h2 className="text-lg font-medium mb-1">Approve changes</h2>
        <p className="text-sm text-[var(--text-secondary)] mb-3 shrink-0">
          {summary.split('\n')[0] || 'Review proposed patches before applying to the project workspace.'}
        </p>

        {loadingDiffs ? (
          <p className="text-xs text-[var(--text-secondary)] flex-1">Loading patch preview…</p>
        ) : diffFiles.length === 0 ? (
          <pre className="flex-1 overflow-auto text-xs font-mono bg-[#1a1a1a] rounded p-3 mb-4 whitespace-pre-wrap">
            {summary}
          </pre>
        ) : (
          <>
            <div className="flex gap-1 flex-wrap mb-2 shrink-0 max-h-20 overflow-auto">
              {diffFiles.map((f) => (
                <button
                  key={f.path}
                  type="button"
                  className={`text-xs px-2 py-1 rounded border truncate max-w-[200px] ${
                    active?.path === f.path
                      ? 'border-[var(--accent)] bg-[var(--accent)]/10'
                      : 'border-[var(--border)] hover:bg-[var(--bg-tertiary)]'
                  }`}
                  onClick={() => setActivePath(f.path)}
                  title={f.path}
                >
                  {f.path}
                </button>
              ))}
            </div>
            <div className="flex-1 min-h-0 border border-[var(--border)] rounded overflow-hidden mb-4">
              {active && (
                <DiffEditor
                  height="100%"
                  original={active.original}
                  modified={active.modified}
                  language={monacoLanguageForPath(active.path)}
                  theme="vs-dark"
                  options={{ readOnly: true, renderSideBySide: true }}
                />
              )}
            </div>
          </>
        )}

        <div className="flex gap-2 justify-end shrink-0">
          <Button variant="secondary" onClick={onClose} disabled={approving}>Cancel</Button>
          <Button loading={approving} onClick={handleApprove}>Approve &amp; apply</Button>
        </div>
      </div>
    </div>
  )
}
