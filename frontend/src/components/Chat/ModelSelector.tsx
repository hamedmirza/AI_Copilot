import { useMemo } from 'react'
import { formatModelOptionLabel } from '@/lib/lmstudioModels'
import type { ChatMode, ChatModelSelectionMode, LMStudioModelCatalogEntry } from '@/store'

interface ModelSelectorProps {
  mode: ChatMode
  selectionMode: ChatModelSelectionMode
  model: string
  models: string[]
  catalog?: LMStudioModelCatalogEntry[]
  resourcesPressure?: string | null
  disabled?: boolean
  onSelectionModeChange: (mode: ChatModelSelectionMode) => void
  onModelChange: (model: string) => void
}

export function ModelSelector({
  mode,
  selectionMode,
  model,
  models,
  catalog = [],
  resourcesPressure = null,
  disabled,
  onSelectionModeChange,
  onModelChange,
}: ModelSelectorProps) {
  const options = useMemo(() => {
    return Array.from(new Set([model, ...models].filter(Boolean)))
  }, [model, models])

  return (
    <div className="flex items-center gap-2 flex-wrap text-xs text-[var(--text-secondary)]">
      <span>Model</span>
      <select
        className="bg-[var(--bg-tertiary)] border border-[var(--border)] rounded px-2 py-1 text-sm text-[var(--text-primary)]"
        value={selectionMode}
        onChange={(event) => onSelectionModeChange(event.target.value as ChatModelSelectionMode)}
        disabled={disabled}
      >
        <option value="auto">Auto</option>
        <option value="manual">Manual</option>
      </select>
      {selectionMode === 'manual' ? (
        <select
          className="min-w-[220px] bg-[var(--bg-tertiary)] border border-[var(--border)] rounded px-2 py-1 text-sm text-[var(--text-primary)]"
          value={model}
          onChange={(event) => onModelChange(event.target.value)}
          disabled={disabled || options.length === 0}
        >
          <option value="" disabled>
            {options.length === 0 ? 'No models available' : 'Select a model'}
          </option>
          {options.map((option) => (
            <option key={option} value={option}>
              {formatModelOptionLabel(option, catalog)}
            </option>
          ))}
        </select>
      ) : (
        <span className="rounded border border-[var(--border)] px-2 py-1 text-[11px] uppercase tracking-wide">
          Auto for {mode}
          {resourcesPressure && resourcesPressure !== 'ok' ? ` • mem ${resourcesPressure}` : ''}
        </span>
      )}
    </div>
  )
}
