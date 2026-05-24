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
  display_name?: string
  status: string
  current_stage?: string | null
  task_id?: string
  task_kind?: string | null
  failure_class?: string | null
  recovery_status?: string | null
  error_message?: string | null
  created_at: string
}

export function hasRecoveryMetadata(run: RunSummary): boolean {
  return Boolean(run.failure_class || run.recovery_status)
}

export interface PromoteSnapshot {
  paths: string[]
  created_at: string
}

export interface RunDetail {
  id: string
  display_name?: string
  project_id: string
  task_id: string
  status: string
  current_stage: string | null
  workspace_path: string | null
  review_attempts: number
  error_message: string | null
  operator_feedback: string | null
  promote_snapshot: PromoteSnapshot | null
  task_kind?: string | null
  failure_class?: string | null
  failure_subclass?: string | null
  failure_signature?: string | null
  recovery_status?: string | null
  superseded_by_run_id?: string | null
  created_at: string
  updated_at: string
}

export interface FailureSummaryRun {
  id: string
  status: string
  current_stage?: string | null
  error_message?: string | null
  failure_subclass?: string | null
  recovery_status?: string | null
  superseded_by_run_id?: string | null
  created_at: string
}

export interface FailureSummaryGroup {
  count: number
  actionable: number
  runs: FailureSummaryRun[]
}

export interface FailureSummaryResponse {
  groups: Record<string, FailureSummaryGroup>
  total_runs: number
}

export interface LessonContent {
  title?: string
  scope?: string
  source_run_id?: string
  stages?: string[]
  kind?: string
  summary?: string
  trigger_pattern?: string
  guidance?: string
  confidence?: number
  applies_to_paths?: string[]
  applies_to_task_kinds?: string[]
  superseded?: boolean
  body?: string
}

export interface LessonRecord {
  id: number
  project_id: string
  run_id?: string | null
  title: string
  content: LessonContent
  created_at: string
}

export interface GlobalSkillRecord {
  id: string
  name: string
  summary: string
  content: LessonContent
  source_lesson_id?: number | null
  source_run_id?: string | null
  origin_project_id?: string | null
  kind: string
  stages: string[]
  tags: string[]
  confidence: number
  promotion_state: string
  times_applied: number
  times_helpful: number
  times_harmful: number
  created_at: string
  updated_at: string
}

export interface PostmortemRecord {
  id: number
  artifact_type: string
  content: {
    run_id: string
    project_id: string
    terminal_status: string
    stage?: string | null
    task_kind?: string | null
    failure_class: string
    failure_subclass?: string | null
    failure_signature?: string | null
    root_cause_summary: string
    operator_visible_symptom: string
    fix_recommendation: string
    confidence: number
    evidence?: {
      event_ids?: number[]
      artifact_types?: string[]
      key_error_lines?: string[]
    }
  }
  created_at: string
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

export function runDisplayLabel(run: Pick<RunSummary, 'id' | 'display_name'>): string {
  const name = String(run.display_name || '').trim()
  if (name) return name
  return `${run.id.slice(0, 8)}…`
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

export function isResumableStatus(status: string): boolean {
  return ['pending', 'running'].includes(status)
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
