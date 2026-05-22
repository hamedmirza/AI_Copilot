import { useCallback, useState } from 'react'
import { api } from '@/api/client'
import { normalizeRunEvents } from '@/lib/runEvents'
import { showError } from '@/lib/toast'
import type { RunArtifact, RunDetail, RunEvent } from '@/types/runs'
import { useRunStore } from '@/store'

export function useRunDetail() {
  const { setCurrentRun, setRunStatus, setEvents } = useRunStore()
  const [detail, setDetail] = useState<RunDetail | null>(null)
  const [events, setLocalEvents] = useState<RunEvent[]>([])
  const [artifacts, setArtifacts] = useState<RunArtifact[]>([])
  const [loading, setLoading] = useState(false)

  const hydrateRun = useCallback(async (runId: string, syncPanel = true) => {
    setLoading(true)
    try {
      const [runRaw, eventRows, artifactRows] = await Promise.all([
        api.runs.get(runId) as Promise<RunDetail>,
        api.runs.events(runId) as Promise<Array<Record<string, unknown>>>,
        api.runs.artifacts(runId) as Promise<RunArtifact[]>,
      ])
      const normalized = normalizeRunEvents(eventRows)
      setDetail(runRaw)
      setLocalEvents(normalized)
      setArtifacts(artifactRows)
      if (syncPanel) {
        setCurrentRun(runId)
        setRunStatus(runRaw.status, runRaw.current_stage || '')
        setEvents(normalized as unknown as import('@/store').RunEvent[])
      }
      return { run: runRaw, events: normalized, artifacts: artifactRows }
    } catch (e) {
      showError(e)
      return null
    } finally {
      setLoading(false)
    }
  }, [setCurrentRun, setEvents, setRunStatus])

  return {
    detail,
    events,
    artifacts,
    loading,
    hydrateRun,
    setDetail,
    setEvents: setLocalEvents,
    setArtifacts,
  }
}
