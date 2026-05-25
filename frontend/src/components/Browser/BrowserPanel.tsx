import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Crosshair, ExternalLink, Lightbulb, RefreshCw } from 'lucide-react'
import { api, getToken } from '@/api/client'
import {
  isAllowedPickerOrigin,
  PICKER_MSG,
  type PickerBridgeMessage,
  type PickerElementPayload,
} from '@/lib/browserPickerMessages'
import { AGENT_MSG, type AgentAction, type AgentResultPayload } from '@/lib/browserAgentMessages'
import { registerBrowserAgentExecutor } from '@/lib/browserAgentRegistry'
import {
  formatElementForAgentTask,
  formatElementForChat,
  inferValidationProfile,
  pickerPayloadToSelection,
} from '@/lib/pageElementContext'
import { listenForBrowserRefresh } from '@/lib/browserRefresh'
import { suggestUrlFromPackageJson } from '@/lib/suggestDevServerUrl'
import { openChatForElementFix, useBrowserPickerShortcuts } from '@/hooks/useBrowserPickerShortcuts'
import {
  useChatStore,
  useEditorStore,
  useProjectStore,
  useRunStore,
  useUIStore,
  type PageElementSelection,
} from '@/store'
import { Button } from '@/components/ui/primitives'
import { showError, showSuccess } from '@/lib/toast'
import { toChatSession } from '@/components/Chat/types'
import { ElementSelectionBar } from './ElementSelectionBar'

const BRIDGE_SCRIPT_PATH = '/copilot-picker-bridge.js'
const BRIDGE_HANDSHAKE_MS = 2500

function normalizeUrl(raw: string): string | null {
  const trimmed = raw.trim()
  if (!trimmed) return null
  try {
    const url = new URL(trimmed.includes('://') ? trimmed : `http://${trimmed}`)
    if (url.protocol !== 'http:' && url.protocol !== 'https:') return null
    return url.toString()
  } catch {
    return null
  }
}

function isSameOriginUrl(url: string, parentOrigin: string): boolean {
  try {
    return new URL(url).origin === parentOrigin
  } catch {
    return false
  }
}

type BridgeBanner = 'none' | 'waiting' | 'missing' | 'server_down'

export function BrowserPanel() {
  const projectId = useProjectStore((s) => s.currentProjectId)
  const treeItems = useEditorStore((s) => s.treeItems)
  const runStatus = useRunStore((s) => s.runStatus)
  const currentSessionId = useChatStore((s) => s.currentSessionId)
  const setActiveMode = useChatStore((s) => s.setActiveMode)
  const setComposerPrefill = useChatStore((s) => s.setComposerPrefill)
  const addSpawnedRunId = useChatStore((s) => s.addSpawnedRunId)
  const clearRunEvents = useChatStore((s) => s.clearRunEvents)
  const appendMessage = useChatStore((s) => s.appendMessage)
  const upsertSession = useChatStore((s) => s.upsertSession)

  const browserUrlByProject = useUIStore((s) => s.browserUrlByProject)
  const setBrowserUrlForProject = useUIStore((s) => s.setBrowserUrlForProject)
  const browserPickerActive = useUIStore((s) => s.browserPickerActive)
  const setBrowserPickerActive = useUIStore((s) => s.setBrowserPickerActive)
  const pageElementSelection = useUIStore((s) => s.pageElementSelection)
  const setPageElementSelection = useUIStore((s) => s.setPageElementSelection)
  const browserBridgeReady = useUIStore((s) => s.browserBridgeReady)
  const browserAgentMode = useUIStore((s) => s.browserAgentMode)
  const browserAgentRunId = useUIStore((s) => s.browserAgentRunId)
  const setBrowserAgentMode = useUIStore((s) => s.setBrowserAgentMode)
  const setBrowserBridgeReady = useUIStore((s) => s.setBrowserBridgeReady)
  const pickerBridgeInstalled = useUIStore((s) =>
    projectId ? Boolean(s.pickerBridgeInstalledByProject[projectId]) : false,
  )
  const setPickerBridgeInstalled = useUIStore((s) => s.setPickerBridgeInstalled)

  const storedUrl = projectId ? browserUrlByProject[projectId] ?? '' : ''
  const [inputUrl, setInputUrl] = useState(storedUrl)
  const [frameUrl, setFrameUrl] = useState(storedUrl)
  const [urlError, setUrlError] = useState(false)
  const [refreshKey, setRefreshKey] = useState(0)
  const [bridgeBanner, setBridgeBanner] = useState<BridgeBanner>('none')
  const [suggesting, setSuggesting] = useState(false)

  const iframeRef = useRef<HTMLIFrameElement>(null)
  const handshakeTimerRef = useRef<number | null>(null)
  const lastFrameUrlRef = useRef('')
  const agentPendingRef = useRef<Map<string, {
    resolve: (value: AgentResultPayload) => void
    reject: (reason?: unknown) => void
  }>>(new Map())

  const parentOrigin = typeof window !== 'undefined' ? window.location.origin : ''
  const bridgeScriptUrl = `${parentOrigin}${BRIDGE_SCRIPT_PATH}`
  const isCrossOriginFrame = useMemo(
    () => Boolean(frameUrl && !isSameOriginUrl(frameUrl, parentOrigin)),
    [frameUrl, parentOrigin],
  )
  const previewSrc = useMemo(() => {
    if (!frameUrl) return ''
    const shouldProxy = (browserPickerActive || browserAgentMode) && projectId && isCrossOriginFrame
    if (!shouldProxy) return frameUrl
    const params = new URLSearchParams({ url: frameUrl, project_id: projectId, token: getToken() })
    return `/api/browser/preview?${params.toString()}`
  }, [browserAgentMode, browserPickerActive, frameUrl, isCrossOriginFrame, projectId])

  useEffect(() => {
    setInputUrl(storedUrl)
    setFrameUrl(storedUrl)
    setUrlError(false)
    setBrowserBridgeReady(false)
    setBridgeBanner('none')
  }, [projectId, storedUrl, setBrowserBridgeReady])

  const postToIframe = useCallback((type: string, payload?: Record<string, unknown>) => {
    const win = iframeRef.current?.contentWindow
    if (!win || !previewSrc) return
    try {
      const targetOrigin = new URL(previewSrc, window.location.href).origin
      win.postMessage({ type, payload }, targetOrigin)
    } catch {
      /* ignore */
    }
  }, [previewSrc])

  const injectBridgeSameOrigin = useCallback(() => {
    const iframe = iframeRef.current
    if (!iframe?.contentDocument) return false
    try {
      const frameOrigin = new URL(previewSrc, window.location.href).origin
      if (frameOrigin !== parentOrigin) return false
      const doc = iframe.contentDocument
      if (doc.querySelector(`script[data-copilot-picker-bridge]`)) return true
      const script = doc.createElement('script')
      script.src = bridgeScriptUrl
      script.defer = true
      script.setAttribute('data-copilot-picker-bridge', '1')
      doc.body?.appendChild(script)
      return true
    } catch {
      return false
    }
  }, [bridgeScriptUrl, parentOrigin, previewSrc])

  const enablePickerInFrame = useCallback(() => {
    injectBridgeSameOrigin()
    postToIframe(PICKER_MSG.ENABLE_PICKER, { parentOrigin })
  }, [injectBridgeSameOrigin, postToIframe, parentOrigin])

  const disablePickerInFrame = useCallback(() => {
    postToIframe(PICKER_MSG.DISABLE_PICKER)
  }, [postToIframe])

  const clearHandshakeTimer = useCallback(() => {
    if (handshakeTimerRef.current) {
      window.clearTimeout(handshakeTimerRef.current)
      handshakeTimerRef.current = null
    }
  }, [])

  const startHandshakeTimer = useCallback((crossOrigin: boolean) => {
    clearHandshakeTimer()
    setBridgeBanner('waiting')
    handshakeTimerRef.current = window.setTimeout(() => {
      if (!useUIStore.getState().browserBridgeReady) {
        setBridgeBanner(crossOrigin ? 'server_down' : 'missing')
      }
    }, BRIDGE_HANDSHAKE_MS)
  }, [clearHandshakeTimer])

  const detectProxiedPreviewFailure = useCallback(() => {
    if (!previewSrc.includes('/api/browser/preview')) return false
    const doc = iframeRef.current?.contentDocument
    if (!doc) return false
    const html = doc.documentElement?.innerHTML ?? ''
    return !html.includes('__AI_COPILOT_PICKER_SOURCE_URL__')
  }, [previewSrc])

  const onIframeLoad = useCallback(() => {
    setBrowserBridgeReady(false)
    if (frameUrl !== lastFrameUrlRef.current) {
      setPageElementSelection(null)
      lastFrameUrlRef.current = frameUrl
    }
    if (!browserPickerActive && !browserAgentMode) {
      clearHandshakeTimer()
      setBridgeBanner('none')
      return
    }
    if (browserPickerActive && isCrossOriginFrame && detectProxiedPreviewFailure()) {
      clearHandshakeTimer()
      setBridgeBanner('server_down')
      return
    }
    if (!isCrossOriginFrame) {
      injectBridgeSameOrigin()
    }
    if (browserAgentMode) {
      window.setTimeout(() => {
        setBrowserBridgeReady(true)
        setBridgeBanner('none')
      }, 150)
      return
    }
    startHandshakeTimer(isCrossOriginFrame)
    window.setTimeout(() => enablePickerInFrame(), 100)
  }, [
    browserAgentMode,
    browserPickerActive,
    clearHandshakeTimer,
    detectProxiedPreviewFailure,
    enablePickerInFrame,
    frameUrl,
    injectBridgeSameOrigin,
    isCrossOriginFrame,
    setPageElementSelection,
    setBrowserBridgeReady,
    startHandshakeTimer,
  ])

  const runAgentInFrame = useCallback((
    action: AgentAction,
    args: Record<string, unknown>,
    requestId: string,
  ) => new Promise<AgentResultPayload>((resolve) => {
    if (browserPickerActive) {
      setBrowserPickerActive(false)
      disablePickerInFrame()
    }
    injectBridgeSameOrigin()
    agentPendingRef.current.set(requestId, { resolve, reject: resolve })
    window.setTimeout(() => {
      postToIframe(AGENT_MSG.COMMAND, {
        requestId,
        action,
        ...args,
      })
    }, 200)
    window.setTimeout(() => {
      if (!agentPendingRef.current.has(requestId)) return
      agentPendingRef.current.delete(requestId)
      resolve({ requestId, ok: false, error: 'agent command timeout' })
    }, 45000)
  }), [
    browserPickerActive,
    disablePickerInFrame,
    injectBridgeSameOrigin,
    postToIframe,
    setBrowserPickerActive,
  ])

  useEffect(() => {
    registerBrowserAgentExecutor(async (action, args, requestId) => runAgentInFrame(action, args, requestId))
    return () => registerBrowserAgentExecutor(null)
  }, [runAgentInFrame])

  useEffect(() => {
    const onMessage = (event: MessageEvent) => {
      if (!isAllowedPickerOrigin(event.origin)) return
      const data = event.data as PickerBridgeMessage | undefined
      if (!data?.type) return

      if (String(data.type) === AGENT_MSG.RESULT) {
        const payload = data.payload as unknown as AgentResultPayload
        const requestId = payload?.requestId
        if (!requestId) return
        const pending = agentPendingRef.current.get(requestId)
        if (pending) {
          agentPendingRef.current.delete(requestId)
          pending.resolve(payload || { requestId, ok: false, error: 'empty agent result' })
        }
        return
      }

      if (data.type === PICKER_MSG.BRIDGE_READY) {
        clearHandshakeTimer()
        setBrowserBridgeReady(true)
        setBridgeBanner('none')
        if (projectId) setPickerBridgeInstalled(projectId, true)
        if (browserPickerActive) enablePickerInFrame()
        return
      }

      if (data.type === PICKER_MSG.ELEMENT_SELECTED) {
        const rawPayload = data.payload as
          | PickerElementPayload
          | { selection?: PickerElementPayload }
          | undefined
        const payload = rawPayload && 'selector' in rawPayload
          ? rawPayload
          : rawPayload && 'selection' in rawPayload
            ? rawPayload.selection
            : undefined
        if (!payload) return
        setPageElementSelection(pickerPayloadToSelection(payload))
        setBrowserPickerActive(false)
        disablePickerInFrame()
        clearHandshakeTimer()
        setBridgeBanner('none')
        return
      }

      if (data.type === PICKER_MSG.QUICK_ADD) {
        const rawPayload = data.payload as
          | PickerElementPayload
          | { selection?: PickerElementPayload }
          | undefined
        const payload = rawPayload && 'selector' in rawPayload
          ? rawPayload
          : rawPayload && 'selection' in rawPayload
            ? rawPayload.selection
            : undefined
        if (!payload) return
        const selection = pickerPayloadToSelection(payload)
        setPageElementSelection(selection)
        setBrowserPickerActive(false)
        disablePickerInFrame()
        clearHandshakeTimer()
        setBridgeBanner('none')
        sendSelectionToChat(selection, 'Element added to chat — agent mode enabled')
        return
      }

      if (data.type === PICKER_MSG.PICKER_CANCELLED) {
        setBrowserPickerActive(false)
        disablePickerInFrame()
        clearHandshakeTimer()
        setBridgeBanner('none')
      }
    }

    window.addEventListener('message', onMessage)
    return () => window.removeEventListener('message', onMessage)
  }, [
    browserPickerActive,
    clearHandshakeTimer,
    disablePickerInFrame,
    enablePickerInFrame,
    projectId,
    setBrowserBridgeReady,
    setBrowserPickerActive,
    setPageElementSelection,
    setPickerBridgeInstalled,
    sendSelectionToChat,
  ])

  useEffect(() => () => clearHandshakeTimer(), [clearHandshakeTimer])

  useEffect(() => listenForBrowserRefresh(() => setRefreshKey((k) => k + 1)), [])

  const navigate = useCallback(() => {
    const normalized = normalizeUrl(inputUrl)
    if (!normalized) {
      setUrlError(true)
      return
    }
    setUrlError(false)
    setFrameUrl(normalized)
    setInputUrl(normalized)
    if (projectId) setBrowserUrlForProject(projectId, normalized)
  }, [inputUrl, projectId, setBrowserUrlForProject])

  const openExternal = () => {
    const normalized = normalizeUrl(frameUrl || inputUrl)
    if (normalized) window.open(normalized, '_blank', 'noopener,noreferrer')
  }

  const togglePicker = useCallback(() => {
    if (!projectId || !frameUrl) return
    if (browserPickerActive) {
      clearHandshakeTimer()
      setBrowserPickerActive(false)
      disablePickerInFrame()
      setBridgeBanner('none')
      return
    }
    setBrowserPickerActive(true)
    if (isCrossOriginFrame) {
      setBridgeBanner('waiting')
      setRefreshKey((k) => k + 1)
      return
    }
    if (browserBridgeReady) {
      enablePickerInFrame()
      setBridgeBanner('none')
    } else {
      enablePickerInFrame()
      startHandshakeTimer(false)
    }
  }, [
    browserBridgeReady,
    browserPickerActive,
    clearHandshakeTimer,
    disablePickerInFrame,
    enablePickerInFrame,
    frameUrl,
    isCrossOriginFrame,
    projectId,
    setBrowserPickerActive,
    startHandshakeTimer,
  ])

  function sendSelectionToChat(selection: PageElementSelection, successMessage: string) {
    setActiveMode('agent')
    if (currentSessionId) {
      void api.chat.sessions
        .update(currentSessionId, { mode: 'agent' })
        .then((updated) => upsertSession(toChatSession(updated)))
        .catch((error) => showError(error))
    }
    setComposerPrefill(formatElementForChat(selection))
    openChatForElementFix()
    showSuccess(successMessage)
  }

  const fixInChat = useCallback(() => {
    if (!pageElementSelection) return
    sendSelectionToChat(pageElementSelection, 'Element attached — agent mode enabled')
  }, [pageElementSelection])

  const spawnUiTask = useCallback(async () => {
    if (!pageElementSelection || !projectId) return
    const description = formatElementForAgentTask(pageElementSelection)
    if (description.length < 10) {
      showError('Task description too short')
      return
    }
    const profile = inferValidationProfile(treeItems.map((t) => t.path))
    try {
      let runId = ''
      let taskId = ''
      if (currentSessionId) {
        const result = await api.chat.spawnTask(currentSessionId, {
          description,
          validation_profile: profile,
        }) as Record<string, unknown>
        runId = String(result.run_id || '')
        taskId = String(result.task_id || '')
      } else {
        const fallback = await api.tasks.create({
          project_id: projectId,
          description,
          validation_profile: profile,
        }) as Record<string, unknown>
        runId = String((fallback.run as Record<string, unknown> | undefined)?.id || '')
        taskId = String((fallback.task as Record<string, unknown> | undefined)?.id || '')
      }
      if (!runId) throw new Error('No run id returned')
      addSpawnedRunId(runId)
      clearRunEvents(runId)
      appendMessage({
        id: `assistant-run-${runId}`,
        role: 'assistant',
        content: `Spawned UI task for ${pageElementSelection.selector}`,
        created_at: new Date().toISOString(),
        metadata: { type: 'run_spawned', run_id: runId, task_id: taskId },
      })
      openChatForElementFix()
      showSuccess('UI pipeline task started')
    } catch (error) {
      showError(error)
    }
  }, [
    addSpawnedRunId,
    appendMessage,
    clearRunEvents,
    currentSessionId,
    pageElementSelection,
    projectId,
    treeItems,
  ])

  const suggestDevUrl = async () => {
    if (!projectId) return
    setSuggesting(true)
    try {
      const data = await api.files.read(projectId, 'package.json')
      const content = String((data as { content?: string }).content || '')
      const suggested = suggestUrlFromPackageJson(content)
      if (suggested) {
        setInputUrl(suggested)
        showSuccess(`Suggested ${suggested}`)
      } else {
        showError('Could not infer dev server URL from package.json')
      }
    } catch {
      showError('No package.json found in project root')
    } finally {
      setSuggesting(false)
    }
  }

  const clearSelection = () => {
    setPageElementSelection(null)
    setBrowserPickerActive(false)
    disablePickerInFrame()
    clearHandshakeTimer()
    setBridgeBanner('none')
  }

  const devServerPortHint = useMemo(() => {
    if (!frameUrl) return 'the dev server'
    try {
      const port = new URL(frameUrl).port
      return port ? `:${port}` : 'the dev server'
    } catch {
      return 'the dev server'
    }
  }, [frameUrl])

  useBrowserPickerShortcuts(
    Boolean(projectId && frameUrl && !browserAgentMode),
    {
      togglePicker,
      addToChat: fixInChat,
      cancelPicker: clearSelection,
    },
    {
      hasSelection: Boolean(pageElementSelection),
      pickerActive: browserPickerActive,
    },
  )

  const runBusy = runStatus === 'running'

  if (!projectId) {
    return (
      <div className="h-full flex items-center justify-center text-sm text-[var(--text-secondary)]">
        Select a project to use Browser preview.
      </div>
    )
  }

  return (
    <div className="h-full flex flex-col bg-[var(--bg-primary)]" data-browser-panel>
      <div className="flex items-center gap-2 px-2 py-1.5 border-b border-[var(--border)] shrink-0 flex-wrap">
        <input
          type="text"
          className="flex-1 min-w-0 px-2 py-1 text-sm bg-[var(--bg-secondary)] border border-[var(--border)] rounded outline-none focus:border-[var(--accent)]"
          placeholder="http://localhost:5173"
          value={inputUrl}
          onChange={(e) => setInputUrl(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && navigate()}
        />
        <Button variant="secondary" className="text-xs px-2 py-1" onClick={navigate}>
          Go
        </Button>
        <Button
          variant="secondary"
          className="text-xs px-2 py-1"
          loading={suggesting}
          onClick={() => void suggestDevUrl()}
          title="Suggest URL from package.json"
        >
          <Lightbulb size={14} />
        </Button>
        <button
          type="button"
          title={browserPickerActive ? 'Stop selecting' : 'Select element'}
          className={`p-1.5 rounded border ${
            browserPickerActive
              ? 'border-[var(--accent)] bg-[var(--accent)]/20 text-[var(--accent)]'
              : 'border-transparent text-[var(--text-secondary)] hover:text-white'
          }`}
          onClick={togglePicker}
          disabled={!frameUrl}
        >
          <Crosshair size={16} />
        </button>
        <button
          type="button"
          title="Refresh"
          className="p-1.5 text-[var(--text-secondary)] hover:text-white rounded"
          onClick={() => setRefreshKey((k) => k + 1)}
        >
          <RefreshCw size={16} />
        </button>
        <button
          type="button"
          title="Open in new tab"
          className="p-1.5 text-[var(--text-secondary)] hover:text-white rounded"
          onClick={openExternal}
        >
          <ExternalLink size={16} />
        </button>
      </div>

      {urlError && (
        <p className="px-3 py-2 text-xs text-red-400 shrink-0">
          Enter a valid http or https URL.
        </p>
      )}

      {browserAgentMode && (
        <div className="px-3 py-2 text-xs bg-[var(--accent)]/10 border-b border-[var(--accent)]/30 text-[var(--accent)] shrink-0 flex items-center justify-between gap-2">
          <span>
            Agent controlling browser
            {browserAgentRunId ? ` for run ${browserAgentRunId.slice(0, 8)}…` : ''}
          </span>
          <Button variant="secondary" className="text-xs px-2 py-0.5" onClick={() => setBrowserAgentMode(false, null)}>
            Stop
          </Button>
        </div>
      )}

      {!browserPickerActive && isCrossOriginFrame && frameUrl && !browserAgentMode && (
        <p className="px-3 py-2 text-xs text-[var(--text-secondary)] shrink-0">
          Click crosshair to enable element picker (uses proxy — no script tag needed for localhost apps)
        </p>
      )}

      {bridgeBanner === 'waiting' && frameUrl && browserPickerActive && (
        <p className="px-3 py-2 text-xs text-[var(--text-secondary)] shrink-0">
          {isCrossOriginFrame ? 'Loading proxied preview…' : 'Connecting element picker…'}
        </p>
      )}

      {bridgeBanner === 'server_down' && frameUrl && browserPickerActive && (
        <p className="px-3 py-2 text-xs bg-red-950/40 border-b border-red-800/50 text-red-200 shrink-0">
          Could not reach dev server or proxy failed — is {devServerPortHint} running?
        </p>
      )}

      {bridgeBanner === 'missing'
        && frameUrl
        && !browserBridgeReady
        && browserPickerActive
        && !isCrossOriginFrame && (
        <div className="px-3 py-2 text-xs bg-amber-950/40 border-b border-amber-800/50 text-amber-200 shrink-0 space-y-1">
          <p>
            Element picker needs the dev bridge in your app. Add to your HTML (dev only):
          </p>
          <code className="block text-[10px] break-all opacity-90">
            {`<script src="${bridgeScriptUrl}" defer></script>`}
          </code>
          {!pickerBridgeInstalled && (
            <p className="opacity-80">Reload the preview after adding the script.</p>
          )}
        </div>
      )}

      {browserPickerActive && browserBridgeReady && (
        <p className="px-3 py-1 text-xs text-[var(--accent)] shrink-0">
          Click an element in the preview… (Option+click adds it to chat, Esc cancels)
        </p>
      )}

      {pageElementSelection && (
        <ElementSelectionBar
          selection={pageElementSelection}
          uiTaskDisabled={runBusy}
          uiTaskDisabledReason={runBusy ? 'A pipeline run is in progress' : undefined}
          onFixInChat={fixInChat}
          onUiTask={() => void spawnUiTask()}
          onClear={clearSelection}
        />
      )}

      {!frameUrl ? (
        <div className="flex-1 flex items-center justify-center text-sm text-[var(--text-secondary)]">
          Enter a URL and press Go to preview your app.
        </div>
      ) : (
        <div className="flex-1 relative overflow-hidden">
          <iframe
            ref={iframeRef}
            key={`${previewSrc}-${refreshKey}`}
            src={previewSrc}
            title="Browser preview"
            className="absolute inset-0 w-full h-full border-0"
            sandbox="allow-scripts allow-same-origin allow-forms allow-popups"
            onLoad={onIframeLoad}
            onError={() => {
              setUrlError(true)
              setBridgeBanner('server_down')
            }}
          />
        </div>
      )}
    </div>
  )
}
