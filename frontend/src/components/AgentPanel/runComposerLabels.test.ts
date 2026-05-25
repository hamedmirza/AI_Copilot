import { describe, expect, it } from 'vitest'
import { runComposerLabels } from './runComposerLabels'

describe('runComposerLabels', () => {
  it('maps awaiting_clarification to Send answer', () => {
    const labels = runComposerLabels('awaiting_clarification')
    expect(labels.primaryLabel).toBe('Send answer')
    expect(labels.primaryDisabled).toBe(false)
  })

  it('disables composer while running', () => {
    const labels = runComposerLabels('running')
    expect(labels.primaryDisabled).toBe(true)
    expect(labels.showPrimary).toBe(false)
    expect(labels.placeholder).toContain('in progress')
  })

  it('maps awaiting_approval to Approve run', () => {
    const labels = runComposerLabels('awaiting_approval')
    expect(labels.primaryLabel).toBe('Approve run')
  })

  it('maps failed to Retry pipeline', () => {
    const labels = runComposerLabels('failed')
    expect(labels.primaryLabel).toBe('Retry pipeline')
  })
})
