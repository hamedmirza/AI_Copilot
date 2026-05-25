import { ExternalLink, ImageIcon } from 'lucide-react'
import { api } from '@/api/client'
import { evidenceFilename } from '@/lib/browserToolLabels'
import { Button } from '@/components/ui/primitives'
import { useUIStore } from '@/store'

type VisualCheck = {
  url?: string
  description?: string
  expected?: string
  passed?: boolean
  notes?: string
  screenshot_path?: string | null
  step_log?: Array<Record<string, unknown>>
  visible_text_preview?: string
}

export type VisualEvidencePayload = {
  passed?: boolean
  browser_client_required?: boolean
  error?: string
  checks?: VisualCheck[]
  server_preflight?: Record<string, { passed?: boolean; notes?: string }>
}

interface VisualEvidencePanelProps {
  runId: string
  evidence: VisualEvidencePayload | null | undefined
  compact?: boolean
  showActions?: boolean
  onContinueVisual?: () => void | Promise<void>
  continueBusy?: boolean
}

function CheckRow({
  runId,
  check,
  index,
  compact,
}: {
  runId: string
  check: VisualCheck
  index: number
  compact?: boolean
}) {
  const filename = check.screenshot_path ? evidenceFilename(check.screenshot_path) : null
  const imgUrl = filename ? api.runs.evidenceUrl(runId, filename) : null
  const passed = Boolean(check.passed)

  return (
    <div className="rounded border border-[var(--border)] bg-[var(--bg-tertiary)]/40 p-2 space-y-2">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className={`text-xs font-medium ${passed ? 'text-[var(--success)]' : 'text-[var(--error)]'}`}>
            Check {index + 1}: {passed ? 'Passed' : 'Failed'}
          </p>
          {check.description && (
            <p className="text-xs text-[var(--text-primary)] mt-0.5">{check.description}</p>
          )}
          {check.url && (
            <p className="text-[11px] text-[var(--text-secondary)] font-mono truncate mt-0.5" title={check.url}>
              {check.url}
            </p>
          )}
          {check.expected && !compact && (
            <p className="text-[11px] text-[var(--text-secondary)] mt-1">
              Expected: {check.expected}
            </p>
          )}
          {check.notes && check.notes !== 'ok' && (
            <p className="text-[11px] text-[var(--error)] mt-1">{check.notes}</p>
          )}
        </div>
        {imgUrl && (
          <a
            href={imgUrl}
            target="_blank"
            rel="noreferrer"
            className="shrink-0 block rounded border border-[var(--border)] overflow-hidden hover:opacity-90"
            title="Open screenshot"
          >
            <img
              src={imgUrl}
              alt={`Visual check ${index + 1}`}
              className={compact ? 'w-20 h-14 object-cover' : 'w-28 h-20 object-cover'}
            />
          </a>
        )}
      </div>
      {!compact && Array.isArray(check.step_log) && check.step_log.length > 0 && (
        <ul className="text-[10px] text-[var(--text-secondary)] space-y-0.5">
          {check.step_log.map((step, i) => (
            <li key={i}>
              {String(step.action || 'step')}: {step.ok ? 'ok' : String(step.error || 'failed')}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

export function VisualEvidencePanel({
  runId,
  evidence,
  compact,
  showActions,
  onContinueVisual,
  continueBusy,
}: VisualEvidencePanelProps) {
  if (!evidence) {
    return (
      <p className="text-xs text-[var(--text-secondary)]">
        No visual evidence artifact yet. Pipeline runs IDE browser checks when frontend files change.
      </p>
    )
  }

  const checks = Array.isArray(evidence.checks) ? evidence.checks : []
  const screenshotCount = checks.filter((c) => c.screenshot_path).length
  const passed = Boolean(evidence.passed)
  const needsClient = Boolean(evidence.browser_client_required)

  return (
    <div className="space-y-2">
      <div
        className={`rounded px-2 py-1 text-xs font-medium inline-flex items-center gap-1.5 ${
          needsClient
            ? 'bg-[var(--warning)]/15 text-[var(--warning)]'
            : passed
              ? 'bg-[var(--success)]/15 text-[var(--success)]'
              : 'bg-[var(--error)]/15 text-[var(--error)]'
        }`}
      >
        <ImageIcon size={12} />
        {needsClient
          ? 'IDE browser required — open Copilot with this project loaded'
          : passed
            ? `Visual verification passed (${screenshotCount} screenshot${screenshotCount === 1 ? '' : 's'})`
            : 'Visual verification failed'}
      </div>

      {evidence.error && (
        <p className="text-xs text-[var(--text-secondary)]">{evidence.error}</p>
      )}

      {checks.length > 0 ? (
        <div className="space-y-2">
          {checks.map((check, index) => (
            <CheckRow key={`${check.url}-${index}`} runId={runId} check={check} index={index} compact={compact} />
          ))}
        </div>
      ) : !needsClient && (
        <p className="text-xs text-[var(--text-secondary)]">No visual checks were recorded.</p>
      )}

      {showActions && needsClient && onContinueVisual && (
        <div className="flex flex-wrap gap-2 pt-1">
          <Button
            variant="secondary"
            className="text-xs h-7"
            disabled={continueBusy}
            onClick={() => void onContinueVisual()}
          >
            Continue visual verification
          </Button>
          <Button
            variant="ghost"
            className="text-xs h-7 inline-flex items-center gap-1"
            onClick={() => useUIStore.getState().setActiveCenterView('browser')}
          >
            <ExternalLink size={12} />
            Open browser
          </Button>
        </div>
      )}
    </div>
  )
}
