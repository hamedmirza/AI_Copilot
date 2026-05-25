import { useMemo, useState } from 'react'
import { Copy, ExternalLink } from 'lucide-react'
import { openRunFile } from '@/lib/openRunFile'
import { useEditorStore, useProjectStore } from '@/store'
import { showError, showSuccess } from '@/lib/toast'
import { Button } from '@/components/ui/primitives'
import { parseReviewContent, type RunArtifact } from '@/types/runs'

function pathFromSuggestion(text: string): string | null {
  const match = text.match(/(?:^|[\s(])([A-Za-z0-9_./-]+\.[A-Za-z0-9]+)/)
  return match?.[1] || null
}

interface ReviewArtifactPanelProps {
  artifact: RunArtifact
  compact?: boolean
  busy?: boolean
  runId?: string | null
  artifacts?: RunArtifact[]
  onRetryWithFeedback: (feedback: string) => void | Promise<void>
  retryDisabled?: boolean
}

export function ReviewArtifactPanel({
  artifact,
  compact = false,
  busy,
  runId,
  artifacts,
  onRetryWithFeedback,
  retryDisabled = false,
}: ReviewArtifactPanelProps) {
  const projectId = useProjectStore((s) => s.currentProjectId)
  const openTab = useEditorStore((s) => s.openTab)
  const review = useMemo(() => parseReviewContent(artifact.content), [artifact.content])
  const [selected, setSelected] = useState<Set<string>>(new Set())

  const toggle = (key: string) => {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  const buildFeedback = (items: string[]) => {
    const parts = [review.summary || ''].filter(Boolean)
    if (items.length) {
      parts.push('Selected feedback:')
      parts.push(...items.map((line) => `- ${line}`))
    }
    return parts.join('\n')
  }

  const allFeedbackItems = useMemo(() => {
    const lines: string[] = []
    for (const issue of review.issues || []) {
      lines.push(`[${issue.severity}] ${issue.file_path}: ${issue.message}`)
    }
    for (const suggestion of review.suggestions || []) {
      lines.push(suggestion)
    }
    return lines
  }, [review.issues, review.suggestions])

  const selectedItems = useMemo(
    () => allFeedbackItems.filter((_, index) => selected.has(String(index))),
    [allFeedbackItems, selected],
  )

  const openPath = async (path: string) => {
    if (!path) return
    const opened = await openRunFile({ projectId, runId, path, artifacts, openTab })
    if (!opened) showError(new Error(`File not found: ${path}`))
  }

  return (
    <div className={`space-y-3 ${compact ? 'text-xs' : 'text-sm'}`}>
      <div className={`rounded px-2 py-1 text-xs font-medium ${
        review.approved
          ? 'bg-[var(--success)]/15 text-[var(--success)]'
          : 'bg-[var(--warning)]/15 text-[var(--warning)]'
      }`}>
        {review.approved ? 'Approved by reviewer' : 'Changes requested'}
      </div>
      {review.summary && (
        <p className="text-[var(--text-secondary)] whitespace-pre-wrap">{review.summary}</p>
      )}

      {(review.issues?.length || 0) > 0 && (
        <div>
          <p className="text-xs text-[var(--text-secondary)] mb-1 uppercase tracking-wide">Issues</p>
          <div className="overflow-auto max-h-40 border border-[var(--border)] rounded">
            <table className="w-full text-xs">
              <thead className="bg-[var(--bg-tertiary)] sticky top-0">
                <tr>
                  <th className="p-1 w-6" />
                  <th className="p-1 text-left">Severity</th>
                  <th className="p-1 text-left">File</th>
                  <th className="p-1 text-left">Message</th>
                </tr>
              </thead>
              <tbody>
                {review.issues?.map((issue, index) => {
                  const key = String(index)
                  return (
                    <tr key={key} className="border-t border-[var(--border)] hover:bg-[var(--bg-tertiary)]/50">
                      <td className="p-1 align-top">
                        <input
                          type="checkbox"
                          checked={selected.has(key)}
                          onChange={() => toggle(key)}
                        />
                      </td>
                      <td className="p-1 align-top">
                        <span className="px-1 rounded bg-black/30 capitalize">{issue.severity}</span>
                      </td>
                      <td className="p-1 align-top font-mono">
                        <button
                          type="button"
                          className="text-[var(--accent)] hover:underline"
                          onClick={() => void openPath(issue.file_path)}
                        >
                          {issue.file_path}
                        </button>
                      </td>
                      <td className="p-1 align-top text-[var(--text-secondary)]">{issue.message}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {(review.suggestions?.length || 0) > 0 && (
        <div className="space-y-1">
          <p className="text-xs text-[var(--text-secondary)] uppercase tracking-wide">Suggestions</p>
          {review.suggestions?.map((suggestion, index) => {
            const offset = (review.issues?.length || 0) + index
            const key = String(offset)
            const path = pathFromSuggestion(suggestion)
            return (
              <div
                key={key}
                className="flex items-start gap-2 p-2 rounded bg-[var(--bg-tertiary)] border border-[var(--border)]"
              >
                <input
                  type="checkbox"
                  className="mt-1"
                  checked={selected.has(key)}
                  onChange={() => toggle(key)}
                />
                <div className="flex-1 min-w-0">
                  <p className="whitespace-pre-wrap break-words">{suggestion}</p>
                  <div className="flex gap-2 mt-1">
                    {path && (
                      <Button
                        variant="ghost"
                        className="text-xs h-6 px-1"
                        onClick={() => void openPath(path)}
                      >
                        <ExternalLink size={12} className="mr-1" />
                        Open file
                      </Button>
                    )}
                    <Button
                      variant="ghost"
                      className="text-xs h-6 px-1"
                      onClick={() => {
                        navigator.clipboard.writeText(suggestion)
                        showSuccess('Copied')
                      }}
                    >
                      <Copy size={12} className="mr-1" />
                      Copy
                    </Button>
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      )}

      <div className="flex flex-wrap gap-2">
        <Button
          variant="secondary"
          disabled={busy || retryDisabled || selectedItems.length === 0}
          onClick={() => void onRetryWithFeedback(buildFeedback(selectedItems))}
        >
          Retry with selected ({selectedItems.length})
        </Button>
        <Button
          variant="secondary"
          disabled={busy || retryDisabled || allFeedbackItems.length === 0}
          onClick={() => void onRetryWithFeedback(buildFeedback(allFeedbackItems))}
        >
          Retry with all feedback
        </Button>
      </div>
    </div>
  )
}
