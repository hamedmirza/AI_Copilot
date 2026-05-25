import { describe, expect, it } from 'vitest'
import { formatExitMessage, getExitCodeHelp, parseExitCodeFromMessage } from './exitCodeHelp'
import { formatRunEventLine, patchRunsFromEvent } from './runEvents'

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
