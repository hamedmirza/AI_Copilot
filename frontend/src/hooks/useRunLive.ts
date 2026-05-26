import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api } from '@/api/client'
import { subscribeGlobalRunEvents } from '@/lib/globalRunEvents'
import {
  applyRunEventToStatus,
  isActiveRunStatus,
  latestActivityLineFromEvents,
  normalizeRunEvents,
  runStatusFromEvents,
  shouldPollRunStatus,
} from '@/lib/runEvents'
import { parseApiDateTime } from '@/lib/datetime'
import type { RunDetail, RunEvent } from '@/types/runs'
import { useRunStore } from '@/store'

const EMPTY_RUN_EVENTS: RunEvent[] = []
const RUN_POLL_INTERVAL_MS = 2000

export function useRunLive(runId: string | null, options?: { syncPanel?: boolean; enabled?: boolean }) {
  const enabled = options?.enabled !== false && Boolean(runId)
  const syncPanel = options?.syncPanel ?? false

  const appendRunEvent = useRunStore((s) => s.appendRunEvent)
  const setRunEvents = useRunStore((s) => s.setRunEvents)
  const clearRunEvents = useRunStore((s) => s.clearRunEvents)
  const setRunStatus = useRunStore((s) => s.setRunStatus)
  const setCurrentRun = useRunStore((s) => s.setCurrentRun)

  const events = useRunStore((s) => (
    runId ? (s.runEventsByRunId[runId] ?? EMPTY_RUN_EVENTS) : EMPTY_RUN_EVENTS
  ))

  const [detail, setDetail] = useState<RunDetail | null>(null)
  const [hydrating, setHydrating] = useState(false)
  const hydrateGen = useRef(0)

  const hydrate = useCallback(async (id: string) => {
    const gen = hydrateGen.current + 1
    hydrateGen.current = gen
    setHydrating(true)
    clearRunEvents(id)
    try {
      const [runRaw, eventRows] = await Promise.all([
        api.runs.get(id) as Promise<RunDetail>,
        api.runs.events(id) as Promise<Array<Record<string, unknown>>>,
      ])
      if (hydrateGen.current !== gen) return null
      const normalized = normalizeRunEvents(eventRows)
      setRunEvents(id, normalized)
      setDetail(runRaw)
      if (syncPanel) {
        setCurrentRun(id)
        setRunStatus(runRaw.status, runRaw.current_stage || '')
      }
      return { run: runRaw, events: normalized }
    } catch {
      return null
    } finally {
      if (hydrateGen.current === gen) setHydrating(false)
    }
  }, [clearRunEvents, setCurrentRun, setRunEvents, setRunStatus, syncPanel])

  useEffect(() => {
    if (!runId || !enabled) {
      setDetail(null)
      return
    }
    void hydrate(runId)
    return () => {
      hydrateGen.current += 1
    }
  }, [runId, enabled, hydrate])

  useEffect(() => {
    if (!runId || !enabled) return
    return subscribeGlobalRunEvents((ev) => {
      const eventRunId = String(ev.run_id || '')
      if (eventRunId && eventRunId !== runId) return
      appendRunEvent(runId, ev)
      if (syncPanel) applyRunEventToStatus(setRunStatus, ev)
      const type = String(ev.type || '')
      if (type.includes('complete') || type === 'run_completed' || type === 'run_failed') {
        void api.runs.get(runId).then((run) => {
          setDetail(run as RunDetail)
          if (syncPanel) {
            const r = run as RunDetail
            setRunStatus(r.status, r.current_stage || '')
          }
        }).catch(() => undefined)
      }
    })
  }, [appendRunEvent, enabled, runId, setRunStatus, syncPanel])

  const status = detail?.status || runStatusFromEvents(events, 'pending')
  const currentStage = detail?.current_stage ?? (
    [...events].reverse().find((e) => e.stage)?.stage ?? null
  )

  useEffect(() => {
    if (!runId || !enabled || !shouldPollRunStatus(status)) return
    const poll = window.setInterval(() => {
      void api.runs.events(runId)
        .then((rows) => {
          const normalized = normalizeRunEvents(rows as Array<Record<string, unknown>>)
          setRunEvents(runId, normalized)
        })
        .catch(() => undefined)
      void api.runs.get(runId)
        .then((run) => setDetail(run as RunDetail))
        .catch(() => undefined)
    }, RUN_POLL_INTERVAL_MS)
    return () => window.clearInterval(poll)
  }, [enabled, runId, setRunEvents, status])

  const elapsedMs = useMemo(() => {
    const start = detail?.created_at ? parseApiDateTime(detail.created_at) : null
    if (!start) return 0
    const endDate = detail?.updated_at && !isActiveRunStatus(status)
      ? parseApiDateTime(detail.updated_at)
      : null
    const endMs = endDate ? endDate.getTime() : Date.now()
    return Math.max(0, endMs - start.getTime())
  }, [detail?.created_at, detail?.updated_at, status])

  const latestActivityLine = useMemo(
    () => latestActivityLineFromEvents(events),
    [events],
  )

  return {
    events: events as RunEvent[],
    detail,
    status,
    currentStage,
    elapsedMs,
    latestActivityLine,
    hydrating,
    hydrate,
  }
}
