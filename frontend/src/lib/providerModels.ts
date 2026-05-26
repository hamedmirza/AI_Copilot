import type { ModelsApiResponse } from '@/lib/lmstudioModels'

export type { ModelsApiResponse }

export type ProviderKind = 'lmstudio' | 'ollama'

export function activeProviderFromSettings(settings: Record<string, unknown>): ProviderKind {
  return settings.ollama_enabled ? 'ollama' : 'lmstudio'
}

export function inactiveProvider(provider: ProviderKind): ProviderKind {
  return provider === 'ollama' ? 'lmstudio' : 'ollama'
}

/** Infer connection status from a models list response (avoids extra health probes on open). */
export function inferProviderStatus(modelCount: number | undefined): 'healthy' | 'degraded' | 'unknown' {
  if (modelCount === undefined) return 'unknown'
  return modelCount > 0 ? 'healthy' : 'degraded'
}

export function statusFromModelsResponse(
  response: ModelsApiResponse | undefined,
): 'healthy' | 'degraded' | 'unknown' {
  return inferProviderStatus(response?.models?.length)
}

/** Ensure the saved model id appears in the dropdown even before the catalog finishes loading. */
export function modelOptionsForSelect(models: string[], selected: string): string[] {
  const trimmed = selected.trim()
  if (!trimmed) return models
  if (models.includes(trimmed)) return models
  return [trimmed, ...models]
}

export const MODELS_CACHE_MS = 90_000

export type ModelsCacheEntry = {
  response: ModelsApiResponse
  fetchedAt: number
}

export function isModelsCacheFresh(fetchedAt: number, maxAgeMs = MODELS_CACHE_MS): boolean {
  return Date.now() - fetchedAt < maxAgeMs
}

export function createSaveSequencer() {
  let latest = 0
  return {
    nextTicket: () => {
      latest += 1
      return latest
    },
    isLatest: (ticket: number) => ticket === latest,
  }
}
