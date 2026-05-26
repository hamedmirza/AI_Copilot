/** Fan-out for the single app-level `/api/ws/events` socket (see App.tsx). */
export type GlobalRunEventListener = (event: Record<string, unknown>) => void

const listeners = new Set<GlobalRunEventListener>()

export function subscribeGlobalRunEvents(listener: GlobalRunEventListener): () => void {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

export function dispatchGlobalRunEvent(event: Record<string, unknown>): void {
  for (const listener of listeners) {
    listener(event)
  }
}
