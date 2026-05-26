import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { DiffEditor } from '@monaco-editor/react'
import { api } from '@/api/client'
import { useEditorStore, useProjectStore } from '@/store'
import { showError, showSuccess } from '@/lib/toast'
import { Button, EmptyState, Skeleton } from '@/components/ui/primitives'

type GitFile = { path: string; status: string }
type GitStatus = {
  staged: GitFile[]
  unstaged: GitFile[]
  untracked: GitFile[]
  branch?: string
  has_remote?: boolean
  remote_name?: string | null
  ahead?: number
  behind?: number
}
type GitCommit = { sha: string; message: string; author: string; date: string }

export function GitPanel({ pollWhenVisible = true }: { pollWhenVisible?: boolean }) {
  const projectId = useProjectStore((s) => s.currentProjectId)
  const bumpTreeRefresh = useEditorStore((s) => s.bumpTreeRefresh)
  const [status, setStatus] = useState<GitStatus | null>(null)
  const [commits, setCommits] = useState<GitCommit[]>([])
  const [commitMsg, setCommitMsg] = useState('')
  const [commitError, setCommitError] = useState('')
  const [loading, setLoading] = useState(false)
  const [refreshing, setRefreshing] = useState(false)
  const [committing, setCommitting] = useState(false)
  const [pushing, setPushing] = useState(false)
  const [pulling, setPulling] = useState(false)
  const [stagingAll, setStagingAll] = useState(false)
  const [branches, setBranches] = useState<string[]>([])
  const [diff, setDiff] = useState<{ path: string; original: string; modified: string } | null>(null)
  const hasLoadedRef = useRef(false)

  const refresh = useCallback(async (opts?: { quiet?: boolean }) => {
    if (!projectId) return
    const quiet = opts?.quiet ?? false
    if (!quiet) {
      if (!hasLoadedRef.current) setLoading(true)
      else setRefreshing(true)
    }
    try {
      const [st, br, log] = await Promise.all([
        api.git.status(projectId) as Promise<GitStatus>,
        api.git.branches(projectId),
        api.git.log(projectId) as Promise<GitCommit[]>,
      ])
      setStatus(st)
      setBranches(br.branches)
      setCommits(Array.isArray(log) ? log : [])
    } catch (e) {
      showError(e)
    } finally {
      hasLoadedRef.current = true
      setLoading(false)
      setRefreshing(false)
    }
  }, [projectId])

  useEffect(() => {
    hasLoadedRef.current = false
    setStatus(null)
    setCommits([])
  }, [projectId])

  useEffect(() => {
    void refresh()
    if (!pollWhenVisible) return
    const interval = setInterval(() => void refresh({ quiet: true }), 8000)
    return () => clearInterval(interval)
  }, [refresh, pollWhenVisible])

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

  const allChanges = useMemo(() => [
    ...(status?.staged || []).map((f) => ({ ...f, section: 'staged' as const })),
    ...(status?.unstaged || []).map((f) => ({ ...f, section: 'unstaged' as const })),
    ...(status?.untracked || []).map((f) => ({ ...f, section: 'untracked' as const })),
  ], [status])

  const hasChanges = allChanges.length > 0
  const remoteLabel = status?.remote_name || 'origin'
  const syncHint = useMemo(() => {
    const ahead = status?.ahead ?? 0
    const behind = status?.behind ?? 0
    if (!status?.has_remote) return null
    if (ahead === 0 && behind === 0) return 'Up to date with remote'
    const parts: string[] = []
    if (ahead > 0) parts.push(`${ahead} to push`)
    if (behind > 0) parts.push(`${behind} to pull`)
    return parts.join(' · ')
  }, [status])

  if (!projectId) {
    return <EmptyState title="No project" description="Select a project to view git status" />
  }

  if (loading && !status) {
    return <div className="p-3 space-y-2">{[1, 2, 3].map((i) => <Skeleton key={i} className="h-5" />)}</div>
  }

  return (
    <div className="h-full flex flex-col p-2 overflow-auto text-sm">
      <div className="flex items-center gap-2 mb-1 flex-wrap">
        <select
          className="bg-[var(--bg-tertiary)] border border-[var(--border)] rounded px-2 py-1 text-xs min-w-0 flex-1"
          value={status?.branch || branches[0] || 'main'}
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
          className="text-xs shrink-0"
          disabled={!status?.has_remote || pushing}
          loading={pushing}
          title={!status?.has_remote ? 'No remote configured' : `Push to ${remoteLabel}`}
          onClick={async () => {
            setPushing(true)
            try {
              const res = await api.git.push(projectId)
              showSuccess(`Pushed ${res.branch} → ${res.remote}`)
              await refresh({ quiet: true })
            } catch (e) { showError(e) }
            finally { setPushing(false) }
          }}
        >
          Push
        </Button>
        <Button
          variant="ghost"
          className="text-xs shrink-0"
          disabled={!status?.has_remote || pulling}
          loading={pulling}
          title={!status?.has_remote ? 'No remote configured' : `Pull from ${remoteLabel}`}
          onClick={async () => {
            setPulling(true)
            try {
              const res = await api.git.pull(projectId)
              showSuccess(`Pulled ${res.branch} ← ${res.remote}`)
              bumpTreeRefresh()
              await refresh({ quiet: true })
            } catch (e) { showError(e) }
            finally { setPulling(false) }
          }}
        >
          Pull
        </Button>
      </div>
      {syncHint && (
        <p className="text-[10px] text-[var(--text-secondary)] mb-2">{syncHint}</p>
      )}
      {refreshing && (
        <p className="text-[10px] text-[var(--text-secondary)] mb-1">Refreshing…</p>
      )}

      <div className="flex items-center gap-2 mb-2">
        <Button
          variant="ghost"
          className="text-xs"
          disabled={!hasChanges || stagingAll}
          loading={stagingAll}
          onClick={async () => {
            setStagingAll(true)
            try {
              await api.git.stageAll(projectId)
              await refresh({ quiet: true })
            } catch (e) { showError(e) }
            finally { setStagingAll(false) }
          }}
        >
          Stage all
        </Button>
        <button
          type="button"
          className="text-xs text-[var(--text-secondary)] hover:text-white"
          onClick={() => void refresh()}
        >
          Refresh
        </button>
      </div>

      {hasChanges ? (
        <div className="flex-1 min-h-0 overflow-auto">
          {allChanges.map((f) => (
            <div key={`${f.section}:${f.path}`} className="flex items-center gap-2 py-0.5 hover:bg-[var(--bg-tertiary)] px-1 rounded">
              <span className="w-4 text-center text-[var(--warning)]">{f.status}</span>
              <span className="flex-1 truncate cursor-pointer" onClick={() => viewDiff(f.path)}>{f.path}</span>
              {f.section !== 'staged' && (
                <button type="button" className="text-[var(--success)]" title="Stage" onClick={async () => {
                  try { await api.git.stage(projectId, [f.path]); await refresh({ quiet: true }) } catch (e) { showError(e) }
                }}>+</button>
              )}
              {f.section === 'staged' && (
                <button type="button" className="text-[var(--error)]" title="Unstage" onClick={async () => {
                  try { await api.git.unstage(projectId, [f.path]); await refresh({ quiet: true }) } catch (e) { showError(e) }
                }}>−</button>
              )}
            </div>
          ))}
        </div>
      ) : (
        <EmptyState title="No changes" description="Working tree clean" />
      )}

      <div className="mt-2 border-t border-[var(--border)] pt-2 shrink-0">
        <input
          className="w-full bg-[var(--bg-tertiary)] border border-[var(--border)] rounded px-2 py-1 text-sm mb-1"
          placeholder="Commit message"
          value={commitMsg}
          onChange={(e) => setCommitMsg(e.target.value)}
        />
        {commitError && <p className="text-[var(--error)] text-xs">{commitError}</p>}
        <p className="text-[10px] text-[var(--text-secondary)] mb-1">
          Commit stages all current changes automatically.
        </p>
        <Button
          loading={committing}
          className="w-full"
          disabled={!hasChanges}
          onClick={async () => {
            if (!commitMsg.trim()) { setCommitError('Commit message required'); return }
            setCommitError('')
            setCommitting(true)
            try {
              const res = await api.git.commit(projectId, commitMsg) as { sha?: string }
              setCommitMsg('')
              const short = res.sha ? res.sha.slice(0, 8) : ''
              showSuccess(short ? `Committed ${short}` : 'Committed')
              bumpTreeRefresh()
              await refresh({ quiet: true })
            } catch (e) { showError(e) }
            finally { setCommitting(false) }
          }}
        >
          Commit
        </Button>
      </div>

      {commits.length > 0 && (
        <div className="mt-2 border-t border-[var(--border)] pt-2 shrink-0">
          <p className="text-[10px] uppercase text-[var(--text-secondary)] mb-1">Recent commits</p>
          <ul className="space-y-1 max-h-28 overflow-auto">
            {commits.slice(0, 8).map((c) => (
              <li key={c.sha} className="text-xs truncate" title={c.message}>
                <span className="text-[var(--accent)] font-mono">{c.sha}</span>{' '}
                {c.message}
              </li>
            ))}
          </ul>
        </div>
      )}

      {diff && (
        <div className="fixed inset-4 bg-[var(--bg-primary)] border border-[var(--border)] z-50 flex flex-col rounded">
          <div className="flex justify-between p-2 border-b border-[var(--border)]">
            <span>{diff.path}</span>
            <button type="button" onClick={() => setDiff(null)}>×</button>
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
