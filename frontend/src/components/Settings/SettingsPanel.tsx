import { useEffect, useRef, useState } from 'react'
import { api } from '@/api/client'
import { useSettingsStore, useAppStore } from '@/store'
import { applyModelsResponse, recommendedLabel, type ModelsApiResponse } from '@/lib/lmstudioModels'
import { showError, showSuccess } from '@/lib/toast'
import { Button, Skeleton } from '@/components/ui/primitives'

const AGENTS = [
  { key: 'model_planner', label: 'Planner', recommended: 'qwen2.5-72b-instruct' },
  { key: 'model_architect', label: 'Architect', recommended: 'qwen2.5-coder-32b-instruct' },
  { key: 'model_ui_designer', label: 'UI Designer', recommended: 'qwen2.5-coder-32b-instruct' },
  { key: 'model_coder', label: 'Coder', recommended: 'qwen2.5-coder-32b-instruct' },
  { key: 'model_reviewer', label: 'Reviewer', recommended: 'qwen2.5-72b-instruct' },
  { key: 'model_tester', label: 'Tester', recommended: 'qwen2.5-coder-7b-instruct' },
  { key: 'model_supervisor', label: 'Supervisor', recommended: 'qwen2.5-72b-instruct' },
]

type ProviderKind = 'lmstudio' | 'ollama'

const CHAT_MODELS = [
  { key: 'model_chat', label: 'General', recommended: 'qwen2.5-72b-instruct' },
  { key: 'model_chat_agent', label: 'Agent', recommended: 'qwen2.5-coder-32b-instruct' },
  { key: 'model_chat_planner', label: 'Planner', recommended: 'qwen2.5-72b-instruct' },
  { key: 'model_chat_debugger', label: 'Debugger', recommended: 'qwen2.5-coder-32b-instruct' },
  { key: 'model_chat_architect', label: 'Architect', recommended: 'qwen2.5-72b-instruct' },
]

function parseArgsInput(value: string): string[] {
  const trimmed = value.trim()
  if (!trimmed) return []
  if (trimmed.startsWith('[')) {
    const parsed = JSON.parse(trimmed)
    if (!Array.isArray(parsed)) {
      throw new Error('Args JSON must be an array of strings')
    }
    return parsed.map((item) => String(item))
  }
  return trimmed
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean)
}

function parseEnvInput(value: string): Record<string, string> {
  const trimmed = value.trim()
  if (!trimmed) return {}
  const parsed = JSON.parse(trimmed)
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
    throw new Error('Environment JSON must be an object of key/value pairs')
  }
  return Object.fromEntries(
    Object.entries(parsed as Record<string, unknown>).map(([key, item]) => [key, String(item)])
  )
}

export function SettingsPanel() {
  const {
    settings,
    setSettings,
    setModels,
    setModelCatalog,
    setModelRecommendations,
    setLmstudioResources,
  } = useSettingsStore()
  const showSettings = useAppStore((s) => s.showSettings)
  const setShowSettings = useAppStore((s) => s.setShowSettings)
  const [loading, setLoading] = useState(true)
  const [pendingProvider, setPendingProvider] = useState<ProviderKind>('lmstudio')
  const [modelsByProvider, setModelsByProvider] = useState<Partial<Record<ProviderKind, ModelsApiResponse>>>({})
  const [testing, setTesting] = useState(false)
  const [testByProvider, setTestByProvider] = useState<Partial<Record<ProviderKind, { ok: boolean; msg: string }>>>({})
  const [saved, setSaved] = useState(false)
  const [lmstudioStatus, setLmstudioStatus] = useState('unknown')
  const [ollamaStatus, setOllamaStatus] = useState('unknown')
  const [mcpServers, setMcpServers] = useState<Array<Record<string, unknown>>>([])
  const [testingServerId, setTestingServerId] = useState<string | null>(null)
  const [savingServerId, setSavingServerId] = useState<string | null>(null)
  const [serverForm, setServerForm] = useState({ name: '', command: '', args: '', envJson: '{}' })
  const importInputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (!showSettings) return
    setLoading(true)
    Promise.all([
      api.settings.get(),
      api.settings.models('lmstudio'),
      api.settings.models('ollama'),
      api.mcp.servers.list().catch(() => [] as Array<Record<string, unknown>>),
    ])
      .then(([s, lmModels, ollamaModels, servers]) => {
        setSettings(s)
        const active: ProviderKind = s.ollama_enabled ? 'ollama' : 'lmstudio'
        setModelsByProvider({ lmstudio: lmModels, ollama: ollamaModels })
        const activeModels = active === 'ollama' ? ollamaModels : lmModels
        applyModelsResponse(activeModels, {
          setModels,
          setModelCatalog,
          setModelRecommendations,
          setLmstudioResources,
        })
        setMcpServers(servers)
        void api.providerHealth().then((health) => {
          setLmstudioStatus(health.lmstudio)
          setOllamaStatus(health.ollama)
        }).catch(() => {})
      })
      .catch(showError)
      .finally(() => setLoading(false))
  }, [showSettings, setSettings, setModels, setModelCatalog, setModelRecommendations, setLmstudioResources])

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === ',') {
        e.preventDefault()
        setShowSettings(true)
      }
      if (e.key === 'Escape') setShowSettings(false)
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [setShowSettings])

  const activeProvider: ProviderKind = settings.ollama_enabled ? 'ollama' : 'lmstudio'
  const providerLabel = (provider: ProviderKind) =>
    provider === 'ollama' ? 'Ollama' : 'LM Studio'
  const snapshotKey = (provider: ProviderKind) =>
    provider === 'ollama' ? 'ollama_role_models_json' : 'lmstudio_role_models_json'

  const getRoleSnapshot = (provider: ProviderKind): Record<string, string> => {
    const raw = settings[snapshotKey(provider)]
    if (raw && typeof raw === 'object' && !Array.isArray(raw)) {
      return raw as Record<string, string>
    }
    return {}
  }

  useEffect(() => {
    if (!showSettings) return
    setPendingProvider(settings.ollama_enabled ? 'ollama' : 'lmstudio')
  }, [showSettings, settings.ollama_enabled])

  const loadProviderModels = async (provider: ProviderKind) => {
    const m = await api.settings.models(provider)
    setModelsByProvider((prev) => ({ ...prev, [provider]: m }))
    return m
  }

  const refreshModels = async () => {
    const m = await loadProviderModels(activeProvider)
    applyModelsResponse(m, {
      setModels,
      setModelCatalog,
      setModelRecommendations,
      setLmstudioResources,
    })
  }

  const roleModelValue = (key: string, editor: ProviderKind) => {
    if (editor === activeProvider) return String(settings[key] || '')
    return getRoleSnapshot(editor)[key] || ''
  }

  const saveRoleModel = async (key: string, value: string, editor: ProviderKind) => {
    if (editor === activeProvider) {
      await save(key, value)
      return
    }
    const snapKey = snapshotKey(editor)
    const snap = { ...getRoleSnapshot(editor), [key]: value }
    try {
      const updated = await api.settings.update({ [snapKey]: snap }) as Record<string, unknown>
      setSettings(updated)
      setSaved(true)
      showSuccess('Saved')
      setTimeout(() => setSaved(false), 2000)
    } catch (e) {
      showError(e)
    }
  }

  const save = async (key: string, value: unknown) => {
    try {
      const updated = await api.settings.update({ [key]: value }) as Record<string, unknown>
      setSettings(updated)
      setSaved(true)
      showSuccess('Saved')
      setTimeout(() => setSaved(false), 2000)
      return updated
    } catch (e) {
      showError(e)
      return null
    }
  }

  const statusDotClass = (status: string) => (
    status === 'healthy' ? 'bg-[var(--success)]' :
    status === 'degraded' ? 'bg-yellow-500' :
    status === 'unknown' ? 'bg-gray-500' : 'bg-[var(--error)]'
  )

  const testConnection = async (provider: ProviderKind) => {
    setTesting(true)
    setTestByProvider((prev) => ({ ...prev, [provider]: undefined }))
    try {
      const health = await api.providerHealth()
      const status = provider === 'ollama' ? health.ollama : health.lmstudio
      const err = provider === 'ollama' ? health.ollama_error : health.lmstudio_error
      const modelCount =
        provider === 'ollama'
          ? (health.ollama_model_count ?? 0)
          : (health.lmstudio_model_count ?? 0)
      setLmstudioStatus(health.lmstudio)
      setOllamaStatus(health.ollama)
      const label = providerLabel(provider)
      let result: { ok: boolean; msg: string }
      if (status === 'healthy') {
        const pressure =
          provider === activeProvider &&
          health.resources_pressure &&
          health.resources_pressure !== 'ok'
            ? `, memory ${health.resources_pressure}`
            : ''
        result = {
          ok: true,
          msg: `${label} connected — ${modelCount} model(s) available${pressure}`,
        }
        await loadProviderModels(provider)
        if (provider === activeProvider) {
          await refreshModels()
        }
      } else if (status === 'degraded' && modelCount > 0) {
        const suggestion =
          provider === 'ollama' && health.suggested_ollama_base_url
            ? ` Try ${health.suggested_ollama_base_url}.`
            : ''
        result = {
          ok: false,
          msg: (err || 'Connected but model configuration needs attention') + suggestion,
        }
        await loadProviderModels(provider)
        if (provider === activeProvider) {
          await refreshModels()
        }
      } else {
        const suggestion =
          provider === 'ollama' && health.suggested_ollama_base_url
            ? ` Reachable at ${health.suggested_ollama_base_url} — update Ollama URL in Settings.`
            : ''
        result = { ok: false, msg: (err || 'Connection failed') + suggestion }
      }
      setTestByProvider((prev) => ({ ...prev, [provider]: result }))
    } catch (e) {
      setTestByProvider((prev) => ({
        ...prev,
        [provider]: { ok: false, msg: e instanceof Error ? e.message : 'Failed' },
      }))
    } finally {
      setTesting(false)
    }
  }

  const applyActiveProvider = async () => {
    setTesting(true)
    try {
      const updated = await api.settings.update({
        ollama_enabled: pendingProvider === 'ollama',
        sync_role_models: true,
      }) as Record<string, unknown>
      setSettings(updated)
      const switched = pendingProvider !== activeProvider
      await Promise.all([loadProviderModels('lmstudio'), loadProviderModels('ollama')])
      await refreshModels()
      await testConnection(pendingProvider)
      showSuccess(
        switched
          ? `Active provider set to ${providerLabel(pendingProvider)}`
          : 'Provider models synced',
      )
    } catch (e) {
      showError(e)
    } finally {
      setTesting(false)
    }
  }

  const refreshMcpServers = async () => {
    try {
      const servers = await api.mcp.servers.list()
      setMcpServers(servers)
    } catch (e) {
      showError(e)
    }
  }

  const saveServer = async () => {
    if (!serverForm.name.trim() || !serverForm.command.trim()) {
      showError('Server name and command are required')
      return
    }
    setSavingServerId('new')
    try {
      const args = parseArgsInput(serverForm.args)
      const env = parseEnvInput(serverForm.envJson)
      await api.mcp.servers.create({
        name: serverForm.name.trim(),
        command: serverForm.command.trim(),
        args,
        env,
      })
      setServerForm({ name: '', command: '', args: '', envJson: '{}' })
      showSuccess('MCP server added')
      await refreshMcpServers()
    } catch (e) {
      showError(e)
    } finally {
      setSavingServerId(null)
    }
  }

  const exportMcpServers = async () => {
    try {
      const payload = await api.mcp.servers.export()
      const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' })
      const url = URL.createObjectURL(blob)
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = 'mcp-servers.json'
      anchor.click()
      URL.revokeObjectURL(url)
      showSuccess('MCP config exported')
    } catch (error) {
      showError(error)
    }
  }

  const importMcpServers = async (file: File) => {
    try {
      const raw = JSON.parse(await file.text()) as { servers?: Array<Record<string, unknown>> } | Array<Record<string, unknown>>
      const servers = Array.isArray(raw) ? raw : Array.isArray(raw?.servers) ? raw.servers : []
      if (servers.length === 0) {
        throw new Error('Import file does not contain any MCP servers')
      }
      const replaceExisting = window.confirm(
        'Replace existing MCP servers?\n\nChoose OK to replace all existing entries, or Cancel to merge by name.'
      )
      await api.mcp.servers.import({ servers, replace_existing: replaceExisting })
      showSuccess(`Imported ${servers.length} MCP server${servers.length === 1 ? '' : 's'}`)
      await refreshMcpServers()
    } catch (error) {
      showError(error)
    }
  }

  if (!showSettings) return null

  return (
    <div className="fixed inset-0 bg-black/60 z-50 flex items-center justify-center">
      <div className="bg-[var(--bg-secondary)] border border-[var(--border)] rounded-lg w-[720px] max-h-[80vh] overflow-auto p-4">
        <div className="flex justify-between items-center mb-4">
          <h2 className="text-lg font-medium">Settings</h2>
          <button onClick={() => setShowSettings(false)} className="text-[var(--text-secondary)] hover:text-white">×</button>
        </div>

        {loading ? (
          <div className="space-y-3">{[1, 2, 3, 4].map((i) => <Skeleton key={i} className="h-8" />)}</div>
        ) : (
          <div className="space-y-4">
            {saved && <span className="text-[var(--success)] text-sm">Saved ✓</span>}

            <section>
              <h3 className="text-sm font-medium mb-2 text-[var(--text-secondary)]">LLM provider</h3>
              <div className="flex items-center gap-2">
                <select
                  className="flex-1 bg-[var(--bg-tertiary)] border border-[var(--border)] rounded px-2 py-1.5 text-sm"
                  value={pendingProvider}
                  disabled={testing}
                  onChange={(e) => setPendingProvider(e.target.value as ProviderKind)}
                >
                  <option value="lmstudio">LM Studio</option>
                  <option value="ollama">Ollama (Mac Studio)</option>
                </select>
                <Button loading={testing} onClick={() => void applyActiveProvider()}>
                  {pendingProvider === activeProvider ? 'Sync' : 'Apply'}
                </Button>
              </div>
              <p className="text-xs mt-2 text-[var(--text-secondary)]">
                Active: <strong className="text-[var(--text-primary)]">{providerLabel(activeProvider)}</strong>
                {pendingProvider !== activeProvider && ` — Apply to switch to ${providerLabel(pendingProvider)}.`}
              </p>
            </section>

            <section>
              <h3 className="text-sm font-medium mb-2 text-[var(--text-secondary)]">Pipeline runtime</h3>
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={
                    settings.auto_resume_enabled !== false
                    && settings.auto_resume_enabled !== 'false'
                  }
                  onChange={(e) => void save('auto_resume_enabled', e.target.checked)}
                />
                Resume interrupted runs on server startup
              </label>
              <p className="text-xs mt-1 text-[var(--text-secondary)]">
                When enabled, the backend re-enqueues one pending or running run after restart.
              </p>
            </section>

            {pendingProvider === 'lmstudio' && (
              <section>
                <div className="flex items-center gap-2 mb-2">
                  <h3 className="text-sm font-medium text-[var(--text-secondary)]">LM Studio</h3>
                  <span className={`w-2 h-2 rounded-full ml-auto ${statusDotClass(lmstudioStatus)}`} />
                </div>
                <label className="block text-xs mb-1">Base URL</label>
                <input
                  className="w-full bg-[var(--bg-tertiary)] border border-[var(--border)] rounded px-2 py-1 text-sm"
                  value={String(settings.lmstudio_base_url || 'http://172.10.1.2:1234/v1')}
                  onChange={(e) => setSettings({ ...settings, lmstudio_base_url: e.target.value })}
                  onBlur={(e) => { void save('lmstudio_base_url', e.target.value); void testConnection('lmstudio') }}
                />
                {modelsByProvider.lmstudio?.resources && (
                  <p className="text-xs mt-1 text-[var(--text-secondary)]">
                    Loaded: {modelsByProvider.lmstudio.resources.loaded_count} model(s), {modelsByProvider.lmstudio.resources.loaded_size_gb} GB
                    {modelsByProvider.lmstudio.resources.pressure !== 'ok' ? ` • memory pressure: ${modelsByProvider.lmstudio.resources.pressure}` : ''}
                  </p>
                )}
                <Button className="mt-3" loading={testing} onClick={() => void testConnection('lmstudio')}>
                  Test connection
                </Button>
                {testByProvider.lmstudio && (
                  <p className={`text-xs mt-1 ${testByProvider.lmstudio.ok ? 'text-[var(--success)]' : 'text-[var(--error)]'}`}>
                    {testByProvider.lmstudio.ok ? '✓' : '✕'} {testByProvider.lmstudio.msg}
                  </p>
                )}
              </section>
            )}

            {pendingProvider === 'ollama' && (
              <section>
                <div className="flex items-center gap-2 mb-2">
                  <h3 className="text-sm font-medium text-[var(--text-secondary)]">Ollama (Mac Studio)</h3>
                  <span className={`w-2 h-2 rounded-full ml-auto ${statusDotClass(ollamaStatus)}`} />
                </div>
                <label className="block text-xs mb-1">Base URL</label>
                <input
                  className="w-full bg-[var(--bg-tertiary)] border border-[var(--border)] rounded px-2 py-1 text-sm"
                  placeholder="http://172.10.1.2:11434/v1"
                  value={String(settings.ollama_base_url || 'http://172.10.1.2:11434/v1')}
                  onChange={(e) => setSettings({ ...settings, ollama_base_url: e.target.value })}
                  onBlur={(e) => { void save('ollama_base_url', e.target.value); void testConnection('ollama') }}
                />
                <label className="block text-xs mt-3 mb-1">Default model</label>
                <select
                  className="w-full bg-[var(--bg-tertiary)] border border-[var(--border)] rounded px-2 py-1 text-sm"
                  value={String(settings.ollama_model || '')}
                  disabled={(modelsByProvider.ollama?.models.length ?? 0) === 0}
                  onChange={(e) => void save('ollama_model', e.target.value)}
                >
                  <option value="">Select a model…</option>
                  {(modelsByProvider.ollama?.models ?? []).map((m) => <option key={m} value={m}>{m}</option>)}
                </select>
                {(modelsByProvider.ollama?.models.length ?? 0) > 0 && (
                  <p className="text-xs mt-1 text-[var(--text-secondary)]">
                    {modelsByProvider.ollama?.models.length} model(s) available
                  </p>
                )}
                <Button className="mt-3" loading={testing} onClick={() => void testConnection('ollama')}>
                  Test connection
                </Button>
                {testByProvider.ollama && (
                  <p className={`text-xs mt-1 ${testByProvider.ollama.ok ? 'text-[var(--success)]' : 'text-[var(--error)]'}`}>
                    {testByProvider.ollama.ok ? '✓' : '✕'} {testByProvider.ollama.msg}
                  </p>
                )}
              </section>
            )}

            <section>
              <h3 className="text-sm font-medium mb-2 text-[var(--text-secondary)]">
                Shared limits ({providerLabel(activeProvider)} when applied)
              </h3>
              <label className="block text-xs mb-1">Provider timeout (seconds)</label>
              <input
                type="number"
                min={30}
                max={900}
                step={30}
                className="w-full bg-[var(--bg-tertiary)] border border-[var(--border)] rounded px-2 py-1 text-sm"
                value={Number(settings.provider_timeout_seconds || 300)}
                onChange={(e) => {
                  const next = Number.parseInt(e.target.value, 10)
                  if (!Number.isNaN(next)) {
                    setSettings({ ...settings, provider_timeout_seconds: next })
                  }
                }}
                onBlur={(e) => {
                  const raw = Number.parseInt(e.target.value, 10)
                  const clamped = Number.isNaN(raw) ? 300 : Math.min(900, Math.max(30, raw))
                  void save('provider_timeout_seconds', clamped)
                }}
              />
              <p className="text-xs mt-1 text-[var(--text-secondary)]">
                How long to wait for the active provider before timing out (default 300s).
              </p>
              <label className="block text-xs mt-3 mb-1">Chat context budget (tokens)</label>
              <input
                type="number"
                min={2048}
                max={200000}
                step={1024}
                className="w-full bg-[var(--bg-tertiary)] border border-[var(--border)] rounded px-2 py-1 text-sm"
                value={Number(settings.chat_max_context_tokens || 32768)}
                onChange={(e) => {
                  const next = Number.parseInt(e.target.value, 10)
                  if (!Number.isNaN(next)) {
                    setSettings({ ...settings, chat_max_context_tokens: next })
                  }
                }}
                onBlur={(e) => {
                  const raw = Number.parseInt(e.target.value, 10)
                  const clamped = Number.isNaN(raw) ? 32768 : Math.min(200000, Math.max(2048, raw))
                  void save('chat_max_context_tokens', clamped)
                }}
              />
              <label className="block text-xs mt-2 mb-1">Chat max output (max_tokens)</label>
              <input
                type="number"
                min={256}
                max={32768}
                step={256}
                className="w-full bg-[var(--bg-tertiary)] border border-[var(--border)] rounded px-2 py-1 text-sm"
                value={Number(settings.chat_max_output_tokens || 4096)}
                onChange={(e) => {
                  const next = Number.parseInt(e.target.value, 10)
                  if (!Number.isNaN(next)) {
                    setSettings({ ...settings, chat_max_output_tokens: next })
                  }
                }}
                onBlur={(e) => {
                  const raw = Number.parseInt(e.target.value, 10)
                  const clamped = Number.isNaN(raw) ? 4096 : Math.min(32768, Math.max(256, raw))
                  void save('chat_max_output_tokens', clamped)
                }}
              />
              <label className="block text-xs mt-2 mb-1">Chat history window (messages)</label>
              <input
                type="number"
                min={1}
                max={500}
                step={1}
                className="w-full bg-[var(--bg-tertiary)] border border-[var(--border)] rounded px-2 py-1 text-sm"
                value={Number(settings.chat_history_limit || 50)}
                onChange={(e) => {
                  const next = Number.parseInt(e.target.value, 10)
                  if (!Number.isNaN(next)) {
                    setSettings({ ...settings, chat_history_limit: next })
                  }
                }}
                onBlur={(e) => {
                  const raw = Number.parseInt(e.target.value, 10)
                  const clamped = Number.isNaN(raw) ? 50 : Math.min(500, Math.max(1, raw))
                  void save('chat_history_limit', clamped)
                }}
              />
              <p className="text-xs mt-1 text-[var(--text-secondary)]">
                Uses the newest messages first, counts tokens with tiktoken (cl100k_base), then sends max_tokens to the active provider.
                Match context budget to your loaded model (e.g. 8192, 32768).
              </p>
            </section>

            <section>
              <h3 className="text-sm font-medium mb-2 text-[var(--text-secondary)]">
                Per-Agent Models — {providerLabel(pendingProvider)}
              </h3>
              {AGENTS.map(({ key, label, recommended }) => {
                const editorModels = modelsByProvider[pendingProvider]?.models ?? []
                const editorRecs = modelsByProvider[pendingProvider]?.recommendations ?? {}
                return (
                  <div key={key} className="flex items-center gap-2 mb-2">
                    <label className="w-28 text-xs">{label}</label>
                    <select
                      className="flex-1 bg-[var(--bg-tertiary)] border border-[var(--border)] rounded px-2 py-1 text-sm"
                      value={roleModelValue(key, pendingProvider)}
                      onChange={(e) => void saveRoleModel(key, e.target.value, pendingProvider)}
                    >
                      <option value={editorRecs[key] || recommended}>
                        {recommendedLabel(key, recommended, editorRecs)}
                      </option>
                      {editorModels.map((m) => <option key={m} value={m}>{m}</option>)}
                    </select>
                  </div>
                )
              })}
            </section>

            <section>
              <h3 className="text-sm font-medium mb-2 text-[var(--text-secondary)]">
                Chat Models — {providerLabel(pendingProvider)}
              </h3>
              {CHAT_MODELS.map(({ key, label, recommended }) => {
                const editorModels = modelsByProvider[pendingProvider]?.models ?? []
                const editorRecs = modelsByProvider[pendingProvider]?.recommendations ?? {}
                return (
                  <div key={key} className="flex items-center gap-2 mb-2">
                    <label className="w-28 text-xs">{label}</label>
                    <select
                      className="flex-1 bg-[var(--bg-tertiary)] border border-[var(--border)] rounded px-2 py-1 text-sm"
                      value={roleModelValue(key, pendingProvider)}
                      onChange={(e) => void saveRoleModel(key, e.target.value, pendingProvider)}
                    >
                      <option value={editorRecs[key] || recommended}>
                        {recommendedLabel(key, recommended, editorRecs)}
                      </option>
                      {editorModels.map((m) => <option key={m} value={m}>{m}</option>)}
                    </select>
                  </div>
                )
              })}
              <label className="flex items-center gap-2 text-sm mt-3">
                <input
                  type="checkbox"
                  checked={settings.nothink_default !== false && settings.nothink_default !== 'false'}
                  onChange={(e) => save('nothink_default', e.target.checked)}
                />
                Disable thinking by default (/nothink)
              </label>
            </section>

            <section>
              <h3 className="text-sm font-medium mb-2 text-[var(--text-secondary)]">MCP Servers</h3>
              <div className="space-y-3">
                <input
                  ref={importInputRef}
                  type="file"
                  accept="application/json"
                  className="hidden"
                  onChange={(event) => {
                    const file = event.target.files?.[0]
                    if (file) {
                      void importMcpServers(file)
                    }
                    event.currentTarget.value = ''
                  }}
                />
                <div className="grid grid-cols-3 gap-2">
                  <input
                    className="bg-[var(--bg-tertiary)] border border-[var(--border)] rounded px-2 py-1 text-sm"
                    placeholder="Server name"
                    value={serverForm.name}
                    onChange={(e) => setServerForm((current) => ({ ...current, name: e.target.value }))}
                  />
                  <input
                    className="bg-[var(--bg-tertiary)] border border-[var(--border)] rounded px-2 py-1 text-sm"
                    placeholder="Command"
                    value={serverForm.command}
                    onChange={(e) => setServerForm((current) => ({ ...current, command: e.target.value }))}
                  />
                  <input
                    className="bg-[var(--bg-tertiary)] border border-[var(--border)] rounded px-2 py-1 text-sm"
                    placeholder="Args, comma separated"
                    value={serverForm.args}
                    onChange={(e) => setServerForm((current) => ({ ...current, args: e.target.value }))}
                  />
                </div>
                <textarea
                  className="w-full min-h-24 bg-[var(--bg-tertiary)] border border-[var(--border)] rounded px-2 py-1 text-sm font-mono"
                  placeholder='Environment JSON, e.g. { "API_KEY": "secret" }'
                  value={serverForm.envJson}
                  onChange={(e) => setServerForm((current) => ({ ...current, envJson: e.target.value }))}
                />
                <div className="flex gap-2">
                  <Button onClick={saveServer} loading={savingServerId === 'new'}>
                    Add Server
                  </Button>
                  <Button variant="secondary" onClick={() => void refreshMcpServers()}>
                    Refresh
                  </Button>
                  <Button variant="secondary" onClick={() => void exportMcpServers()}>
                    Export JSON
                  </Button>
                  <Button variant="secondary" onClick={() => importInputRef.current?.click()}>
                    Import JSON
                  </Button>
                </div>
                <p className="text-xs text-[var(--text-secondary)]">
                  `args` accepts comma-separated values or a JSON array. `env` uses raw JSON and is included in export/import.
                </p>

                <div className="space-y-2">
                  {mcpServers.length === 0 && (
                    <p className="text-xs text-[var(--text-secondary)]">No MCP servers configured yet.</p>
                  )}
                  {mcpServers.map((server) => {
                    const serverId = String(server.id || '')
                    return (
                      <div key={serverId || String(server.name)} className="border border-[var(--border)] rounded p-3 bg-[var(--bg-tertiary)] space-y-2">
                        <div className="flex items-center justify-between gap-3">
                          <div className="min-w-0">
                            <p className="text-sm font-medium truncate">{String(server.name || 'Unnamed server')}</p>
                            <p className="text-xs text-[var(--text-secondary)] truncate">
                              {String(server.command || '')} {Array.isArray(server.args) ? (server.args as string[]).join(' ') : String(server.args_json || '')}
                            </p>
                          </div>
                          <label className="flex items-center gap-2 text-xs">
                            <input
                              type="checkbox"
                              checked={server.enabled !== false}
                              onChange={async (e) => {
                                setSavingServerId(serverId)
                                try {
                                  await api.mcp.servers.update(serverId, { enabled: e.target.checked })
                                  await refreshMcpServers()
                                } catch (error) {
                                  showError(error)
                                } finally {
                                  setSavingServerId(null)
                                }
                              }}
                            />
                            Enabled
                          </label>
                        </div>

                        <div className="flex items-center gap-3 text-xs text-[var(--text-secondary)]">
                          <span>Status: {String(server.last_status || server.status || 'unknown')}</span>
                          <span>Tools: {String(server.tool_count || server.tool_count_json || 0)}</span>
                          <span>Env: {Object.keys((server.env as Record<string, unknown>) || {}).length}</span>
                          {server.last_error && <span className="text-[var(--error)] truncate">Error: {String(server.last_error)}</span>}
                        </div>

                        <div className="flex gap-2">
                          <Button
                            variant="secondary"
                            loading={testingServerId === serverId}
                            onClick={async () => {
                              setTestingServerId(serverId)
                              try {
                                const result = await api.mcp.servers.test(serverId)
                                const toolCount = Array.isArray(result.tools) ? result.tools.length : Number(result.tool_count || 0)
                                showSuccess(
                                  typeof result.message === 'string'
                                    ? result.message
                                    : `Server responded with ${String(toolCount)} tools`
                                )
                                await refreshMcpServers()
                              } catch (error) {
                                showError(error)
                              } finally {
                                setTestingServerId(null)
                              }
                            }}
                          >
                            Test
                          </Button>
                          <Button
                            variant="ghost"
                            disabled={savingServerId === serverId}
                            onClick={async () => {
                              if (!confirm(`Delete MCP server "${String(server.name || 'server')}"?`)) return
                              setSavingServerId(serverId)
                              try {
                                await api.mcp.servers.delete(serverId)
                                showSuccess('MCP server deleted')
                                await refreshMcpServers()
                              } catch (error) {
                                showError(error)
                              } finally {
                                setSavingServerId(null)
                              }
                            }}
                          >
                            Delete
                          </Button>
                        </div>
                      </div>
                    )
                  })}
                </div>
              </div>
            </section>

            <section>
              <h3 className="text-sm font-medium mb-2 text-[var(--text-secondary)]">Editor</h3>
              <div className="flex gap-4">
                <div>
                  <label className="text-xs">Font Size</label>
                  <input
                    type="number"
                    className="block bg-[var(--bg-tertiary)] border border-[var(--border)] rounded px-2 py-1 text-sm w-20"
                    value={Number(settings.editor_font_size) || 14}
                    onChange={(e) => save('editor_font_size', Number(e.target.value))}
                  />
                </div>
                <label className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={!!settings.editor_auto_save}
                    onChange={(e) => save('editor_auto_save', e.target.checked)}
                  />
                  Auto-save (2s debounce)
                </label>
              </div>
            </section>

            <Button
              variant="secondary"
              onClick={async () => {
                if (!confirm('Reset all settings to defaults?')) return
                try {
                  const updated = await api.settings.reset()
                  setSettings(updated)
                  setSaved(true)
                  showSuccess('Reset to defaults')
                  setTimeout(() => setSaved(false), 2000)
                } catch (e) {
                  showError(e)
                }
              }}
            >
              Reset to defaults
            </Button>
          </div>
        )}
      </div>
    </div>
  )
}
