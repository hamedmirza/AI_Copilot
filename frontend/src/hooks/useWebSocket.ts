import { useCallback, useEffect, useRef } from 'react'
import { getToken } from '@/api/client'
import { useAppStore } from '@/store'

function wsConnectUrl(path: string): string {
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const sep = path.includes('?') ? '&' : '?'
  return `${proto}//${window.location.host}${path}${sep}token=${encodeURIComponent(getToken())}`
}

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
  const setReconnecting = useAppStore((s) => s.setWsReconnecting)

  onMessageRef.current = onMessage

  const connect = useCallback(() => {
    if (!enabled || !path) return
    const ws = new WebSocket(wsConnectUrl(path))
    wsRef.current = ws

    ws.onopen = () => {
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
      if (trackStatus) setReconnecting(true)
      const delay = Math.min(backoffRef.current, 30000)
      backoffRef.current = Math.min(backoffRef.current * 2, 30000)
      timerRef.current = window.setTimeout(connect, delay)
    }

    ws.onerror = () => ws.close()
  }, [path, enabled, trackStatus, setReconnecting])

  useEffect(() => {
    connect()
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current)
      wsRef.current?.close()
    }
  }, [connect])

  return wsRef
}
