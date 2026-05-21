import { useEffect, useState } from 'react'
import { api } from '@/api/client'
import { EmptyState, Skeleton } from '@/components/ui/primitives'

export function LogViewer() {
  const [lines, setLines] = useState<Array<Record<string, unknown>>>([])
  const [level, setLevel] = useState('')
  const [runId, setRunId] = useState('')
  const [loading, setLoading] = useState(true)

  const load = async () => {
    try {
      const data = await api.logs({ limit: 200, level: level || undefined, run_id: runId || undefined })
      setLines(data.lines)
    } catch { /* ignore */ }
    finally { setLoading(false) }
  }

  useEffect(() => {
    load()
    const interval = setInterval(load, 2000)
    return () => clearInterval(interval)
  }, [level, runId])

  if (loading) {
    return <div className="p-2 space-y-1">{[1, 2, 3].map((i) => <Skeleton key={i} className="h-4" />)}</div>
  }

  return (
    <div className="h-full flex flex-col">
      <div className="flex gap-2 p-2 border-b border-[var(--border)]">
        <select
          className="bg-[var(--bg-tertiary)] border border-[var(--border)] rounded px-2 py-0.5 text-xs"
          value={level}
          onChange={(e) => setLevel(e.target.value)}
        >
          <option value="">All levels</option>
          <option value="debug">Debug</option>
          <option value="info">Info</option>
          <option value="warn">Warn</option>
          <option value="error">Error</option>
        </select>
        <input
          className="flex-1 bg-[var(--bg-tertiary)] border border-[var(--border)] rounded px-2 py-0.5 text-xs"
          placeholder="Filter by run_id"
          value={runId}
          onChange={(e) => setRunId(e.target.value)}
        />
        <button className="text-xs text-[var(--text-secondary)] hover:text-white" onClick={() => setLines([])}>
          Clear
        </button>
      </div>
      <div className="flex-1 overflow-auto p-2 font-mono text-xs">
        {lines.length === 0 ? (
          <EmptyState title="No logs" description="Server logs will appear here" />
        ) : (
          lines.map((line, i) => (
            <div key={i} className={`py-0.5 ${
              line.level === 'error' ? 'text-[var(--error)]' :
              line.level === 'warn' ? 'text-[var(--warning)]' : 'text-[var(--text-secondary)]'
            }`}>
              [{String(line.timestamp)}] [{String(line.level)}] {String(line.message)}
              {line.run_id ? ` (run:${line.run_id})` : ''}
            </div>
          ))
        )}
      </div>
    </div>
  )
}
