import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from '@/api/client'
import { useRunLive } from '@/hooks/useRunLive'
import { dispatchGlobalRunEvent } from '@/lib/globalRunEvents'
import { useRunStore } from '@/store'

type MockHandler = (() => void) | null

class MockWebSocket {
  static OPEN = 1
  static CLOSED = 3
  static instances: MockWebSocket[] = []

  url: string
  readyState = 0
  onopen: MockHandler = null
  onclose: MockHandler = null
  onerror: MockHandler = null
  onmessage: ((ev: { data: string }) => void) | null = null

  constructor(url: string) {
    this.url = url
    MockWebSocket.instances.push(this)
    queueMicrotask(() => {
      if (this.readyState === MockWebSocket.CLOSED) return
      this.readyState = MockWebSocket.OPEN
      this.onopen?.()
    })
  }

  close() {
    if (this.readyState === MockWebSocket.CLOSED) return
    this.readyState = MockWebSocket.CLOSED
    this.onclose?.()
  }

  emit(data: unknown) {
    this.onmessage?.({ data: JSON.stringify(data) })
  }

  static reset() {
    MockWebSocket.instances = []
  }
}

vi.mock('@/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/client')>()
  return {
    ...actual,
    api: {
      runs: {
        get: vi.fn(async () => ({
          id: 'run-1',
          status: 'completed',
          current_stage: 'coder',
          created_at: '2026-01-01T00:00:00Z',
          updated_at: '2026-01-01T00:00:01Z',
        })),
        events: vi.fn(async () => [
          { id: 1, type: 'coder_started', message: 'coder started', created_at: '2026-01-01T00:00:00Z' },
        ]),
      },
    },
  }
})

function Probe({ runId }: { runId: string | null }) {
  const live = useRunLive(runId)
  return (
    <div>
      <span data-testid="count">{live.events.length}</span>
      <span data-testid="line">{live.latestActivityLine || ''}</span>
    </div>
  )
}

describe('useRunLive', () => {
  let container: HTMLDivElement
  let root: Root

  beforeEach(() => {
    MockWebSocket.reset()
    vi.stubGlobal('WebSocket', MockWebSocket as unknown as typeof WebSocket)
    useRunStore.setState({
      currentRunId: null,
      runStatus: 'idle',
      currentStage: null,
      events: [],
      runEventsByRunId: {},
      runs: [],
    })
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)
  })

  afterEach(() => {
    act(() => root.unmount())
    container.remove()
    vi.unstubAllGlobals()
  })

  it('hydrates events and grows on global run event dispatch', async () => {
    await act(async () => {
      root.render(<Probe runId="run-1" />)
    })
    await act(async () => {
      await new Promise((r) => setTimeout(r, 50))
    })
    expect(container.querySelector('[data-testid="count"]')?.textContent).toBe('1')
    expect(MockWebSocket.instances.some((ws) => ws.url.includes('/api/ws/runs/'))).toBe(false)

    await act(async () => {
      dispatchGlobalRunEvent({
        run_id: 'run-1',
        type: 'pipeline_tool_start',
        message: '',
        payload: { tool: 'list_files' },
        created_at: '2026-01-01T00:00:01Z',
      })
      await new Promise((r) => setTimeout(r, 0))
    })
    expect(Number(container.querySelector('[data-testid="count"]')?.textContent)).toBe(2)
    expect(container.querySelector('[data-testid="line"]')?.textContent).toContain('list_files')
  })

  it('does not poll when run status is changes_requested', async () => {
    const events = vi.mocked(api.runs.events)
    vi.mocked(api.runs.get).mockResolvedValue({
      id: 'run-1',
      status: 'changes_requested',
      current_stage: 'documentation',
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:01Z',
    } as never)
    events.mockClear()

    await act(async () => {
      root.render(<Probe runId="run-1" />)
    })
    await act(async () => {
      await new Promise((r) => setTimeout(r, 50))
    })
    const callsAfterHydrate = events.mock.calls.length
    await act(async () => {
      await new Promise((r) => setTimeout(r, 2500))
    })
    expect(events.mock.calls.length).toBe(callsAfterHydrate)
  })
})
