import { useCallback, useState } from 'react'
import { api } from '@/api/client'
import { normalizeThreadEntry } from '@/components/AgentPanel/runThread'
import { normalizeRunEvents } from '@/lib/runEvents'
import { showError } from '@/lib/toast'
import type { RunArtifact, RunDetail, RunEvent, RunThreadEntry } from '@/types/runs'
import { useRunStore } from '@/store'

export function useRunDetail() {
  const { setCurrentRun, setRunStatus, setEvents, setRunEvents, clearRunEvents } = useRunStore()
  const [detail, setDetail] = useState<RunDetail | null>(null)
  const [events, setLocalEvents] = useState<RunEvent[]>([])
  const [artifacts, setArtifacts] = useState<RunArtifact[]>([])
  const [thread, setThread] = useState<RunThreadEntry[]>([])
  const [threadLoading, setThreadLoading] = useState(false)
  const [loading, setLoading] = useState(false)

  const refreshThread = useCallback(async (runId: string) => {
    setThreadLoading(true)
    try {
      const rows = await api.runs.thread(runId) as Array<Record<string, unknown>>
      setThread(rows.map(normalizeThreadEntry))
      return rows.map(normalizeThreadEntry)
    } catch (e) {
      showError(e)
      return null
    } finally {
      setThreadLoading(false)
    }
  }, [])

  const hydrateRun = useCallback(async (runId: string, syncPanel = true) => {
    setLoading(true)
    clearRunEvents(runId)
    try {
      const [runRaw, eventRows, artifactRows, threadRows] = await Promise.all([
        api.runs.get(runId) as Promise<RunDetail>,
        api.runs.events(runId) as Promise<Array<Record<string, unknown>>>,
        api.runs.artifacts(runId) as Promise<RunArtifact[]>,
        api.runs.thread(runId) as Promise<Array<Record<string, unknown>>>,
      ])
      const normalized = normalizeRunEvents(eventRows)
      const normalizedThread = threadRows.map(normalizeThreadEntry)
      setDetail(runRaw)
      setLocalEvents(normalized)
      setRunEvents(runId, normalized as RunEvent[])
      setArtifacts(artifactRows)
      setThread(normalizedThread)
      if (syncPanel) {
        setCurrentRun(runId)
        setRunStatus(runRaw.status, runRaw.current_stage || '')
        setEvents(normalized as unknown as Array<Record<string, unknown>>)
      }
      return { run: runRaw, events: normalized, artifacts: artifactRows, thread: normalizedThread }
    } catch (e) {
      showError(e)
      return null
    } finally {
      setLoading(false)
    }
  }, [clearRunEvents, setCurrentRun, setEvents, setRunEvents, setRunStatus])

  return {
    detail,
    events,
    artifacts,
    thread,
    threadLoading,
    loading,
    hydrateRun,
    refreshThread,
    setDetail,
    setEvents: setLocalEvents,
    setArtifacts,
    setThread,
  }
}
