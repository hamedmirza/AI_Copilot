import { describe, expect, it } from 'vitest'
import {
  activeProviderFromSettings,
  createSaveSequencer,
  inferProviderStatus,
  modelOptionsForSelect,
  statusFromModelsResponse,
} from './providerModels'

describe('providerModels', () => {
  it('activeProviderFromSettings respects ollama_enabled', () => {
    expect(activeProviderFromSettings({ ollama_enabled: true })).toBe('ollama')
    expect(activeProviderFromSettings({ ollama_enabled: false })).toBe('lmstudio')
  })

  it('inferProviderStatus maps model counts', () => {
    expect(inferProviderStatus(undefined)).toBe('unknown')
    expect(inferProviderStatus(0)).toBe('degraded')
    expect(inferProviderStatus(3)).toBe('healthy')
  })

  it('statusFromModelsResponse uses models length', () => {
    expect(statusFromModelsResponse({ models: ['a'] })).toBe('healthy')
    expect(statusFromModelsResponse({ models: [] })).toBe('degraded')
  })

  it('modelOptionsForSelect prepends missing selection', () => {
    expect(modelOptionsForSelect(['a', 'b'], 'saved')).toEqual(['saved', 'a', 'b'])
    expect(modelOptionsForSelect(['a', 'b'], 'a')).toEqual(['a', 'b'])
  })

  it('createSaveSequencer ignores stale tickets', () => {
    const seq = createSaveSequencer()
    const first = seq.nextTicket()
    const second = seq.nextTicket()
    expect(seq.isLatest(first)).toBe(false)
    expect(seq.isLatest(second)).toBe(true)
  })
})
