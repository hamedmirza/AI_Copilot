import { useCallback, useEffect, useRef, useState } from 'react'
import { Terminal } from 'xterm'
import { FitAddon } from '@xterm/addon-fit'
import { WebLinksAddon } from '@xterm/addon-web-links'
import 'xterm/css/xterm.css'
import { wsUrl } from '@/api/client'
import { useProjectStore } from '@/store'
import { Button } from '@/components/ui/primitives'

interface TermTab {
  id: string
  term: Terminal
  fitAddon: FitAddon
  ws: WebSocket | null
}

export function TerminalPanel() {
  const projectId = useProjectStore((s) => s.currentProjectId)
  const [tabs, setTabs] = useState<TermTab[]>([])
  const [activeId, setActiveId] = useState<string | null>(null)
  const termContainerRef = useRef<HTMLDivElement>(null)
  const projectIdRef = useRef<string | null>(null)

  const disposeTab = (tab: TermTab) => {
    try {
      tab.ws?.close()
    } catch {
      // ignore close failures during cleanup
    }
    tab.term.dispose()
  }

  const disposeAllTabs = useCallback(() => {
    setTabs((prev) => {
      prev.forEach(disposeTab)
      return []
    })
    setActiveId(null)
  }, [])

  const spawnTerminal = useCallback(() => {
    if (!projectId) return
    const id = crypto.randomUUID()
    const term = new Terminal({ cursorBlink: true, fontSize: 13, theme: { background: '#1e1e1e' } })
    const fitAddon = new FitAddon()
    term.loadAddon(fitAddon)
    term.loadAddon(new WebLinksAddon())
    const ws = new WebSocket(wsUrl(`/api/ws/terminal/${id}?project_id=${projectId}`))
    ws.onopen = () => term.writeln('Connected to shell...')
    ws.onmessage = (ev) => term.write(ev.data)
    term.onData((data) => {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'input', data }))
      }
    })
    term.attachCustomKeyEventHandler((event) => {
      if (event.ctrlKey && event.key === 'c' && event.type === 'keydown') {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ type: 'input', data: '\x03' }))
        }
        return false
      }
      return true
    })
    const tab: TermTab = { id, term, fitAddon, ws }
    setTabs((prev) => [...prev, tab])
    setActiveId(id)
  }, [projectId])

  useEffect(() => {
    if (projectIdRef.current === projectId) return
    projectIdRef.current = projectId
    disposeAllTabs()
    if (projectId) {
      queueMicrotask(() => {
        spawnTerminal()
      })
    }
  }, [disposeAllTabs, projectId, spawnTerminal])

  useEffect(() => () => {
    disposeAllTabs()
  }, [disposeAllTabs])

  useEffect(() => {
    const active = tabs.find((t) => t.id === activeId)
    if (!active || !termContainerRef.current) return
    termContainerRef.current.innerHTML = ''
    active.term.open(termContainerRef.current)
    active.fitAddon.fit()
    const ro = new ResizeObserver(() => {
      active.fitAddon.fit()
      if (active.ws?.readyState === WebSocket.OPEN) {
        active.ws.send(JSON.stringify({
          type: 'resize',
          cols: active.term.cols,
          rows: active.term.rows,
        }))
      }
    })
    ro.observe(termContainerRef.current)
    return () => ro.disconnect()
  }, [activeId, tabs])

  const closeTab = (id: string) => {
    const tab = tabs.find((t) => t.id === id)
    if (tab) disposeTab(tab)
    setTabs((prev) => prev.filter((t) => t.id !== id))
    if (activeId === id) setActiveId(tabs.find((t) => t.id !== id)?.id ?? null)
  }

  return (
    <div className="h-full flex flex-col bg-[#1e1e1e]">
      <div className="flex items-center border-b border-[var(--border)]">
        {tabs.map((t) => (
          <div
            key={t.id}
            className={`flex items-center gap-1 px-3 py-1 text-xs cursor-pointer border-r border-[var(--border)] ${
              activeId === t.id ? 'bg-[var(--bg-primary)]' : ''
            }`}
            onClick={() => setActiveId(t.id)}
          >
            bash
            <button onClick={(e) => { e.stopPropagation(); closeTab(t.id) }}>×</button>
          </div>
        ))}
        <Button variant="ghost" className="text-xs" onClick={spawnTerminal}>+</Button>
      </div>
      <div ref={termContainerRef} className="flex-1 p-1" />
    </div>
  )
}
