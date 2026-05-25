import type { RunEvent } from '@/types/runs'
import { formatExitMessage } from '@/lib/exitCodeHelp'

export function normalizeRunEvent(raw: Record<string, unknown>): RunEvent {
  return {
    ...raw,
    id: raw.id !== undefined ? Number(raw.id) : undefined,
    type: String(raw.type || raw.event_type || ''),
    event_type: raw.event_type ? String(raw.event_type) : undefined,
    stage: raw.stage != null ? String(raw.stage) : null,
    severity: raw.severity ? String(raw.severity) : undefined,
    message: raw.message ? String(raw.message) : '',
    run_id: raw.run_id ? String(raw.run_id) : undefined,
    created_at: raw.created_at ? String(raw.created_at) : undefined,
  }
}

export function normalizeRunEvents(rows: Array<Record<string, unknown>>): RunEvent[] {
  return rows.map((row) => normalizeRunEvent(row))
}

export function stageStatusFromEvents(events: RunEvent[], stage: string): 'pending' | 'running' | 'done' | 'failed' {
  const failed = events.some((e) => e.type === `${stage}_failed`)
  const complete = events.some((e) => e.type === `${stage}_complete`)
  const started = events.some((e) => e.type === `${stage}_started`)
  if (failed) return 'failed'
  if (complete) return 'done'
  if (started) return 'running'
  return 'pending'
}

export function runStatusFromEvents(events: RunEvent[], fallback = 'pending'): string {
  if (events.length === 0) return fallback
  const types = new Set(events.map((e) => e.type))
  if (types.has('run_completed')) return 'completed'
  if (types.has('run_clarification_requested')) return 'awaiting_clarification'
  if (types.has('awaiting_approval')) return 'awaiting_approval'
  if (types.has('run_changes_requested')) return 'changes_requested'
  if (types.has('run_blocked')) return 'blocked'
  if (types.has('run_failed')) return 'failed'
  if (events.some((e) => String(e.type || '').endsWith('_started'))) return 'running'
  return fallback
}

const ROUTINE_EVENT_TYPES = new Set([
  'validation_started',
  'reviewer_attempt_started',
])

const SIGNIFICANT_EVENT_TYPES = new Set([
  'run_clarification_requested',
  'awaiting_approval',
  'run_completed',
  'run_failed',
  'run_blocked',
  'run_changes_requested',
  'code_patch_applied',
  'validation_rejected',
  'validation_passed',
  'ui_designer_skipped',
  'provider_resolved',
  'visual_evidence_failed',
  'visual_evidence_passed',
  'browser_client_required',
  'browser_visual_check_started',
  'browser_visual_check_passed',
  'browser_visual_check_failed',
  'project_dev_server_down',
])

export function isSignificantRunEvent(event: RunEvent): boolean {
  const type = String(event.type || '')
  if (SIGNIFICANT_EVENT_TYPES.has(type)) return true
  if (type.endsWith('_failed')) return true
  if (event.severity === 'error' || event.severity === 'warn' || event.severity === 'warning') return true
  if (ROUTINE_EVENT_TYPES.has(type)) return false
  if (type.endsWith('_started') || type.endsWith('_complete')) return false
  return false
}

export function filterSignificantRunEvents(events: RunEvent[]): RunEvent[] {
  return events.filter(isSignificantRunEvent)
}

export function patchRunsFromEvent<T extends { id: string; status?: string; current_stage?: string | null }>(
  runs: T[],
  event: Pick<RunEvent, 'run_id' | 'type' | 'stage'>,
): T[] | null {
  const runId = event.run_id
  if (!runId) return null
  const index = runs.findIndex((run) => run.id === runId)
  if (index < 0) return null

  const type = String(event.type || '')
  if (type.endsWith('_started')) {
    const stage = event.stage ?? type.replace(/_started$/, '')
    return runs.map((run, i) =>
      i === index ? { ...run, status: 'running', current_stage: stage || run.current_stage } : run,
    )
  }
  if (type === 'run_completed') {
    return runs.map((run, i) => (i === index ? { ...run, status: 'completed' } : run))
  }
  if (type === 'run_failed') {
    return runs.map((run, i) => (i === index ? { ...run, status: 'failed' } : run))
  }
  return null
}

export function formatRunEventLine(event: RunEvent): string {
  const type = String(event.type || 'event')
  const message = String(event.message || '').trim()
  if (message) return formatExitMessage(message)
  return type.replaceAll('_', ' ')
}

export function runEventSeverityClass(event: RunEvent): string {
  if (event.severity === 'error') return 'text-[var(--error)]'
  if (event.severity === 'warn' || event.severity === 'warning') return 'text-[var(--warning)]'
  return 'text-[var(--text-secondary)]'
}
