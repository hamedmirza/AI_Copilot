interface ThinkingIndicatorProps {
  label?: string
  compact?: boolean
}

export function ThinkingIndicator({ label = 'Thinking', compact = false }: ThinkingIndicatorProps) {
  return (
    <div
      className={`flex items-center gap-2 text-[var(--text-secondary)] ${compact ? 'text-xs' : 'text-sm'}`}
      role="status"
      aria-live="polite"
      aria-label={label}
    >
      <span className="flex gap-1" aria-hidden="true">
        {[0, 1, 2].map((index) => (
          <span
            key={index}
            className={`rounded-full bg-[var(--accent)] animate-pulse ${compact ? 'w-1.5 h-1.5' : 'w-2 h-2'}`}
            style={{ animationDelay: `${index * 180}ms` }}
          />
        ))}
      </span>
      <span>{label}</span>
    </div>
  )
}
