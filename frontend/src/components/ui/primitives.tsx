import { cn } from '@/lib/utils'

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  loading?: boolean
  variant?: 'primary' | 'secondary' | 'ghost' | 'danger'
}

export function Button({ loading, variant = 'primary', children, className, disabled, ...props }: ButtonProps) {
  const variants = {
    primary: 'bg-[var(--accent)] hover:bg-[var(--accent-hover)] text-white',
    secondary: 'bg-[var(--bg-tertiary)] hover:bg-[#3c3c3c] text-[var(--text-primary)]',
    ghost: 'bg-transparent hover:bg-[var(--bg-tertiary)] text-[var(--text-primary)]',
    danger: 'bg-[var(--error)] hover:opacity-90 text-white',
  }
  return (
    <button
      className={cn(
        'inline-flex items-center gap-2 px-3 py-1.5 rounded text-sm font-medium transition-colors',
        variants[variant],
        className
      )}
      disabled={disabled || loading}
      {...props}
    >
      {loading && <span className="spinner" />}
      {children}
    </button>
  )
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn('skeleton', className)} />
}

export function EmptyState({ title, description, action }: { title: string; description: string; action?: React.ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center h-full p-8 text-center text-[var(--text-secondary)]">
      <p className="text-base mb-1 text-[var(--text-primary)]">{title}</p>
      <p className="text-sm mb-4">{description}</p>
      {action}
    </div>
  )
}
