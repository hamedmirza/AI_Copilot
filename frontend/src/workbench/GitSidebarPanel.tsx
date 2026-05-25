import { lazy, Suspense } from 'react'
import { useUIStore } from '@/store'

const GitPanel = lazy(async () => ({ default: (await import('@/components/GitPanel/GitPanel')).GitPanel }))

export function GitSidebarPanel() {
  const activePanel = useUIStore((s) => s.activePanel)
  const bottomTab = useUIStore((s) => s.bottomTab)
  const bottomPanelCollapsed = useUIStore((s) => s.bottomPanelCollapsed)
  const pollWhenVisible =
    activePanel === 'git' || (bottomTab === 'git' && !bottomPanelCollapsed)
  return (
    <Suspense fallback={<div className="p-3 text-sm text-[var(--text-secondary)]">Loading…</div>}>
      <GitPanel pollWhenVisible={pollWhenVisible} />
    </Suspense>
  )
}
