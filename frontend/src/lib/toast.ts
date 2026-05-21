import { toast } from 'sonner'

export { toast }

export function showError(error: unknown) {
  const message = error instanceof Error ? error.message : String(error)
  toast.error(message)
}

export function showSuccess(message: string) {
  toast.success(message)
}
