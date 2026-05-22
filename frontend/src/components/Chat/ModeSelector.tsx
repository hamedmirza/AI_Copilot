import type { ChatMode } from '@/store'
import { CHAT_MODE_OPTIONS } from './types'

interface ModeSelectorProps {
  value: ChatMode
  onChange: (mode: ChatMode) => void
  disabled?: boolean
}

export function ModeSelector({ value, onChange, disabled }: ModeSelectorProps) {
  return (
    <label className="flex items-center gap-2 text-xs text-[var(--text-secondary)]">
      <span>Mode</span>
      <select
        className="bg-[var(--bg-tertiary)] border border-[var(--border)] rounded px-2 py-1 text-sm text-[var(--text-primary)]"
        value={value}
        onChange={(event) => onChange(event.target.value as ChatMode)}
        disabled={disabled}
      >
        {CHAT_MODE_OPTIONS.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </label>
  )
}
