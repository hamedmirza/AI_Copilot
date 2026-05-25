export const BROWSER_REFRESH_EVENT = 'copilot-browser-refresh'

export function dispatchBrowserRefresh(): void {
  window.dispatchEvent(new CustomEvent(BROWSER_REFRESH_EVENT))
}

export function listenForBrowserRefresh(onRefresh: () => void): () => void {
  window.addEventListener(BROWSER_REFRESH_EVENT, onRefresh)
  return () => window.removeEventListener(BROWSER_REFRESH_EVENT, onRefresh)
}
