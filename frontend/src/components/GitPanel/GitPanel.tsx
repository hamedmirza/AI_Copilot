import { useCallback, useEffect, useState } from 'react'
import { DiffEditor } from '@monaco-editor/react'
import { api } from '@/api/client'
import { useProjectStore } from '@/store'
import { showError, showSuccess } from '@/lib/toast'
import { Button, EmptyState, Skeleton } from '@/components/ui/primitives'

export function GitPanel() {
  const projectId = useProjectStore((s) => s.currentProjectId)
  const [status, setStatus] = useState<{ staged: Array<{ path: string; status: string }>; unstaged: Array<{ path: string; status: string }>; untracked: Array<{ path: string; status: string }>; branch?: string; has_remote?: boolean } | null>(null)
  const [commitMsg, setCommitMsg] = useState('')
  const [commitError, setCommitError] = useState('')
  const [loading, setLoading] = useState(false)
  const [committing, setCommitting] = useState(false)
  const [branches, setBranches] = useState<string[]>([])
  const [diff, setDiff] = useState<{ path: string; original: string; modified: string } | null>(null)

  const refresh = useCallback(async () => {
    if (!projectId) return
    setLoading(true)
    try {
      const [st, br] = await Promise.all([
        api.git.status(projectId),
        api.git.branches(projectId),
      ])
      setStatus(st as typeof status)
      setBranches(br.branches)
    } catch (e) {
      showError(e)
    } finally {
      setLoading(false)
    }
  }, [projectId])

  useEffect(() => {
    refresh()
    const interval = setInterval(refresh, 5000)
    return () => clearInterval(interval)
  }, [refresh])

  const viewDiff = async (path: string) => {
    if (!projectId) return
    try {
      const d = await api.git.diff(projectId, path)
      const file = await api.files.read(projectId, path)
      setDiff({ path, original: d.original, modified: file.content })
    } catch (e) {
      showError(e)
    }
  }

  if (!projectId) {
    return <EmptyState title="No project" description="Select a project to view git status" />
  }

  if (loading && !status) {
    return <div className="p-3 space-y-2">{[1, 2, 3].map((i) => <Skeleton key={i} className="h-5" />)}</div>
  }

  const allChanges = [
    ...(status?.staged || []).map((f) => ({ ...f, section: 'staged' as const })),
    ...(status?.unstaged || []).map((f) => ({ ...f, section: 'unstaged' as const })),
    ...(status?.untracked || []).map((f) => ({ ...f, section: 'untracked' as const })),
  ]

  return (
    <div className="h-full flex flex-col p-2 overflow-auto text-sm">
      <div className="flex items-center gap-2 mb-2">
        <select
          className="bg-[var(--bg-tertiary)] border border-[var(--border)] rounded px-2 py-1 text-xs"
          value={status?.branch || 'main'}
          onChange={async (e) => {
            try {
              await api.git.checkout(projectId, e.target.value)
              await refresh()
            } catch (err) { showError(err) }
          }}
        >
          {branches.map((b) => <option key={b} value={b}>{b}</option>)}
        </select>
        <Button
          variant="ghost"
          className="text-xs"
          disabled={!status?.has_remote}
          title={!status?.has_remote ? 'No remote configured' : 'Push'}
          onClick={async () => {
            try { await api.git.push(projectId); showSuccess('Pushed') } catch (e) { showError(e) }
          }}
        >
          Push
        </Button>
        <Button
          variant="ghost"
          className="text-xs"
          disabled={!status?.has_remote}
          title={!status?.has_remote ? 'No remote configured' : 'Pull'}
          onClick={async () => {
            try { await api.git.pull(projectId); await refresh() } catch (e) { showError(e) }
          }}
        >
          Pull
        </Button>
      </div>

      {allChanges.length === 0 ? (
        <EmptyState title="No changes" description="No changes — your working tree is clean" />
      ) : (
        <div className="flex-1">
          {allChanges.map((f) => (
            <div key={f.path} className="flex items-center gap-2 py-0.5 hover:bg-[var(--bg-tertiary)] px-1 rounded">
              <span className="w-4 text-center text-[var(--warning)]">{f.status}</span>
              <span className="flex-1 truncate cursor-pointer" onClick={() => viewDiff(f.path)}>{f.path}</span>
              {f.section !== 'staged' && (
                <button className="text-[var(--success)]" onClick={async () => {
                  try { await api.git.stage(projectId, [f.path]); await refresh() } catch (e) { showError(e) }
                }}>+</button>
              )}
              {f.section === 'staged' && (
                <button className="text-[var(--error)]" onClick={async () => {
                  try { await api.git.unstage(projectId, [f.path]); await refresh() } catch (e) { showError(e) }
                }}>−</button>
              )}
            </div>
          ))}
        </div>
      )}

      <div className="mt-2 border-t border-[var(--border)] pt-2">
        <input
          className="w-full bg-[var(--bg-tertiary)] border border-[var(--border)] rounded px-2 py-1 text-sm mb-1"
          placeholder="Commit message"
          value={commitMsg}
          onChange={(e) => setCommitMsg(e.target.value)}
        />
        {commitError && <p className="text-[var(--error)] text-xs">{commitError}</p>}
        <Button
          loading={committing}
          className="w-full"
          onClick={async () => {
            if (!commitMsg.trim()) { setCommitError('Commit message required'); return }
            setCommitError('')
            setCommitting(true)
            try {
              await api.git.commit(projectId, commitMsg)
              setCommitMsg('')
              showSuccess('Committed')
              await refresh()
            } catch (e) { showError(e) }
            finally { setCommitting(false) }
          }}
        >
          Commit
        </Button>
      </div>

      {diff && (
        <div className="fixed inset-4 bg-[var(--bg-primary)] border border-[var(--border)] z-50 flex flex-col rounded">
          <div className="flex justify-between p-2 border-b border-[var(--border)]">
            <span>{diff.path}</span>
            <button onClick={() => setDiff(null)}>×</button>
          </div>
          <div className="flex-1">
            <DiffEditor
              height="100%"
              original={diff.original}
              modified={diff.modified}
              language="plaintext"
              theme="vs-dark"
            />
          </div>
        </div>
      )}
    </div>
  )
}
