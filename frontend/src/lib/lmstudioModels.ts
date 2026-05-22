import type { LMStudioModelCatalogEntry, LMStudioResources } from '@/store'

export type ModelsApiResponse = {
  models: string[]
  catalog?: LMStudioModelCatalogEntry[]
  recommendations?: Record<string, string>
  resources?: LMStudioResources
}

export function applyModelsResponse(
  response: ModelsApiResponse,
  handlers: {
    setModels: (models: string[]) => void
    setModelCatalog: (catalog: LMStudioModelCatalogEntry[]) => void
    setModelRecommendations: (recommendations: Record<string, string>) => void
    setLmstudioResources: (resources: LMStudioResources | null) => void
  },
) {
  handlers.setModels(response.models)
  handlers.setModelCatalog(response.catalog ?? [])
  handlers.setModelRecommendations(response.recommendations ?? {})
  if (response.resources) {
    handlers.setLmstudioResources(response.resources)
  } else {
    handlers.setLmstudioResources(null)
  }
}

export function formatModelOptionLabel(
  modelId: string,
  catalog: LMStudioModelCatalogEntry[],
): string {
  const entry = catalog.find((item) => item.id === modelId)
  if (!entry) return modelId
  const tags: string[] = []
  if (entry.loaded) tags.push('loaded')
  if (entry.size_gb > 0) tags.push(`${entry.size_gb} GB`)
  if (entry.params) tags.push(entry.params)
  return tags.length > 0 ? `${modelId} (${tags.join(', ')})` : modelId
}

export function recommendedLabel(
  settingsKey: string,
  staticRecommended: string,
  recommendations: Record<string, string>,
): string {
  const dynamic = recommendations[settingsKey]
  if (dynamic && dynamic !== staticRecommended) {
    return `★ ${dynamic} (best available)`
  }
  if (dynamic) {
    return `★ ${dynamic}`
  }
  return `★ ${staticRecommended}`
}
