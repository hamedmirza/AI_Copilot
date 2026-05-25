import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ChatWebSocketBridge } from '@/components/Chat/ChatWebSocketBridge'
import { useChatStore } from '@/store'

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

function chatSockets() {
  return MockWebSocket.instances.filter((ws) => ws.url.includes('/api/ws/chat/'))
}

function resetChatStore(sessionId: string | null = 'session-1') {
  useChatStore.setState({
    sessions: [],
    currentSessionId: sessionId,
    historyOpen: false,
    historySearchQuery: '',
    messages: [],
    streaming: false,
    activeMode: 'general',
    modelSelectionMode: 'auto',
    selectedModel: '',
    pendingToolCalls: [],
    spawnedRunIds: [],
    streamingContent: '',
    assistantStatus: null,
    runEventsById: {},
    pendingRunId: null,
    composerPrefill: '',
  })
}

function PanelStub() {
  return <div data-testid="chat-panel-stub">chat panel</div>
}

function AppLike({ showPanel }: { showPanel: boolean }) {
  return (
    <>
      <ChatWebSocketBridge />
      {showPanel ? <PanelStub /> : null}
    </>
  )
}

describe('useChatWebSocket / ChatWebSocketBridge', () => {
  let container: HTMLDivElement
  let root: Root

  beforeEach(() => {
    vi.stubGlobal('WebSocket', MockWebSocket)
    MockWebSocket.reset()
    resetChatStore('session-1')
    localStorage.setItem('api_token', 'dev-token')
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)
  })

  afterEach(() => {
    act(() => {
      root.unmount()
    })
    container.remove()
    vi.unstubAllGlobals()
  })

  async function renderAppLike(showPanel: boolean) {
    await act(async () => {
      root.render(<AppLike showPanel={showPanel} />)
    })
    await vi.waitFor(() => {
      expect(chatSockets().length).toBeGreaterThan(0)
    })
  }

  it('opens a chat socket when currentSessionId is set', async () => {
    await renderAppLike(true)
    const [socket] = chatSockets()
    expect(socket.url).toContain('/api/ws/chat/session-1')
    expect(socket.readyState).toBe(MockWebSocket.OPEN)
  })

  it('keeps the chat socket open when the chat panel unmounts (collapsed right panel)', async () => {
    await renderAppLike(true)
    const [socket] = chatSockets()
    expect(container.querySelector('[data-testid="chat-panel-stub"]')).not.toBeNull()

    await act(async () => {
      root.render(<AppLike showPanel={false} />)
    })

    expect(container.querySelector('[data-testid="chat-panel-stub"]')).toBeNull()
    expect(chatSockets()).toHaveLength(1)
    expect(socket.readyState).toBe(MockWebSocket.OPEN)
  })

  it('applies streaming token events while the panel is hidden', async () => {
    await renderAppLike(true)
    const [socket] = chatSockets()

    await act(async () => {
      root.render(<AppLike showPanel={false} />)
    })

    await act(async () => {
      socket.emit({ type: 'token', token: 'hello' })
    })

    const state = useChatStore.getState()
    expect(state.streaming).toBe(true)
    expect(state.streamingContent).toBe('hello')
    expect(state.messages.some((message) => message.content.includes('hello'))).toBe(true)
  })

  it('reconnects when currentSessionId changes', async () => {
    await renderAppLike(true)
    const first = chatSockets()[0]
    expect(first.url).toContain('session-1')

    resetChatStore('session-2')
    await act(async () => {
      root.render(<AppLike showPanel={true} />)
    })

    await vi.waitFor(() => {
      expect(chatSockets().length).toBe(2)
    })
    expect(first.readyState).toBe(MockWebSocket.CLOSED)
    expect(chatSockets()[1].url).toContain('/api/ws/chat/session-2')
    expect(chatSockets()[1].readyState).toBe(MockWebSocket.OPEN)
  })

  it('does not open a chat socket without currentSessionId', async () => {
    resetChatStore(null)
    await act(async () => {
      root.render(<AppLike showPanel={true} />)
    })
    await new Promise((resolve) => setTimeout(resolve, 20))
    expect(chatSockets()).toHaveLength(0)
  })
})
