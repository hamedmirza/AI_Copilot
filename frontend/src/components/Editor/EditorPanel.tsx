import { useCallback, useEffect, useRef, useState } from 'react'
import Editor from '@monaco-editor/react'
import type { editor as MonacoEditor } from 'monaco-editor'
import { api } from '@/api/client'
import { useEditorStore, useProjectStore, useSettingsStore } from '@/store'
import { showError, showSuccess } from '@/lib/toast'
import { EmptyState, Button } from '@/components/ui/primitives'

export function EditorPanel() {
  const tabs = useEditorStore((s) => s.tabs)
  const activeTab = useEditorStore((s) => s.activeTab)
  const updateTabContent = useEditorStore((s) => s.updateTabContent)
  const markClean = useEditorStore((s) => s.markClean)
  const closeTab = useEditorStore((s) => s.closeTab)
  const setActiveTab = useEditorStore((s) => s.setActiveTab)
  const promoteTab = useEditorStore((s) => s.promoteTab)
  const setSelection = useEditorStore((s) => s.setSelection)
  const projectId = useProjectStore((s) => s.currentProjectId)
  const settings = useSettingsStore((s) => s.settings)
  const [saving, setSaving] = useState<string | null>(null)
  const [confirmClose, setConfirmClose] = useState<string | null>(null)
  const autoSaveTimer = useRef<number | null>(null)
  const editorRef = useRef<MonacoEditor.IStandaloneCodeEditor | null>(null)

  const current = tabs.find((t) => t.path === activeTab)

  const saveFile = useCallback(async (path: string) => {
    if (!projectId) return
    const tab = tabs.find((t) => t.path === path)
    if (!tab) return
    setSaving(path)
    try {
      await api.files.write(projectId, path, tab.content)
      markClean(path)
      showSuccess(`Saved ${path.split('/').pop()}`)
    } catch (e) {
      showError(e)
    } finally {
      setSaving(null)
    }
  }, [projectId, tabs, markClean])

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 's') {
        e.preventDefault()
        if (activeTab) saveFile(activeTab)
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [activeTab, saveFile])

  useEffect(() => {
    if (!settings.editor_auto_save || !activeTab || !current?.dirty) return
    const delay = Number(settings.editor_auto_save_delay_ms) || 2000
    autoSaveTimer.current = window.setTimeout(() => saveFile(activeTab), delay)
    return () => { if (autoSaveTimer.current) clearTimeout(autoSaveTimer.current) }
  }, [current?.content, settings.editor_auto_save, activeTab, saveFile, current?.dirty])

  const handleClose = (path: string) => {
    const tab = tabs.find((t) => t.path === path)
    if (tab?.dirty) {
      setConfirmClose(path)
    } else {
      closeTab(path)
    }
  }

  useEffect(() => {
    if (!current) {
      setSelection(null)
      return
    }
    const editor = editorRef.current
    if (!editor) return
    const selection = editor.getSelection()
    if (!selection) return
    const model = editor.getModel()
    const text = model?.getValueInRange(selection) || ''
    setSelection({
      path: current.path,
      text,
      startLineNumber: selection.startLineNumber,
      endLineNumber: selection.endLineNumber,
    })
  }, [current?.path, setSelection])

  if (tabs.length === 0) {
    return <EmptyState title="No files open" description="Open a file from the Explorer to start editing" />
  }

  return (
    <div className="h-full flex flex-col">
      <div className="flex bg-[var(--bg-secondary)] border-b border-[var(--border)] overflow-x-auto">
        {tabs.map((tab) => (
          <div
            key={tab.path}
            className={`flex items-center gap-1 px-3 py-1.5 border-r border-[var(--border)] cursor-pointer text-sm ${
              activeTab === tab.path ? 'bg-[var(--bg-primary)]' : 'hover:bg-[var(--bg-tertiary)]'
            }`}
            onClick={() => setActiveTab(tab.path)}
            onDoubleClick={() => promoteTab(tab.path)}
            title={tab.preview ? 'Preview — double-click to keep open' : undefined}
          >
            {tab.dirty && <span className="w-2 h-2 rounded-full bg-white" />}
            {saving === tab.path && <span className="spinner" />}
            <span className={tab.preview ? 'italic opacity-75' : ''}>
              {tab.path.split('/').pop()}
            </span>
            <button
              className="ml-1 opacity-60 hover:opacity-100"
              onClick={(e) => { e.stopPropagation(); handleClose(tab.path) }}
            >
              ×
            </button>
          </div>
        ))}
      </div>
      {current && (
        <div className="flex-1">
          <Editor
            height="100%"
            language={current.language}
            value={current.content}
            theme="vs-dark"
            options={{
              fontSize: Number(settings.editor_font_size) || 14,
              tabSize: Number(settings.editor_tab_size) || 2,
              minimap: { enabled: false },
              scrollBeyondLastLine: false,
            }}
            onChange={(v) => {
              if (current.preview) promoteTab(current.path)
              updateTabContent(current.path, v || '')
            }}
            onMount={(editor) => {
              editorRef.current = editor
              const syncSelection = () => {
                const selection = editor.getSelection()
                const model = editor.getModel()
                if (!selection || !model) {
                  setSelection(null)
                  return
                }
                setSelection({
                  path: current.path,
                  text: model.getValueInRange(selection),
                  startLineNumber: selection.startLineNumber,
                  endLineNumber: selection.endLineNumber,
                })
              }
              syncSelection()
              editor.onDidChangeCursorSelection(syncSelection)
            }}
          />
        </div>
      )}
      {confirmClose && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-[var(--bg-secondary)] p-4 rounded border border-[var(--border)] max-w-md">
            <p className="mb-4">Save changes to {confirmClose.split('/').pop()} before closing?</p>
            <div className="flex gap-2 justify-end">
              <Button variant="secondary" onClick={() => { closeTab(confirmClose); setConfirmClose(null) }}>Don't Save</Button>
              <Button variant="secondary" onClick={() => setConfirmClose(null)}>Cancel</Button>
              <Button onClick={async () => { await saveFile(confirmClose); closeTab(confirmClose); setConfirmClose(null) }}>Save</Button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
