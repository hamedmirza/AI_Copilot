import { useCallback, useEffect, useState } from 'react'
import { ExternalLink, RefreshCw } from 'lucide-react'
import { useProjectStore, useUIStore } from '@/store'
import { Button } from '@/components/ui/primitives'

function normalizeUrl(raw: string): string | null {
  const trimmed = raw.trim()
  if (!trimmed) return null
  try {
    const url = new URL(trimmed.includes('://') ? trimmed : `http://${trimmed}`)
    if (url.protocol !== 'http:' && url.protocol !== 'https:') return null
    return url.toString()
  } catch {
    return null
  }
}

export function BrowserPanel() {
  const projectId = useProjectStore((s) => s.currentProjectId)
  const browserUrlByProject = useUIStore((s) => s.browserUrlByProject)
  const setBrowserUrlForProject = useUIStore((s) => s.setBrowserUrlForProject)

  const storedUrl = projectId ? browserUrlByProject[projectId] ?? '' : ''
  const [inputUrl, setInputUrl] = useState(storedUrl)
  const [frameUrl, setFrameUrl] = useState(storedUrl)
  const [loadError, setLoadError] = useState(false)
  const [refreshKey, setRefreshKey] = useState(0)

  useEffect(() => {
    setInputUrl(storedUrl)
    setFrameUrl(storedUrl)
    setLoadError(false)
  }, [projectId, storedUrl])

  const navigate = useCallback(() => {
    const normalized = normalizeUrl(inputUrl)
    if (!normalized) {
      setLoadError(true)
      return
    }
    setLoadError(false)
    setFrameUrl(normalized)
    setInputUrl(normalized)
    if (projectId) setBrowserUrlForProject(projectId, normalized)
  }, [inputUrl, projectId, setBrowserUrlForProject])

  const openExternal = () => {
    const normalized = normalizeUrl(frameUrl || inputUrl)
    if (normalized) window.open(normalized, '_blank', 'noopener,noreferrer')
  }

  return (
    <div className="h-full flex flex-col bg-[var(--bg-primary)]">
      <div className="flex items-center gap-2 px-2 py-1.5 border-b border-[var(--border)] shrink-0">
        <input
          type="text"
          className="flex-1 min-w-0 px-2 py-1 text-sm bg-[var(--bg-secondary)] border border-[var(--border)] rounded outline-none focus:border-[var(--accent)]"
          placeholder="http://localhost:5177"
          value={inputUrl}
          onChange={(e) => setInputUrl(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && navigate()}
        />
        <Button variant="secondary" className="text-xs px-2 py-1" onClick={navigate}>
          Go
        </Button>
        <button
          type="button"
          title="Refresh"
          className="p-1.5 text-[var(--text-secondary)] hover:text-white rounded"
          onClick={() => setRefreshKey((k) => k + 1)}
        >
          <RefreshCw size={16} />
        </button>
        <button
          type="button"
          title="Open in new tab"
          className="p-1.5 text-[var(--text-secondary)] hover:text-white rounded"
          onClick={openExternal}
        >
          <ExternalLink size={16} />
        </button>
      </div>

      {loadError && (
        <p className="px-3 py-2 text-xs text-red-400 shrink-0">
          Enter a valid http or https URL.
        </p>
      )}

      {!frameUrl ? (
        <div className="flex-1 flex items-center justify-center text-sm text-[var(--text-secondary)]">
          Enter a URL and press Go to preview your app.
        </div>
      ) : (
        <div className="flex-1 relative overflow-hidden">
          <iframe
            key={`${frameUrl}-${refreshKey}`}
            src={frameUrl}
            title="Browser preview"
            className="absolute inset-0 w-full h-full border-0"
            sandbox="allow-scripts allow-same-origin allow-forms allow-popups"
            onError={() => setLoadError(true)}
          />
          {loadError && (
            <div className="absolute bottom-0 left-0 right-0 px-3 py-2 text-xs bg-[var(--bg-secondary)] border-t border-[var(--border)] text-[var(--text-secondary)]">
              Preview may be blocked (X-Frame-Options).{' '}
              <button type="button" className="text-[var(--accent)] underline" onClick={openExternal}>
                Open in new tab
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
