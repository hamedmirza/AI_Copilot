import { parseApiDateTime } from '@/lib/datetime'

export type RunStatus =
  | 'pending'
  | 'running'
  | 'awaiting_approval'
  | 'changes_requested'
  | 'blocked'
  | 'completed'
  | 'failed'
  | 'cancelled'
  | 'idle'

export interface RunSummary {
  id: string
  status: string
  current_stage?: string | null
  task_id?: string
  error_message?: string | null
  created_at: string
}

export interface PromoteSnapshot {
  paths: string[]
  created_at: string
}

export interface RunDetail {
  id: string
  project_id: string
  task_id: string
  status: string
  current_stage: string | null
  workspace_path: string | null
  review_attempts: number
  error_message: string | null
  operator_feedback: string | null
  promote_snapshot: PromoteSnapshot | null
  created_at: string
  updated_at: string
}

export interface RunEvent {
  id?: number
  type: string
  event_type?: string
  stage?: string | null
  severity?: string
  message?: string
  payload?: Record<string, unknown>
  created_at?: string
  run_id?: string
}

export interface RunArtifact {
  id: number
  artifact_type: string
  content: Record<string, unknown>
  created_at: string
}

export interface ReviewIssue {
  severity: string
  file_path: string
  message: string
}

export interface ReviewContent {
  approved?: boolean
  summary?: string
  issues?: ReviewIssue[]
  suggestions?: string[]
}

const STATUS_COLORS: Record<string, string> = {
  completed: 'bg-[var(--success)]/20 text-[var(--success)]',
  running: 'bg-[var(--accent)]/20 text-[var(--accent)]',
  pending: 'bg-gray-500/20 text-gray-300',
  awaiting_approval: 'bg-[var(--warning)]/20 text-[var(--warning)]',
  changes_requested: 'bg-[var(--warning)]/20 text-[var(--warning)]',
  blocked: 'bg-[var(--error)]/20 text-[var(--error)]',
  failed: 'bg-[var(--error)]/20 text-[var(--error)]',
  cancelled: 'bg-gray-500/20 text-gray-400',
}

export function runStatusLabel(status: string): string {
  return status.replaceAll('_', ' ')
}

export function runStatusBadgeClass(status: string): string {
  return STATUS_COLORS[status] || 'bg-gray-500/20 text-gray-300'
}

export function isReviewArtifactType(artifactType: string): boolean {
  return artifactType.startsWith('review_')
}

export function parseReviewContent(content: Record<string, unknown>): ReviewContent {
  return {
    approved: Boolean(content.approved),
    summary: typeof content.summary === 'string' ? content.summary : '',
    issues: Array.isArray(content.issues)
      ? content.issues.map((row) => {
          const issue = row as Record<string, unknown>
          return {
            severity: String(issue.severity || 'info'),
            file_path: String(issue.file_path || ''),
            message: String(issue.message || ''),
          }
        })
      : [],
    suggestions: Array.isArray(content.suggestions)
      ? content.suggestions.map((s) => String(s))
      : [],
  }
}

export function latestReviewArtifact(artifacts: RunArtifact[]): RunArtifact | null {
  const reviews = artifacts.filter((a) => isReviewArtifactType(a.artifact_type))
  if (reviews.length === 0) return null
  return reviews[reviews.length - 1]
}

export function isRetryableStatus(status: string): boolean {
  return ['blocked', 'changes_requested'].includes(status)
}

export function canRollbackWorkspace(status: string): boolean {
  return ['awaiting_approval', 'changes_requested', 'blocked', 'failed'].includes(status)
}

export function canRollbackPromote(status: string, snapshot: PromoteSnapshot | null | undefined): boolean {
  return status === 'completed' && !!snapshot?.paths?.length
}

export function formatRunRelativeTime(iso: string): string {
  const date = parseApiDateTime(iso)
  if (!date) return ''
  const diffMs = date.getTime() - Date.now()
  const minute = 60 * 1000
  const hour = 60 * minute
  const day = 24 * hour
  const fmt = new Intl.RelativeTimeFormat(undefined, { numeric: 'auto' })
  if (Math.abs(diffMs) < hour) return fmt.format(Math.round(diffMs / minute), 'minute')
  if (Math.abs(diffMs) < day) return fmt.format(Math.round(diffMs / hour), 'hour')
  return fmt.format(Math.round(diffMs / day), 'day')
}
