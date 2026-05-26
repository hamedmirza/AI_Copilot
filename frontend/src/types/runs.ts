import { parseApiDateTime } from '@/lib/datetime'

export type RunStatus =
  | 'pending'
  | 'running'
  | 'awaiting_clarification'
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
  updated_at?: string
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
  terminal_success?: boolean | null
  terminal_status?: string | null
  retry_count?: number | null
  schema_failure_count?: number | null
  reviewer_failure_count?: number | null
  tester_failure_count?: number | null
  operator_feedback_present?: boolean | null
  approval_reached?: boolean | null
  promote_rolled_back?: boolean | null
  primary_failure_class?: string | null
  chat_session_id?: string | null
  deliverable_kind?: string | null
  expected_targets?: string[]
  expected_validation_family?: string | null
  readiness?: Record<string, unknown>
  mismatch_classes?: string[]
  approval_override?: boolean | null
  clarification_question?: string | null
  clarification_stage?: string | null
  recommended_assumption?: string | null
  created_at: string
  updated_at: string
}

export interface RunThreadEntry {
  id: number
  run_id: string
  session_id?: string | null
  role: string
  entry_type: string
  stage?: string | null
  severity?: string
  message: string
  payload?: Record<string, unknown>
  created_at: string
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

export interface ImprovementMetrics {
  sample_size?: number
  success_rate?: number
  avg_retry_count?: number
  schema_failure_rate?: number
  reviewer_failure_rate?: number
  tester_failure_rate?: number
  rollback_rate?: number
  successful_runs?: number
  harmful_runs?: number
}

export interface ImprovementRecord {
  id: string
  project_id?: string | null
  source_run_id?: string | null
  source_lesson_id?: number | null
  source_skill_id?: string | null
  title: string
  display_title?: string
  status: 'candidate' | 'trialing' | 'approved' | 'deprecated' | 'rejected' | string
  scope: 'project' | 'global' | string
  kind: string
  hypothesis: string
  failure_class?: string | null
  failure_subclass?: string | null
  task_kind?: string | null
  comparable_task_signature: string
  cohort_key: string
  confidence: number
  content: {
    summary?: string
    guidance?: string
    stages?: string[]
    tags?: string[]
    machine_guidance?: Record<string, unknown>
  }
  baseline_metrics?: ImprovementMetrics
  trial_metrics?: ImprovementMetrics
  decision_metadata?: Record<string, unknown>
  exposure_count?: number
  created_at: string
  updated_at: string
  trial_started_at?: string | null
  approved_at?: string | null
  deprecated_at?: string | null
  rejected_at?: string | null
}

export interface ImprovementExposureRecord {
  id: number
  improvement_id: string
  run_id: string
  stage: string
  status_at_application: string
  scope: string
  cohort_key: string
  task_signature: string
  task_kind?: string | null
  exposure_kind: string
  applied_context: Record<string, unknown>
  created_at: string
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
  outcome_class?: string
  why_blocked?: string
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
  awaiting_clarification: 'bg-[var(--warning)]/20 text-[var(--warning)]',
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
  return ['blocked', 'changes_requested', 'failed'].includes(status)
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

const TERMINAL_RUN_STATUSES = new Set([
  'completed',
  'failed',
  'blocked',
  'changes_requested',
  'cancelled',
])

function formatDurationMs(ms: number): string {
  if (ms < 0) return ''
  const minute = 60 * 1000
  const hour = 60 * minute
  if (ms < minute) return `${Math.max(1, Math.round(ms / 1000))}s`
  if (ms < hour) return `${Math.round(ms / minute)}m`
  return `${Math.round(ms / hour)}h`
}

/** Elapsed wall time for a run (terminal: created→updated; active: created→now). */
export function formatRunElapsed(
  createdIso: string,
  updatedIso: string | null | undefined,
  status: string,
): string {
  const created = parseApiDateTime(createdIso)
  if (!created) return ''
  const terminal = TERMINAL_RUN_STATUSES.has(status)
  const end = terminal && updatedIso ? parseApiDateTime(updatedIso) : new Date()
  if (!end) return ''
  const label = formatDurationMs(end.getTime() - created.getTime())
  return terminal ? label : `Active · ${label}`
}
