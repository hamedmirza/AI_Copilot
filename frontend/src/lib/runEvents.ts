import type { RunEvent } from '@/types/runs'
import { formatExitMessage } from '@/lib/exitCodeHelp'

export function normalizeRunEvent(raw: Record<string, unknown>): RunEvent {
  const payload =
    raw.payload && typeof raw.payload === 'object' && !Array.isArray(raw.payload)
      ? (raw.payload as Record<string, unknown>)
      : undefined
  const outcomeClass = raw.outcome_class ?? payload?.outcome_class
  const whyBlocked = raw.why_blocked ?? payload?.why_blocked
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
    payload,
    outcome_class: outcomeClass != null ? String(outcomeClass) : undefined,
    why_blocked: whyBlocked != null ? String(whyBlocked) : undefined,
  }
}

export function normalizeRunEvents(rows: Array<Record<string, unknown>>): RunEvent[] {
  return rows.map((row) => normalizeRunEvent(row))
}

export function stageStatusFromEvents(
  events: RunEvent[],
  stage: string,
): 'pending' | 'running' | 'done' | 'failed' | 'skipped' {
  const failed = events.some((e) => e.type === `${stage}_failed`)
  const complete = events.some((e) => e.type === `${stage}_complete`)
  const skipped = events.some((e) => e.type === `${stage}_skipped`)
  const started = events.some((e) => e.type === `${stage}_started`)
  if (failed) return 'failed'
  if (complete) return 'done'
  if (skipped) return 'skipped'
  if (started) return 'running'
  return 'pending'
}

export function applyRunEventToStatus(
  setRunStatus: (status: string, stage?: string | null) => void,
  ev: Record<string, unknown>,
) {
  const type = String(ev.type || '')
  if (type === 'run_clarification_requested') setRunStatus('awaiting_clarification', String(ev.stage || ''))
  else if (type === 'awaiting_approval') setRunStatus('awaiting_approval', String(ev.stage || ''))
  else if (type === 'run_blocked') setRunStatus('blocked', String(ev.stage || ''))
  else if (type === 'run_failed') setRunStatus('failed', String(ev.stage || ''))
  else if (type === 'run_completed') setRunStatus('completed', String(ev.stage || ''))
  else if (type === 'run_changes_requested') setRunStatus('changes_requested', String(ev.stage || ''))
  else if (type.endsWith('_started')) setRunStatus('running', type.replace('_started', ''))
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
  'architect_schema_rejected',
  'coder_schema_rejected',
  'coder_guard_rejected',
  'validation_rejected',
  'validation_passed',
  'validation_result',
  'ui_designer_skipped',
  'provider_resolved',
  'lessons_applied',
  'stage_progress',
  'pipeline_tool_start',
  'pipeline_tool_end',
  'visual_evidence_failed',
  'visual_evidence_passed',
  'browser_client_required',
  'browser_visual_check_started',
  'browser_visual_check_passed',
  'browser_visual_check_failed',
  'project_dev_server_down',
])

const ACTIVITY_VISIBLE_TYPES = new Set([
  ...SIGNIFICANT_EVENT_TYPES,
])

/** Run is still executing or waiting on user input — enable live UI timers. */
const IN_PROGRESS_RUN_STATUSES = new Set([
  'pending',
  'running',
  'awaiting_clarification',
  'awaiting_approval',
  'awaiting_design_review',
])

/** HTTP poll while status may still change (excludes terminal pipeline outcomes). */
const POLLABLE_RUN_STATUSES = IN_PROGRESS_RUN_STATUSES

export const MAX_RUN_EVENTS_PER_RUN = 500

export function isActiveRunStatus(status: string): boolean {
  return IN_PROGRESS_RUN_STATUSES.has(status)
}

export function shouldPollRunStatus(status: string): boolean {
  return POLLABLE_RUN_STATUSES.has(status)
}

export function trimRunEvents(events: RunEvent[]): RunEvent[] {
  if (events.length <= MAX_RUN_EVENTS_PER_RUN) return events
  return events.slice(-MAX_RUN_EVENTS_PER_RUN)
}

export function runEventDedupeKey(event: RunEvent): string {
  const id = event.id
  if (id != null && !Number.isNaN(Number(id))) return `id:${id}`
  const created = event.created_at || ''
  const type = String(event.type || event.event_type || '')
  const message = String(event.message || '')
  const stage = event.stage ?? ''
  return `${type}|${stage}|${message}|${created}`
}

export function dedupeRunEvents(events: RunEvent[]): RunEvent[] {
  const seen = new Set<string>()
  const out: RunEvent[] = []
  for (const event of events) {
    const key = runEventDedupeKey(event)
    if (seen.has(key)) continue
    seen.add(key)
    out.push(event)
  }
  return out
}

export function appendRunEventDeduped(existing: RunEvent[], raw: Record<string, unknown>): RunEvent[] {
  const next = normalizeRunEvent(raw)
  const key = runEventDedupeKey(next)
  if (existing.some((e) => runEventDedupeKey(e) === key)) return existing
  return trimRunEvents([...existing, next])
}

export function isActivityVisibleRunEvent(event: RunEvent): boolean {
  const type = String(event.type || '')
  if (ACTIVITY_VISIBLE_TYPES.has(type)) return true
  if (type.endsWith('_started') || type.endsWith('_complete')) return true
  if (type.startsWith('pipeline_tool_')) return true
  return false
}

export function formatRunActivityLine(event: RunEvent): string {
  const type = String(event.type || '')
  const payload = event.payload
  const tool = payload?.tool ? String(payload.tool) : ''
  const path = payload?.path ? String(payload.path) : payload?.file_path ? String(payload.file_path) : ''

  if (type === 'stage_progress') {
    const msg = String(event.message || '').trim()
    return msg || `Still working on ${event.stage || 'stage'}…`
  }
  if (type === 'provider_resolved') {
    return String(event.message || 'Provider resolved')
  }
  if (type === 'lessons_applied') {
    return 'Applied lessons from prior runs'
  }
  if (type === 'pipeline_tool_start') {
    if (tool && path) return `${tool}: ${path}`
    if (tool) return `${tool}…`
    return 'Running tool…'
  }
  if (type === 'pipeline_tool_end') {
    if (tool && path) return `Finished ${tool}: ${path}`
    if (tool) return `Finished ${tool}`
    return 'Tool finished'
  }
  if (type === 'code_patch_applied') {
    const files = payload?.applied_count ?? payload?.file_count
    if (files != null) return `Applied patch (${files} file${Number(files) === 1 ? '' : 's'})`
    return String(event.message || 'Patch applied')
  }
  if (type.endsWith('_started')) {
    const stage = event.stage || type.replace(/_started$/, '')
    return `${stage.replaceAll('_', ' ')}…`
  }
  if (type.endsWith('_complete')) {
    const stage = event.stage || type.replace(/_complete$/, '')
    return `${stage.replaceAll('_', ' ')} complete`
  }
  if (type === 'coder_schema_rejected' || type === 'architect_schema_rejected') {
    return 'Retrying — output did not match schema'
  }
  if (type === 'validation_result' || type === 'validation_passed' || type === 'validation_rejected') {
    return formatRunEventLine(event)
  }
  return formatRunEventLine(event)
}

export function latestActivityLineFromEvents(events: RunEvent[]): string | null {
  for (let i = events.length - 1; i >= 0; i -= 1) {
    const event = events[i]
    if (!isActivityVisibleRunEvent(event)) continue
    const line = formatRunActivityLine(event).trim()
    if (line) return line
  }
  return null
}

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

/** Pipeline retry / rejection events that update the run thread and activity log. */
export function shouldRefreshRunThread(eventType: string): boolean {
  const type = String(eventType || '')
  return (
    type.endsWith('_schema_rejected') ||
    type.endsWith('_guard_rejected') ||
    type === 'validation_rejected'
  )
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
  if (type === 'run_blocked' || type === 'run_changes_requested') {
    return runs.map((run, i) => (i === index ? { ...run, status: type.replace('run_', '') } : run))
  }
  if (type === 'stage_progress' && event.stage) {
    return runs.map((run, i) =>
      i === index ? { ...run, status: 'running', current_stage: event.stage || run.current_stage } : run,
    )
  }
  if (type.startsWith('pipeline_tool_') && event.stage) {
    return runs.map((run, i) =>
      i === index ? { ...run, status: 'running', current_stage: event.stage || run.current_stage } : run,
    )
  }
  return null
}

export function formatRunEventLine(event: RunEvent): string {
  const type = String(event.type || 'event')
  const message = String(event.message || '').trim()
  if (event.why_blocked && (type === 'run_blocked' || event.outcome_class === 'blocked')) {
    return formatExitMessage(String(event.why_blocked))
  }
  if (message) return formatExitMessage(message)
  return type.replaceAll('_', ' ')
}

export function runEventSeverityClass(event: RunEvent): string {
  if (event.severity === 'error') return 'text-[var(--error)]'
  if (event.severity === 'warn' || event.severity === 'warning') return 'text-[var(--warning)]'
  return 'text-[var(--text-secondary)]'
}
