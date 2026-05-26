import { describe, expect, it } from 'vitest'
import { formatExitMessage, getExitCodeHelp, parseExitCodeFromMessage } from './exitCodeHelp'
import {
  appendRunEventDeduped,
  dedupeRunEvents,
  formatRunActivityLine,
  formatRunEventLine,
  MAX_RUN_EVENTS_PER_RUN,
  patchRunsFromEvent,
  runEventDedupeKey,
  shouldPollRunStatus,
  shouldRefreshRunThread,
  trimRunEvents,
} from './runEvents'
import type { RunEvent } from '@/types/runs'

describe('getExitCodeHelp', () => {
  it('maps common shell exit codes', () => {
    expect(getExitCodeHelp(127).label).toBe('Command not found')
    expect(getExitCodeHelp(127).hint).toMatch(/venv/)
    expect(getExitCodeHelp(126).label).toBe('Command not executable')
  })

  it('maps signal-style exits', () => {
    expect(getExitCodeHelp(130).label).toBe('Interrupted')
    expect(getExitCodeHelp(137).label).toBe('Process killed')
    expect(getExitCodeHelp(129).label).toBe('Stopped by SIGHUP')
  })
})

describe('formatExitMessage', () => {
  it('formats exit=N as label, code, and hint', () => {
    expect(formatExitMessage('exit=127')).toBe(
      'Command not found (127) — Use project venv paths (e.g. backend/.venv/bin/pytest), not bare pytest.',
    )
    expect(formatExitMessage('exit=1')).toContain('Tests or script failed (1)')
  })

  it('leaves unrelated messages unchanged', () => {
    expect(formatExitMessage('validation failed')).toBe('validation failed')
    expect(parseExitCodeFromMessage('exit=127 extra')).toBeNull()
  })
})

describe('shouldPollRunStatus', () => {
  it('polls only in-progress statuses', () => {
    expect(shouldPollRunStatus('running')).toBe(true)
    expect(shouldPollRunStatus('awaiting_approval')).toBe(true)
    expect(shouldPollRunStatus('changes_requested')).toBe(false)
    expect(shouldPollRunStatus('blocked')).toBe(false)
    expect(shouldPollRunStatus('completed')).toBe(false)
  })
})

describe('trimRunEvents', () => {
  it('keeps the newest events when over cap', () => {
    const events = Array.from({ length: MAX_RUN_EVENTS_PER_RUN + 10 }, (_, i) => ({
      type: 'stage_progress',
      message: String(i),
      created_at: `2020-01-01T00:00:${String(i).padStart(2, '0')}Z`,
    }))
    const trimmed = trimRunEvents(events)
    expect(trimmed).toHaveLength(MAX_RUN_EVENTS_PER_RUN)
    expect(trimmed[0]?.message).toBe('10')
  })
})

describe('patchRunsFromEvent', () => {
  const runs = [{ id: 'run-1', status: 'pending', current_stage: null }]

  it('updates stage on stage_started events', () => {
    const next = patchRunsFromEvent(runs, { run_id: 'run-1', type: 'coder_started', stage: 'coder' })
    expect(next?.[0]).toMatchObject({ status: 'running', current_stage: 'coder' })
  })

  it('updates status on terminal events', () => {
    const next = patchRunsFromEvent(runs, { run_id: 'run-1', type: 'run_completed' })
    expect(next?.[0]).toMatchObject({ status: 'completed' })
  })

  it('returns null for unrelated events', () => {
    expect(patchRunsFromEvent(runs, { run_id: 'run-1', type: 'code_patch_applied' })).toBeNull()
  })
})

describe('shouldRefreshRunThread', () => {
  it('includes schema and guard rejection events', () => {
    expect(shouldRefreshRunThread('coder_schema_rejected')).toBe(true)
    expect(shouldRefreshRunThread('architect_schema_rejected')).toBe(true)
    expect(shouldRefreshRunThread('coder_guard_rejected')).toBe(true)
    expect(shouldRefreshRunThread('coder_started')).toBe(false)
  })
})

describe('run event dedupe', () => {
  it('dedupes by id or type/message/created_at', () => {
    const events: RunEvent[] = [
      { id: 1, type: 'coder_started', message: 'x', created_at: '2020-01-01T00:00:00Z' },
      { id: 1, type: 'coder_started', message: 'x', created_at: '2020-01-01T00:00:00Z' },
      { type: 'pipeline_tool_start', message: 'list', created_at: '2020-01-01T00:00:01Z' },
    ]
    expect(dedupeRunEvents(events)).toHaveLength(2)
    expect(runEventDedupeKey(events[0])).toBe('id:1')
  })

  it('appendRunEventDeduped skips duplicates', () => {
    const base: RunEvent[] = [{ type: 'coder_started', message: 'go', created_at: 't1' }]
    const next = appendRunEventDeduped(base, { type: 'coder_started', message: 'go', created_at: 't1' })
    expect(next).toHaveLength(1)
    const added = appendRunEventDeduped(next, { type: 'pipeline_tool_end', message: 'done', created_at: 't2' })
    expect(added).toHaveLength(2)
  })
})

describe('formatRunActivityLine', () => {
  it('formats pipeline tool events', () => {
    expect(
      formatRunActivityLine({
        type: 'pipeline_tool_start',
        payload: { tool: 'list_files', path: 'backend/app' },
      }),
    ).toContain('list_files')
  })

  it('formats stage progress heartbeats', () => {
    expect(
      formatRunActivityLine({
        type: 'stage_progress',
        stage: 'coder',
        message: 'Still working on coder… (45s)',
      }),
    ).toContain('Still working')
  })
})

describe('patchRunsFromEvent pipeline tools', () => {
  const runs = [{ id: 'run-1', status: 'running', current_stage: 'planner' }]

  it('keeps stage current on pipeline_tool events', () => {
    const next = patchRunsFromEvent(runs, {
      run_id: 'run-1',
      type: 'pipeline_tool_start',
      stage: 'coder',
    })
    expect(next?.[0]).toMatchObject({ current_stage: 'coder', status: 'running' })
  })
})

describe('formatRunEventLine', () => {
  it('enriches exit messages on run events', () => {
    expect(
      formatRunEventLine({
        type: 'validation_rejected',
        message: 'exit=127',
        severity: 'error',
      }),
    ).toContain('Command not found (127)')
  })
})
