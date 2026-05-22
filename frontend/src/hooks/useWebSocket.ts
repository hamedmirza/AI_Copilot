import { useCallback, useEffect, useRef } from 'react'
import { wsUrl } from '@/api/client'
import { useAppStore } from '@/store'

export function useWebSocket(
  path: string,
  onMessage: (data: unknown) => void,
  enabled = true,
  trackStatus = false,
) {
  const wsRef = useRef<WebSocket | null>(null)
  const backoffRef = useRef(1000)
  const timerRef = useRef<number | null>(null)
  const onMessageRef = useRef(onMessage)
  const intentionalCloseRef = useRef(false)
  const setReconnecting = useAppStore((s) => s.setWsReconnecting)

  onMessageRef.current = onMessage

  const connect = useCallback(() => {
    if (!enabled || !path || intentionalCloseRef.current) return
    const ws = new WebSocket(wsUrl(path))
    wsRef.current = ws

    ws.onopen = () => {
      if (intentionalCloseRef.current) {
        ws.close()
        return
      }
      backoffRef.current = 1000
      if (trackStatus) setReconnecting(false)
    }

    ws.onmessage = (ev) => {
      try {
        onMessageRef.current(JSON.parse(ev.data))
      } catch {
        onMessageRef.current(ev.data)
      }
    }

    ws.onclose = () => {
      if (wsRef.current === ws) wsRef.current = null
      if (intentionalCloseRef.current) return
      if (trackStatus) setReconnecting(true)
      const delay = Math.min(backoffRef.current, 30000)
      backoffRef.current = Math.min(backoffRef.current * 2, 30000)
      timerRef.current = window.setTimeout(connect, delay)
    }

    ws.onerror = () => {
      if (!intentionalCloseRef.current) ws.close()
    }
  }, [path, enabled, trackStatus, setReconnecting])

  useEffect(() => {
    intentionalCloseRef.current = false
    connect()
    return () => {
      intentionalCloseRef.current = true
      if (timerRef.current) {
        clearTimeout(timerRef.current)
        timerRef.current = null
      }
      const ws = wsRef.current
      wsRef.current = null
      if (!ws) return
      ws.onopen = null
      ws.onmessage = null
      ws.onerror = null
      ws.onclose = null
      if (ws.readyState === WebSocket.OPEN) {
        ws.close()
      } else if (ws.readyState === WebSocket.CONNECTING) {
        ws.onopen = () => ws.close()
      }
    }
  }, [connect])

  return wsRef
}
