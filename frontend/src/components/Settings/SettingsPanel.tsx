import { useEffect, useState } from 'react'
import { api } from '@/api/client'
import { useSettingsStore, useAppStore } from '@/store'
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

export function SettingsPanel() {
  const { settings, models, setSettings, setModels } = useSettingsStore()
  const showSettings = useAppStore((s) => s.showSettings)
  const setShowSettings = useAppStore((s) => s.setShowSettings)
  const [loading, setLoading] = useState(true)
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState<{ ok: boolean; msg: string } | null>(null)
  const [saved, setSaved] = useState(false)
  const [providerStatus, setProviderStatus] = useState('unknown')

  useEffect(() => {
    if (!showSettings) return
    setLoading(true)
    Promise.all([api.settings.get(), api.settings.models()])
      .then(([s, m]) => { setSettings(s); setModels(m.models) })
      .catch(showError)
      .finally(() => setLoading(false))
  }, [showSettings, setSettings, setModels])

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

  const save = async (key: string, value: unknown) => {
    try {
      const updated = await api.settings.update({ [key]: value }) as Record<string, unknown>
      setSettings(updated)
      setSaved(true)
      showSuccess('Saved')
      setTimeout(() => setSaved(false), 2000)
    } catch (e) {
      showError(e)
    }
  }

  const testConnection = async () => {
    setTesting(true)
    setTestResult(null)
    try {
      const health = await api.providerHealth()
      setProviderStatus(health.lmstudio)
      if (health.lmstudio === 'healthy') {
        setTestResult({ ok: true, msg: `Connected, ${health.model_count} models available` })
        const m = await api.settings.models()
        setModels(m.models)
      } else if (health.lmstudio === 'degraded' && health.model_count > 0) {
        setTestResult({ ok: false, msg: health.error || 'Connected but model configuration needs attention' })
      } else {
        setTestResult({ ok: false, msg: health.error || 'Connection failed' })
      }
    } catch (e) {
      setTestResult({ ok: false, msg: e instanceof Error ? e.message : 'Failed' })
    } finally {
      setTesting(false)
    }
  }

  if (!showSettings) return null

  return (
    <div className="fixed inset-0 bg-black/60 z-50 flex items-center justify-center">
      <div className="bg-[var(--bg-secondary)] border border-[var(--border)] rounded-lg w-[600px] max-h-[80vh] overflow-auto p-4">
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
              <h3 className="text-sm font-medium mb-2 text-[var(--text-secondary)]">LM Studio</h3>
              <label className="block text-xs mb-1">Base URL</label>
              <div className="flex gap-2">
                <input
                  className="flex-1 bg-[var(--bg-tertiary)] border border-[var(--border)] rounded px-2 py-1 text-sm"
                  value={String(settings.lmstudio_base_url || '')}
                  onChange={(e) => setSettings({ ...settings, lmstudio_base_url: e.target.value })}
                  onBlur={(e) => { save('lmstudio_base_url', e.target.value); testConnection() }}
                />
                <span className={`w-3 h-3 rounded-full self-center ${
                  providerStatus === 'healthy' ? 'bg-[var(--success)]' :
                  providerStatus === 'degraded' ? 'bg-yellow-500' :
                  providerStatus === 'unknown' ? 'bg-gray-500' : 'bg-[var(--error)]'
                }`} />
              </div>
              <Button loading={testing} className="mt-2" onClick={testConnection}>Test Connection</Button>
              {testResult && (
                <p className={`text-xs mt-1 ${testResult.ok ? 'text-[var(--success)]' : 'text-[var(--error)]'}`}>
                  {testResult.ok ? '✓' : '✕'} {testResult.msg}
                </p>
              )}
            </section>

            <section>
              <h3 className="text-sm font-medium mb-2 text-[var(--text-secondary)]">Per-Agent Models</h3>
              {AGENTS.map(({ key, label, recommended }) => (
                <div key={key} className="flex items-center gap-2 mb-2">
                  <label className="w-28 text-xs">{label}</label>
                  <select
                    className="flex-1 bg-[var(--bg-tertiary)] border border-[var(--border)] rounded px-2 py-1 text-sm"
                    value={String(settings[key] || '')}
                    onChange={(e) => save(key, e.target.value)}
                  >
                    <option value={recommended}>★ {recommended}</option>
                    {models.map((m) => <option key={m} value={m}>{m}</option>)}
                  </select>
                </div>
              ))}
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
                await save('lmstudio_base_url', 'http://192.168.128.70:1234/v1')
                showSuccess('Reset to defaults')
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
