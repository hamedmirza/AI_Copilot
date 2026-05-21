import { useState } from 'react'
import { showSuccess } from '@/lib/toast'
import { Button } from '@/components/ui/primitives'
import { ChevronDown, ChevronRight, Copy } from 'lucide-react'

interface Artifact {
  id: number
  artifact_type: string
  content: Record<string, unknown>
  created_at: string
}

function JsonSection({ label, value, depth = 0 }: { label: string; value: unknown; depth?: number }) {
  const [open, setOpen] = useState(depth < 1)
  const isObject = value !== null && typeof value === 'object'
  const text = isObject ? JSON.stringify(value, null, 2) : String(value)

  const copy = () => {
    navigator.clipboard.writeText(text)
    showSuccess('Copied to clipboard')
  }

  if (!isObject) {
    return (
      <div className="pl-2 py-0.5" style={{ marginLeft: depth * 8 }}>
        <span className="text-[var(--text-secondary)]">{label}: </span>
        <span className="text-[var(--text-primary)]">{text}</span>
        <button className="ml-2 opacity-60 hover:opacity-100" onClick={copy} title="Copy">
          <Copy size={12} />
        </button>
      </div>
    )
  }

  const entries = Array.isArray(value)
    ? value.map((v, i) => [String(i), v] as const)
    : Object.entries(value as Record<string, unknown>)

  return (
    <div style={{ marginLeft: depth * 8 }}>
      <div className="flex items-center gap-1 py-0.5 hover:bg-[var(--bg-tertiary)] rounded cursor-pointer">
        <button className="p-0.5" onClick={() => setOpen(!open)}>
          {open ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
        </button>
        <span className="text-[var(--accent)]">{label}</span>
        <span className="text-[var(--text-secondary)] text-xs">
          {Array.isArray(value) ? `[${value.length}]` : `{${entries.length}}`}
        </span>
        <button className="ml-auto opacity-60 hover:opacity-100 px-1" onClick={copy} title="Copy JSON">
          <Copy size={12} />
        </button>
      </div>
      {open && (
        <div className="border-l border-[var(--border)] ml-2">
          {entries.map(([k, v]) => (
            <JsonSection key={k} label={k} value={v} depth={depth + 1} />
          ))}
        </div>
      )}
    </div>
  )
}

export function ArtifactViewer({ artifacts, loading }: { artifacts: Artifact[]; loading: boolean }) {
  const [expanded, setExpanded] = useState<Record<number, boolean>>({})

  if (loading) {
    return <p className="text-xs text-[var(--text-secondary)] p-2">Loading artifacts...</p>
  }

  if (artifacts.length === 0) return null

  return (
    <div className="border-t border-[var(--border)] pt-2 max-h-48 overflow-auto">
      <p className="text-xs text-[var(--text-secondary)] mb-1 px-1">Artifacts</p>
      {artifacts.map((a) => (
        <div key={a.id} className="mb-2 bg-[#1a1a1a] rounded p-2">
          <div
            className="flex items-center gap-1 cursor-pointer text-xs font-medium"
            onClick={() => setExpanded((s) => ({ ...s, [a.id]: !s[a.id] }))}
          >
            {expanded[a.id] !== false ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
            {a.artifact_type}
            <Button
              variant="ghost"
              className="ml-auto text-xs py-0 px-1 h-5"
              onClick={(e) => {
                e.stopPropagation()
                navigator.clipboard.writeText(JSON.stringify(a.content, null, 2))
                showSuccess('Copied artifact JSON')
              }}
            >
              <Copy size={12} />
            </Button>
          </div>
          {expanded[a.id] !== false && (
            <div className="mt-1 text-xs font-mono">
              <JsonSection label="content" value={a.content} />
            </div>
          )}
        </div>
      ))}
    </div>
  )
}
