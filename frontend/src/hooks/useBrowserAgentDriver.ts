import { useCallback, useEffect, useRef } from 'react'
import { wsUrl } from '@/api/client'
import { AGENT_MSG, type AgentAction, type BrowserWsCommand } from '@/lib/browserAgentMessages'
import { executeBrowserAgentCommand } from '@/lib/browserAgentRegistry'
import { PICKER_MSG } from '@/lib/browserPickerMessages'
import { useUIStore } from '@/store'

const BRIDGE_HANDSHAKE_MS = 4000

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => {
    window.setTimeout(resolve, ms)
  })
}

async function waitForBridgeReadyState(): Promise<boolean> {
  const deadline = Date.now() + BRIDGE_HANDSHAKE_MS
  while (Date.now() < deadline) {
    if (useUIStore.getState().browserBridgeReady) return true
    await sleep(150)
  }
  return useUIStore.getState().browserBridgeReady
}

export function useBrowserAgentDriver(projectId: string | null) {
  const wsRef = useRef<WebSocket | null>(null)
  const backoffRef = useRef(1000)
  const timerRef = useRef<number | null>(null)
  const intentionalCloseRef = useRef(false)

  const sendResult = useCallback((payload: {
    request_id: string
    ok: boolean
    result?: Record<string, unknown>
    error?: string
  }) => {
    const ws = wsRef.current
    if (!ws || ws.readyState !== WebSocket.OPEN) return
    ws.send(JSON.stringify({ type: 'browser_result', ...payload }))
  }, [])

  const handleNavigate = useCallback(async (args: Record<string, unknown>, requestId: string) => {
    const url = String(args.url || '').trim()
    if (!url || !projectId) {
      sendResult({ request_id: requestId, ok: false, error: 'invalid url' })
      return
    }
    useUIStore.getState().setBrowserAgentMode(true, undefined)
    useUIStore.getState().setActiveCenterView('browser')
    useUIStore.getState().setBrowserUrlForProject(projectId, url)
    useUIStore.getState().setBrowserBridgeReady(false)
    await sleep(600)
    const ready = await waitForBridgeReadyState()
    sendResult({
      request_id: requestId,
      ok: ready,
      result: { url, navigated: ready },
      error: ready ? undefined : 'bridge not ready after navigate',
    })
  }, [projectId, sendResult])

  const handleCommand = useCallback(async (command: BrowserWsCommand) => {
    const requestId = command.request_id
    const action = String(command.action)
    const args = command.args || {}
    if (command.run_id) {
      useUIStore.getState().setBrowserAgentMode(true, command.run_id)
    } else {
      useUIStore.getState().setBrowserAgentMode(true, undefined)
    }
    useUIStore.getState().setActiveCenterView('browser')

    if (action === 'navigate') {
      await handleNavigate(args, requestId)
      return
    }

    const result = await executeBrowserAgentCommand(action as AgentAction, args, requestId)
    sendResult({
      request_id: requestId,
      ok: result.ok,
      result: result.result,
      error: result.error,
    })
  }, [handleNavigate, sendResult])

  const connect = useCallback(() => {
    if (!projectId || intentionalCloseRef.current) return
    const path = `/api/ws/browser?project_id=${encodeURIComponent(projectId)}`
    const ws = new WebSocket(wsUrl(path))
    wsRef.current = ws

    ws.onopen = () => {
      backoffRef.current = 1000
      ws.send(JSON.stringify({ type: 'browser_ready', project_id: projectId }))
    }

    ws.onmessage = (ev) => {
      try {
        const data = JSON.parse(String(ev.data)) as BrowserWsCommand & { type?: string }
        if (data.type === 'browser_command') {
          void handleCommand(data)
        }
      } catch {
        /* ignore */
      }
    }

    ws.onclose = () => {
      if (wsRef.current === ws) wsRef.current = null
      if (intentionalCloseRef.current) return
      const delay = Math.min(backoffRef.current, 30000)
      backoffRef.current = Math.min(backoffRef.current * 2, 30000)
      timerRef.current = window.setTimeout(() => connect(), delay)
    }

    ws.onerror = () => ws.close()
  }, [handleCommand, projectId])

  useEffect(() => {
    intentionalCloseRef.current = false
    connect()
    return () => {
      intentionalCloseRef.current = true
      if (timerRef.current) clearTimeout(timerRef.current)
      const ws = wsRef.current
      wsRef.current = null
      if (ws && ws.readyState === WebSocket.OPEN) ws.close()
    }
  }, [connect])

  const stopAgentControl = useCallback(() => {
    useUIStore.getState().setBrowserAgentMode(false, null)
  }, [])

  return { stopAgentControl }
}

export { AGENT_MSG, PICKER_MSG }
