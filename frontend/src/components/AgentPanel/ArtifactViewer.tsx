import { useState } from 'react'
import {
  ChevronDown,
  ChevronRight,
  Code2,
  Compass,
  Copy,
  ExternalLink,
  FileEdit,
  FileMinus,
  FilePlus,
  FileText,
  FlaskConical,
  LayoutTemplate,
  ListChecks,
} from 'lucide-react'
import { openRunFile } from '@/lib/openRunFile'
import { showError, showSuccess } from '@/lib/toast'
import { Button } from '@/components/ui/primitives'
import { useEditorStore, useProjectStore } from '@/store'
import {
  formatRunRelativeTime,
  isReviewArtifactType,
  type RunArtifact,
} from '@/types/runs'
import { ReviewArtifactPanel } from './ReviewArtifactPanel'

interface ArtifactViewerProps {
  artifacts: RunArtifact[]
  loading: boolean
  runId?: string | null
  onRetryWithFeedback?: (feedback: string) => void | Promise<void>
  retryBusy?: boolean
}

// --- helpers --------------------------------------------------------------

type LucideIcon = React.ComponentType<{ size?: number; className?: string }>

interface ArtifactMeta {
  label: string
  icon: LucideIcon
}

function humanize(value: string): string {
  return value
    .split('_')
    .filter(Boolean)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ')
}

function describeArtifact(type: string): ArtifactMeta {
  if (type.startsWith('review_')) {
    const attempt = type.slice('review_'.length)
    const suffix = attempt && !Number.isNaN(Number(attempt)) ? ` · attempt ${attempt}` : ''
    return { label: `Reviewer${suffix}`, icon: ListChecks }
  }
  const table: Record<string, ArtifactMeta> = {
    plan: { label: 'Planner', icon: ListChecks },
    architect: { label: 'Architect', icon: Compass },
    ui_design: { label: 'UI Designer', icon: LayoutTemplate },
    coder: { label: 'Coder', icon: Code2 },
    test_plan: { label: 'Tester', icon: FlaskConical },
  }
  return table[type] || { label: humanize(type), icon: FileText }
}

function fileActionMeta(action: string): { cls: string; icon: LucideIcon } {
  const lower = action.toLowerCase()
  if (/(create|add|new)/.test(lower))
    return { cls: 'bg-[var(--success)]/15 text-[var(--success)]', icon: FilePlus }
  if (/(delete|remove|drop)/.test(lower))
    return { cls: 'bg-[var(--error)]/15 text-[var(--error)]', icon: FileMinus }
  if (/(update|modify|edit|refactor|rename|move|patch)/.test(lower))
    return { cls: 'bg-[var(--accent)]/15 text-[var(--accent)]', icon: FileEdit }
  return { cls: 'bg-[var(--bg-tertiary)] text-[var(--text-primary)]', icon: FileText }
}

function asString(value: unknown): string {
  if (typeof value === 'string') return value
  if (value === null || value === undefined) return ''
  return String(value)
}

function asStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) return []
  return value
    .map((item) => (typeof item === 'string' ? item : item == null ? '' : JSON.stringify(item)))
    .filter((line) => line.length > 0)
}

function asRecordArray(value: unknown): Record<string, unknown>[] {
  if (!Array.isArray(value)) return []
  return value.filter(
    (item): item is Record<string, unknown> => item !== null && typeof item === 'object',
  )
}

function copyText(text: string, message = 'Copied to clipboard') {
  navigator.clipboard.writeText(text)
  showSuccess(message)
}

// --- shared sub-components ------------------------------------------------

function SectionHeading({ children }: { children: React.ReactNode }) {
  return (
    <p className="text-[10px] uppercase tracking-wide text-[var(--text-secondary)] mb-1">
      {children}
    </p>
  )
}

function Prose({ text }: { text: string }) {
  if (!text) return null
  return (
    <p className="text-sm text-[var(--text-primary)] whitespace-pre-wrap break-words leading-relaxed">
      {text}
    </p>
  )
}

function ChipList({ items }: { items: string[] }) {
  if (items.length === 0) return null
  return (
    <div className="flex flex-wrap gap-1">
      {items.map((item, i) => (
        <span
          key={`${item}-${i}`}
          className="px-1.5 py-0.5 rounded text-xs bg-[var(--bg-tertiary)] text-[var(--text-primary)] border border-[var(--border)] font-mono"
        >
          {item}
        </span>
      ))}
    </div>
  )
}

function BulletList({
  items,
  tone = 'default',
}: {
  items: string[]
  tone?: 'default' | 'warning'
}) {
  if (items.length === 0) return null
  const dotClass = tone === 'warning' ? 'bg-[var(--warning)]' : 'bg-[var(--text-secondary)]'
  return (
    <ul className="space-y-1 text-sm">
      {items.map((line, i) => (
        <li key={i} className="flex gap-2 text-[var(--text-primary)]">
          <span className={`mt-1.5 w-1 h-1 rounded-full shrink-0 ${dotClass}`} />
          <span className="whitespace-pre-wrap break-words flex-1">{line}</span>
        </li>
      ))}
    </ul>
  )
}

function useOpenFile(
  runId?: string | null,
  artifacts?: RunArtifact[],
  changeEntry?: Record<string, unknown>,
  inlineContent?: string | null,
) {
  const projectId = useProjectStore((s) => s.currentProjectId)
  const openTab = useEditorStore((s) => s.openTab)
  return async (path: string) => {
    const opened = await openRunFile({
      projectId,
      runId,
      path,
      artifacts,
      changeEntry,
      inlineContent,
      openTab,
    })
    if (!opened) {
      showError(new Error(`File not found: ${path}`))
    }
  }
}

function FileLink({
  path,
  className,
  runId,
  artifacts,
  changeEntry,
  inlineContent,
}: {
  path: string
  className?: string
  runId?: string | null
  artifacts?: RunArtifact[]
  changeEntry?: Record<string, unknown>
  inlineContent?: string | null
}) {
  const openFile = useOpenFile(runId, artifacts, changeEntry, inlineContent)
  return (
    <button
      type="button"
      className={`text-[var(--accent)] hover:underline font-mono text-xs inline-flex items-center gap-1 min-w-0 ${
        className || ''
      }`}
      onClick={() => void openFile(path)}
      title={`Open ${path}`}
    >
      <span className="truncate">{path}</span>
      <ExternalLink size={11} className="shrink-0 opacity-70" />
    </button>
  )
}

// --- artifact-specific renderers ------------------------------------------

function PlanArtifact({ content }: { content: Record<string, unknown> }) {
  const summary = asString(content.summary)
  const steps = asRecordArray(content.steps)
  const risks = asStringArray(content.risks)

  return (
    <div className="space-y-3">
      {summary && (
        <div>
          <SectionHeading>Summary</SectionHeading>
          <Prose text={summary} />
        </div>
      )}
      {steps.length > 0 && (
        <div>
          <SectionHeading>Steps ({steps.length})</SectionHeading>
          <ol className="space-y-2">
            {steps.map((step, i) => {
              const stepId = asString(step.step_id) || String(i + 1)
              const title = asString(step.title) || `Step ${i + 1}`
              const description = asString(step.description)
              const criteria = asStringArray(step.acceptance_criteria)
              return (
                <li
                  key={`${stepId}-${i}`}
                  className="rounded border border-[var(--border)] bg-[var(--bg-tertiary)]/40 p-2"
                >
                  <div className="flex items-baseline gap-2">
                    <span className="text-xs font-mono text-[var(--text-secondary)] shrink-0">
                      {stepId}
                    </span>
                    <p className="text-sm font-medium text-[var(--text-primary)]">{title}</p>
                  </div>
                  {description && (
                    <p className="text-xs text-[var(--text-secondary)] mt-1 whitespace-pre-wrap break-words leading-relaxed">
                      {description}
                    </p>
                  )}
                  {criteria.length > 0 && (
                    <div className="mt-2">
                      <SectionHeading>Acceptance criteria</SectionHeading>
                      <BulletList items={criteria} />
                    </div>
                  )}
                </li>
              )
            })}
          </ol>
        </div>
      )}
      {risks.length > 0 && (
        <div>
          <SectionHeading>Risks</SectionHeading>
          <BulletList items={risks} tone="warning" />
        </div>
      )}
    </div>
  )
}

function ArchitectArtifact({
  content,
  runId,
  artifacts,
}: {
  content: Record<string, unknown>
  runId?: string | null
  artifacts?: RunArtifact[]
}) {
  const overview = asString(content.overview)
  const modules = asStringArray(content.modules)
  const fileChanges = asRecordArray(content.file_changes)
  const dependencies = asStringArray(content.dependencies)

  return (
    <div className="space-y-3">
      {overview && (
        <div>
          <SectionHeading>Overview</SectionHeading>
          <Prose text={overview} />
        </div>
      )}
      {modules.length > 0 && (
        <div>
          <SectionHeading>Modules ({modules.length})</SectionHeading>
          <ChipList items={modules} />
        </div>
      )}
      {fileChanges.length > 0 && (
        <div>
          <SectionHeading>File changes ({fileChanges.length})</SectionHeading>
          <div className="space-y-1.5">
            {fileChanges.map((entry, i) => {
              const path = asString(entry.path)
              const action = asString(entry.action) || 'change'
              const rationale = asString(entry.rationale)
              const meta = fileActionMeta(action)
              const ActionIcon = meta.icon
              return (
                <div
                  key={`${path}-${i}`}
                  className="rounded border border-[var(--border)] bg-[var(--bg-tertiary)]/40 p-2"
                >
                  <div className="flex items-center gap-2 flex-wrap">
                    <span
                      className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] uppercase tracking-wide ${meta.cls}`}
                    >
                      <ActionIcon size={11} />
                      {action}
                    </span>
                    {path ? (
                      <FileLink path={path} className="flex-1" runId={runId} artifacts={artifacts} />
                    ) : (
                      <span className="text-xs text-[var(--text-secondary)] italic">
                        unspecified path
                      </span>
                    )}
                  </div>
                  {rationale && (
                    <p className="text-xs text-[var(--text-secondary)] mt-1 whitespace-pre-wrap break-words leading-relaxed">
                      {rationale}
                    </p>
                  )}
                </div>
              )
            })}
          </div>
        </div>
      )}
      {dependencies.length > 0 && (
        <div>
          <SectionHeading>Dependencies</SectionHeading>
          <ChipList items={dependencies} />
        </div>
      )}
    </div>
  )
}

function UiDesignArtifact({ content }: { content: Record<string, unknown> }) {
  const layout = asString(content.layout_description)
  const components = asRecordArray(content.components)
  const styling = asString(content.styling_notes)
  const a11y = asStringArray(content.accessibility_notes)

  return (
    <div className="space-y-3">
      {layout && (
        <div>
          <SectionHeading>Layout</SectionHeading>
          <Prose text={layout} />
        </div>
      )}
      {components.length > 0 && (
        <div>
          <SectionHeading>Components ({components.length})</SectionHeading>
          <div className="space-y-1.5">
            {components.map((comp, i) => {
              const name = asString(comp.name) || `Component ${i + 1}`
              const componentType = asString(comp.component_type)
              const props =
                comp.props && typeof comp.props === 'object' && !Array.isArray(comp.props)
                  ? Object.entries(comp.props as Record<string, unknown>)
                  : []
              return (
                <div
                  key={`${name}-${i}`}
                  className="rounded border border-[var(--border)] bg-[var(--bg-tertiary)]/40 p-2"
                >
                  <div className="flex items-baseline gap-2 flex-wrap">
                    <p className="text-sm font-medium text-[var(--text-primary)]">{name}</p>
                    {componentType && (
                      <span className="text-xs text-[var(--text-secondary)] font-mono">
                        {componentType}
                      </span>
                    )}
                  </div>
                  {props.length > 0 && (
                    <div className="mt-1 text-xs font-mono space-y-0.5">
                      {props.map(([k, v]) => (
                        <div key={k} className="flex gap-2">
                          <span className="text-[var(--accent)] shrink-0">{k}:</span>
                          <span className="text-[var(--text-primary)] break-all">
                            {asString(v)}
                          </span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        </div>
      )}
      {styling && (
        <div>
          <SectionHeading>Styling notes</SectionHeading>
          <Prose text={styling} />
        </div>
      )}
      {a11y.length > 0 && (
        <div>
          <SectionHeading>Accessibility notes</SectionHeading>
          <BulletList items={a11y} />
        </div>
      )}
    </div>
  )
}

function CoderArtifact({
  content,
  runId,
  artifacts,
}: {
  content: Record<string, unknown>
  runId?: string | null
  artifacts?: RunArtifact[]
}) {
  const summary = asString(content.summary)
  const fileChanges = asRecordArray(content.file_changes)
  const requiresApproval = Boolean(content.requires_operator_approval)

  return (
    <div className="space-y-3">
      {requiresApproval && (
        <div className="rounded px-2 py-1 text-xs font-medium bg-[var(--warning)]/15 text-[var(--warning)]">
          Requires operator approval before promotion.
        </div>
      )}
      {summary && (
        <div>
          <SectionHeading>Summary</SectionHeading>
          <Prose text={summary} />
        </div>
      )}
      {fileChanges.length > 0 && (
        <div>
          <SectionHeading>File changes ({fileChanges.length})</SectionHeading>
          <div className="space-y-1.5">
            {fileChanges.map((entry, i) => (
              <CoderFileChange
                key={`${asString(entry.path)}-${i}`}
                entry={entry}
                runId={runId}
                artifacts={artifacts}
              />
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

function CoderFileChange({
  entry,
  runId,
  artifacts,
}: {
  entry: Record<string, unknown>
  runId?: string | null
  artifacts?: RunArtifact[]
}) {
  const [open, setOpen] = useState(false)
  const path = asString(entry.path)
  const lineChanges = asRecordArray(entry.line_changes)
  const fullContent = typeof entry.full_content === 'string' ? entry.full_content : null
  const replacementCount = lineChanges.length
  const summaryText = fullContent
    ? `full file (${fullContent.split('\n').length} lines)`
    : `${replacementCount} edit${replacementCount === 1 ? '' : 's'}`

  return (
    <div className="rounded border border-[var(--border)] bg-[var(--bg-tertiary)]/40">
      <div className="flex items-center gap-2 p-2">
        <button
          type="button"
          className="p-0.5 hover:bg-[var(--bg-tertiary)] rounded shrink-0"
          onClick={() => setOpen(!open)}
          title={open ? 'Collapse' : 'Expand'}
        >
          {open ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
        </button>
        {path ? (
          <FileLink
            path={path}
            className="flex-1"
            runId={runId}
            artifacts={artifacts}
            changeEntry={entry}
            inlineContent={fullContent}
          />
        ) : (
          <span className="text-xs text-[var(--text-secondary)] italic flex-1">
            unspecified path
          </span>
        )}
        <span className="text-[10px] text-[var(--text-secondary)] shrink-0">{summaryText}</span>
      </div>
      {open && (lineChanges.length > 0 || fullContent !== null) && (
        <div className="border-t border-[var(--border)] p-2 space-y-2">
          {lineChanges.map((change, i) => {
            const start = Number(change.start_line) || 0
            const end = Number(change.end_line) || start
            const newContent = asString(change.new_content)
            return (
              <div key={i} className="space-y-0.5">
                <div className="flex items-center justify-between">
                  <p className="text-[10px] uppercase tracking-wide text-[var(--text-secondary)]">
                    lines {start}–{end}
                  </p>
                  <button
                    type="button"
                    className="opacity-60 hover:opacity-100"
                    onClick={() => copyText(newContent, 'Copied snippet')}
                    title="Copy snippet"
                  >
                    <Copy size={11} />
                  </button>
                </div>
                <pre className="text-xs font-mono bg-black/40 rounded p-2 overflow-auto whitespace-pre text-[var(--text-primary)] border border-[var(--border)] max-h-48">
                  {newContent}
                </pre>
              </div>
            )
          })}
          {fullContent !== null && (
            <div className="space-y-0.5">
              <div className="flex items-center justify-between">
                <p className="text-[10px] uppercase tracking-wide text-[var(--text-secondary)]">
                  full file contents
                </p>
                <button
                  type="button"
                  className="opacity-60 hover:opacity-100"
                  onClick={() => copyText(fullContent, 'Copied file contents')}
                  title="Copy file"
                >
                  <Copy size={11} />
                </button>
              </div>
              <pre className="text-xs font-mono bg-black/40 rounded p-2 overflow-auto whitespace-pre text-[var(--text-primary)] border border-[var(--border)] max-h-64">
                {fullContent}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function TestPlanArtifact({ content }: { content: Record<string, unknown> }) {
  const passed = Boolean(content.passed)
  const summary = asString(content.summary)
  const commands = asRecordArray(content.commands)
  const notes = asStringArray(content.notes)

  return (
    <div className="space-y-3">
      <div
        className={`rounded px-2 py-1 text-xs font-medium ${
          passed
            ? 'bg-[var(--success)]/15 text-[var(--success)]'
            : 'bg-[var(--error)]/15 text-[var(--error)]'
        }`}
      >
        {passed ? 'All tests passed' : 'Tests failed'}
      </div>
      {summary && (
        <div>
          <SectionHeading>Summary</SectionHeading>
          <Prose text={summary} />
        </div>
      )}
      {commands.length > 0 && (
        <div>
          <SectionHeading>Commands ({commands.length})</SectionHeading>
          <div className="space-y-1.5">
            {commands.map((cmd, i) => {
              const command = asString(cmd.command)
              const description = asString(cmd.description)
              return (
                <div
                  key={`${command}-${i}`}
                  className="rounded border border-[var(--border)] bg-[var(--bg-tertiary)]/40 p-2"
                >
                  <div className="flex items-center gap-2">
                    <code className="text-xs font-mono text-[var(--text-primary)] bg-black/40 px-1.5 py-0.5 rounded flex-1 break-all">
                      {command}
                    </code>
                    <button
                      type="button"
                      className="opacity-60 hover:opacity-100 shrink-0"
                      onClick={() => copyText(command, 'Copied command')}
                      title="Copy command"
                    >
                      <Copy size={12} />
                    </button>
                  </div>
                  {description && (
                    <p className="text-xs text-[var(--text-secondary)] mt-1 whitespace-pre-wrap break-words leading-relaxed">
                      {description}
                    </p>
                  )}
                </div>
              )
            })}
          </div>
        </div>
      )}
      {notes.length > 0 && (
        <div>
          <SectionHeading>Notes</SectionHeading>
          <BulletList items={notes} />
        </div>
      )}
    </div>
  )
}

// --- raw JSON fallback ----------------------------------------------------

function JsonSection({
  label,
  value,
  depth = 0,
}: {
  label: string
  value: unknown
  depth?: number
}) {
  const [open, setOpen] = useState(depth < 1)
  const isObject = value !== null && typeof value === 'object'
  const text = isObject ? JSON.stringify(value, null, 2) : String(value)

  if (!isObject) {
    return (
      <div className="pl-2 py-0.5" style={{ marginLeft: depth * 8 }}>
        <span className="text-[var(--text-secondary)]">{label}: </span>
        <span className="text-[var(--text-primary)] break-words">{text}</span>
        <button
          className="ml-2 opacity-60 hover:opacity-100"
          onClick={() => copyText(text)}
          title="Copy"
        >
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
      <div className="flex items-center gap-1 py-0.5 hover:bg-[var(--bg-tertiary)] rounded">
        <button className="p-0.5" onClick={() => setOpen(!open)}>
          {open ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
        </button>
        <span className="text-[var(--accent)]">{label}</span>
        <span className="text-[var(--text-secondary)] text-xs">
          {Array.isArray(value) ? `[${value.length}]` : `{${entries.length}}`}
        </span>
        <button
          className="ml-auto opacity-60 hover:opacity-100 px-1"
          onClick={() => copyText(text, 'Copied JSON')}
          title="Copy JSON"
        >
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

// --- dispatcher + outer viewer --------------------------------------------

function RenderTypedArtifact({
  artifact,
  runId,
  artifacts,
}: {
  artifact: RunArtifact
  runId?: string | null
  artifacts?: RunArtifact[]
}) {
  switch (artifact.artifact_type) {
    case 'plan':
      return <PlanArtifact content={artifact.content} />
    case 'architect':
      return <ArchitectArtifact content={artifact.content} runId={runId} artifacts={artifacts} />
    case 'ui_design':
      return <UiDesignArtifact content={artifact.content} />
    case 'coder':
      return <CoderArtifact content={artifact.content} runId={runId} artifacts={artifacts} />
    case 'test_plan':
      return <TestPlanArtifact content={artifact.content} />
    default:
      return (
        <div className="text-xs font-mono">
          <JsonSection label="content" value={artifact.content} />
        </div>
      )
  }
}

function ArtifactBody({
  artifact,
  runId,
  artifacts,
  onRetryWithFeedback,
  retryBusy,
}: {
  artifact: RunArtifact
  runId?: string | null
  artifacts?: RunArtifact[]
  onRetryWithFeedback?: (feedback: string) => void | Promise<void>
  retryBusy?: boolean
}) {
  const [showRaw, setShowRaw] = useState(false)

  if (isReviewArtifactType(artifact.artifact_type)) {
    return (
      <div className="space-y-2">
        <ReviewArtifactPanel
          artifact={artifact}
          runId={runId}
          artifacts={artifacts}
          onRetryWithFeedback={onRetryWithFeedback || (() => {})}
          busy={retryBusy}
        />
        <RawJsonToggle showRaw={showRaw} onToggle={() => setShowRaw(!showRaw)} content={artifact.content} />
      </div>
    )
  }

  return (
    <div className="space-y-2">
      <RenderTypedArtifact artifact={artifact} runId={runId} artifacts={artifacts} />
      <RawJsonToggle showRaw={showRaw} onToggle={() => setShowRaw(!showRaw)} content={artifact.content} />
    </div>
  )
}

function RawJsonToggle({
  showRaw,
  onToggle,
  content,
}: {
  showRaw: boolean
  onToggle: () => void
  content: Record<string, unknown>
}) {
  return (
    <div>
      <button
        type="button"
        className="text-[11px] text-[var(--text-secondary)] hover:text-[var(--text-primary)] inline-flex items-center gap-1"
        onClick={onToggle}
      >
        {showRaw ? <ChevronDown size={11} /> : <ChevronRight size={11} />}
        {showRaw ? 'Hide' : 'Show'} raw JSON
      </button>
      {showRaw && (
        <div className="text-xs font-mono mt-1">
          <JsonSection label="content" value={content} />
        </div>
      )}
    </div>
  )
}

export function ArtifactViewer({
  artifacts,
  loading,
  runId,
  onRetryWithFeedback,
  retryBusy,
}: ArtifactViewerProps) {
  const [expanded, setExpanded] = useState<Record<number, boolean>>({})

  if (loading) {
    return <p className="text-xs text-[var(--text-secondary)] p-2">Loading artifacts...</p>
  }

  if (artifacts.length === 0) return null

  return (
    <div className="border-t border-[var(--border)] pt-2">
      <p className="text-xs text-[var(--text-secondary)] mb-1 px-1">
        Artifacts ({artifacts.length})
      </p>
      <div className="max-h-64 overflow-auto space-y-2">
        {artifacts.map((a) => {
          const meta = describeArtifact(a.artifact_type)
          const Icon = meta.icon
          const isOpen = expanded[a.id] !== false
          const relativeTime = formatRunRelativeTime(a.created_at)
          return (
            <div
              key={a.id}
              className="bg-[#1a1a1a] rounded border border-[var(--border)] overflow-hidden"
            >
              <div
                className="flex items-center gap-2 px-2 py-1.5 cursor-pointer hover:bg-[var(--bg-tertiary)]/40 transition-colors"
                onClick={() => setExpanded((s) => ({ ...s, [a.id]: !isOpen }))}
              >
                {isOpen ? (
                  <ChevronDown size={12} className="shrink-0" />
                ) : (
                  <ChevronRight size={12} className="shrink-0" />
                )}
                <Icon size={13} className="text-[var(--text-secondary)] shrink-0" />
                <span className="text-xs font-medium text-[var(--text-primary)] truncate">
                  {meta.label}
                </span>
                <span
                  className="text-[10px] text-[var(--text-secondary)] font-mono truncate"
                  title={a.artifact_type}
                >
                  {a.artifact_type}
                </span>
                <div className="flex items-center gap-1 ml-auto shrink-0">
                  {relativeTime && (
                    <span className="text-[10px] text-[var(--text-secondary)]">{relativeTime}</span>
                  )}
                  <Button
                    variant="ghost"
                    className="text-xs py-0 px-1 h-5"
                    onClick={(e) => {
                      e.stopPropagation()
                      copyText(JSON.stringify(a.content, null, 2), 'Copied artifact JSON')
                    }}
                    title="Copy artifact JSON"
                  >
                    <Copy size={12} />
                  </Button>
                </div>
              </div>
              {isOpen && (
                <div className="p-2 border-t border-[var(--border)]">
                  <ArtifactBody
                    artifact={a}
                    runId={runId}
                    artifacts={artifacts}
                    onRetryWithFeedback={onRetryWithFeedback}
                    retryBusy={retryBusy}
                  />
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
