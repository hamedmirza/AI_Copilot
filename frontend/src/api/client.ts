const API_BASE = ''
const TOKEN_KEY = 'ai-copilot-token'

export function getToken(): string {
  return localStorage.getItem(TOKEN_KEY) || 'dev-token'
}

export function setToken(token: string) {
  localStorage.setItem(TOKEN_KEY, token)
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    'X-Api-Token': getToken(),
    ...(options.headers as Record<string, string> || {}),
  }
  const res = await fetch(`${API_BASE}${path}`, { ...options, headers })
  if (!res.ok) {
    let message = `Request failed (${res.status})`
    try {
      const body = await res.json()
      message = body.detail || body.message || message
    } catch { /* ignore */ }
    throw new Error(message)
  }
  if (res.status === 204) return undefined as T
  const contentType = res.headers.get('content-type') || ''
  if (!contentType.includes('application/json')) {
    return undefined as T
  }
  return res.json()
}

function encodeFilePath(path: string): string {
  return path.split('/').map((segment) => encodeURIComponent(segment)).join('/')
}

function buildQuery(params: Record<string, string | number | undefined | null>): string {
  const query = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') {
      query.set(key, String(value))
    }
  })
  const result = query.toString()
  return result ? `?${result}` : ''
}

export const api = {
  health: () => request<{
    status: string
    version: string
    uptime_seconds?: number
    worker_count?: number
    ws_connections?: number
  }>('/api/health'),
  providerHealth: () =>
    request<{
      active_provider: 'lmstudio' | 'ollama'
      lmstudio: string
      ollama: string
      model_count: number
      lmstudio_model_count?: number
      ollama_model_count?: number
      lmstudio_models?: string[]
      ollama_models?: string[]
      error?: string
      lmstudio_error?: string
      ollama_error?: string
      suggested_ollama_base_url?: string | null
      resources_pressure?: string
      loaded_size_gb?: number
      recommendations?: Record<string, string>
      models?: string[]
    }>('/api/health/provider'),
  settings: {
    get: () => request<Record<string, unknown>>('/api/settings'),
    update: (data: Record<string, unknown>) =>
      request('/api/settings', { method: 'PUT', body: JSON.stringify(data) }),
    reset: () => request<Record<string, unknown>>('/api/settings/reset', { method: 'POST' }),
    models: (provider?: 'lmstudio' | 'ollama') =>
      request<{
        provider?: string
        models: string[]
        catalog?: Array<{
          id: string
          state: string
          loaded: boolean
          size_gb: number
          tool_use: boolean
          params: string
          quantization: string
        }>
        recommendations?: Record<string, string>
        resources?: {
          pressure: 'ok' | 'elevated' | 'high'
          loaded_count: number
          loaded_size_gb: number
        }
      }>(`/api/settings/models${provider ? `?provider=${provider}` : ''}`),
  },
  onboarding: {
    status: () => request<{ complete: boolean; project_count: number }>('/api/onboarding/status'),
  },
  dialog: {
    pickDirectory: (prompt?: string) =>
      request<{ cancelled: boolean; path: string | null; error?: string | null }>(
        '/api/dialog/pick-directory',
        {
          method: 'POST',
          body: JSON.stringify({ prompt }),
        },
      ),
  },
  projects: {
    list: () => request<Array<Record<string, unknown>>>('/api/projects'),
    create: (data: Record<string, unknown>) =>
      request('/api/projects', { method: 'POST', body: JSON.stringify(data) }),
    get: (id: string) => request(`/api/projects/${id}`),
    update: (id: string, data: Record<string, unknown>) =>
      request(`/api/projects/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
    delete: (id: string) => request(`/api/projects/${id}`, { method: 'DELETE' }),
    tree: (id: string) => request<{ items: Array<{ path: string; type: string; size: number }> }>(`/api/projects/${id}/tree`),
    runs: (id: string) => request(`/api/projects/${id}/runs`),
    kanban: (id: string) => request<Record<string, unknown>>(`/api/projects/${id}/kanban`),
    lessons: (id: string) => request(`/api/projects/${id}/lessons`),
    improvements: (id: string, params?: { status?: string; scope?: string }) =>
      request(
        `/api/projects/${id}/improvements${buildQuery({
          status: params?.status,
          scope: params?.scope,
        })}`,
      ),
    createLessonFromRun: (projectId: string, runId: string) =>
      request(`/api/projects/${projectId}/lessons/from-run/${runId}`, { method: 'POST' }),
  },
  files: {
    read: (projectId: string, path: string) =>
      request<{ content: string; line_count: number }>(
        `/api/projects/${projectId}/files/${encodeFilePath(path)}`,
      ),
    write: (projectId: string, path: string, content: string) =>
      request(`/api/projects/${projectId}/files/${encodeFilePath(path)}`, {
        method: 'PUT',
        body: JSON.stringify({ content }),
      }),
    create: (projectId: string, path: string, content = '', isDirectory = false) =>
      request(`/api/projects/${projectId}/files`, {
        method: 'POST',
        body: JSON.stringify({ path, content, is_directory: isDirectory }),
      }),
    delete: (projectId: string, path: string) =>
      request(`/api/projects/${projectId}/files/${encodeFilePath(path)}`, { method: 'DELETE' }),
    rename: (projectId: string, path: string, newPath: string) =>
      request(`/api/projects/${projectId}/files/${encodeFilePath(path)}/rename`, {
        method: 'POST',
        body: JSON.stringify({ new_path: newPath }),
      }),
  },
  tasks: {
    create: (data: Record<string, unknown>) =>
      request('/api/tasks', { method: 'POST', body: JSON.stringify(data) }),
  },
  chat: {
    modes: () => request<Array<Record<string, unknown>>>('/api/chat/modes'),
    sessions: {
      list: (projectId: string, q?: string) =>
        request<Array<Record<string, unknown>>>(`/api/chat/sessions${buildQuery({ project_id: projectId, q })}`),
      create: (data: Record<string, unknown>) =>
        request<Record<string, unknown>>('/api/chat/sessions', { method: 'POST', body: JSON.stringify(data) }),
      get: (id: string) =>
        request<Record<string, unknown>>(`/api/chat/sessions/${id}`),
      update: (id: string, data: Record<string, unknown>) =>
        request<Record<string, unknown>>(`/api/chat/sessions/${id}`, {
          method: 'PUT',
          body: JSON.stringify(data),
        }),
      delete: (id: string) =>
        request<{ ok?: boolean }>(`/api/chat/sessions/${id}`, { method: 'DELETE' }),
      cancel: (id: string) =>
        request<{ ok: boolean; cancelled: boolean }>(
          `/api/chat/sessions/${id}/cancel`,
          { method: 'POST' },
        ),
    },
    messages: {
      list: (sessionId: string) =>
        request<{ items: Array<Record<string, unknown>>; total: number }>(`/api/chat/sessions/${sessionId}/messages`),
      send: (sessionId: string, data: Record<string, unknown>) =>
        request<Record<string, unknown>>(`/api/chat/sessions/${sessionId}/messages`, {
          method: 'POST',
          body: JSON.stringify(data),
        }),
    },
    spawnTask: (sessionId: string, data: Record<string, unknown>) =>
      request<Record<string, unknown>>(`/api/chat/sessions/${sessionId}/spawn-task`, {
        method: 'POST',
        body: JSON.stringify(data),
      }),
  },
  runs: {
    get: (id: string) => request(`/api/runs/${id}`),
    events: (id: string) => request(`/api/runs/${id}/events`),
    artifacts: (id: string) => request(`/api/runs/${id}/artifacts`),
    postmortem: (id: string) => request(`/api/runs/${id}/postmortem`),
    readWorkspaceFile: (id: string, path: string) =>
      request<{ content: string; line_count: number }>(
        `/api/runs/${id}/files/${encodeFilePath(path)}`,
      ),
    failureSummary: (projectId?: string) =>
      request(`/api/runs/failure-summary${buildQuery({ project_id: projectId })}`),
    cleanupFailed: (projectId?: string) =>
      request<{
        deleted_count: number
        deleted_run_ids: string[]
        workspaces_removed: number
        snapshots_removed: number
        orphan_workspaces_removed: number
        by_project: Record<string, number>
      }>(`/api/runs/cleanup${buildQuery({ project_id: projectId })}`, { method: 'POST' }),
    approve: (id: string, comment = '') =>
      request(`/api/runs/${id}/approve`, { method: 'POST', body: JSON.stringify({ comment }) }),
    reject: (id: string, reason: string) =>
      request(`/api/runs/${id}/reject`, { method: 'POST', body: JSON.stringify({ reason }) }),
    retry: (id: string, body?: { feedback?: string }) =>
      request(`/api/runs/${id}/retry`, {
        method: 'POST',
        body: JSON.stringify(body ?? {}),
      }),
    clarify: (id: string, answer: string) =>
      request<{ ok: boolean; run_id: string; status: string; current_stage: string }>(`/api/runs/${id}/clarify`, {
        method: 'POST',
        body: JSON.stringify({ answer }),
      }),
    thread: (id: string) => request<Array<Record<string, unknown>>>(`/api/runs/${id}/thread`),
    resume: (id: string) =>
      request<{ ok: boolean; run_id: string; status: string }>(`/api/runs/${id}/resume`, {
        method: 'POST',
      }),
    continueVisual: (id: string) =>
      request<{ ok: boolean; passed: boolean; evidence?: Record<string, unknown>; status?: string }>(
        `/api/runs/${id}/continue-visual`,
        { method: 'POST' },
      ),
    evidenceUrl: (runId: string, filename: string) => {
      const sep = '?'
      return `/api/runs/${runId}/evidence/${encodeURIComponent(filename)}${sep}token=${encodeURIComponent(getToken())}`
    },
    rollbackWorkspace: (id: string) =>
      request(`/api/runs/${id}/rollback-workspace`, { method: 'POST' }),
    rollbackPromote: (id: string) =>
      request(`/api/runs/${id}/rollback-promote`, { method: 'POST' }),
    deploymentReadiness: (id: string) =>
      request<{
        run_id: string
        status: string
        ready: boolean
        gates: Array<{
          id: string
          label: string
          passed: boolean
          required: boolean
          detail: string
        }>
        changed_files?: string[]
        visual_evidence?: Record<string, unknown> | null
        warnings?: string[]
        mismatch_classes?: string[]
        readiness?: Record<string, unknown>
      }>(`/api/runs/${id}/deployment-readiness`),
  },
  reporting: {
    metrics: (projectId: string) =>
      request<Record<string, unknown>>(`/api/projects/${projectId}/metrics`),
  },
  lessons: {
    promoteGlobal: (lessonId: number) =>
      request(`/api/lessons/${lessonId}/promote-global`, { method: 'POST' }),
  },
  improvements: {
    get: (id: string) => request(`/api/improvements/${id}`),
    exposures: (id: string) => request(`/api/improvements/${id}/exposures`),
    override: (id: string, body: { status: string; scope?: string }) =>
      request(`/api/improvements/${id}/override`, {
        method: 'POST',
        body: JSON.stringify(body),
      }),
  },
  skills: {
    listGlobal: () => request('/api/skills/global'),
    deprecate: (skillId: string) =>
      request(`/api/skills/global/${skillId}/deprecate`, { method: 'POST' }),
  },
  mcp: {
    servers: {
      list: () => request<Array<Record<string, unknown>>>('/api/mcp/servers'),
      create: (data: Record<string, unknown>) =>
        request<Record<string, unknown>>('/api/mcp/servers', {
          method: 'POST',
          body: JSON.stringify(data),
        }),
      update: (id: string, data: Record<string, unknown>) =>
        request<Record<string, unknown>>(`/api/mcp/servers/${id}`, {
          method: 'PUT',
          body: JSON.stringify(data),
        }),
      delete: (id: string) =>
        request<{ ok?: boolean }>(`/api/mcp/servers/${id}`, { method: 'DELETE' }),
      test: (id: string) =>
        request<Record<string, unknown>>(`/api/mcp/servers/${id}/test`, { method: 'POST' }),
      export: () =>
        request<{ servers: Array<Record<string, unknown>> }>('/api/mcp/servers/export'),
      import: (data: Record<string, unknown>) =>
        request<{ ok: boolean; count: number; servers: Array<Record<string, unknown>> }>('/api/mcp/servers/import', {
          method: 'POST',
          body: JSON.stringify(data),
        }),
    },
  },
  git: {
    status: (projectId: string) => request(`/api/projects/${projectId}/git/status`),
    stage: (projectId: string, paths: string[]) =>
      request(`/api/projects/${projectId}/git/stage`, { method: 'POST', body: JSON.stringify({ paths }) }),
    unstage: (projectId: string, paths: string[]) =>
      request(`/api/projects/${projectId}/git/unstage`, { method: 'POST', body: JSON.stringify({ paths }) }),
    commit: (projectId: string, message: string) =>
      request(`/api/projects/${projectId}/git/commit`, { method: 'POST', body: JSON.stringify({ message }) }),
    log: (projectId: string) => request(`/api/projects/${projectId}/git/log`),
    branches: (projectId: string) => request<{ current: string; branches: string[] }>(`/api/projects/${projectId}/git/branches`),
    checkout: (projectId: string, branch: string) =>
      request(`/api/projects/${projectId}/git/checkout`, { method: 'POST', body: JSON.stringify({ branch }) }),
    diff: (projectId: string, path: string) =>
      request<{ diff: string; original: string; path: string }>(`/api/projects/${projectId}/git/diff/${path}`),
    push: (projectId: string) => request(`/api/projects/${projectId}/git/push`, { method: 'POST' }),
    pull: (projectId: string) => request(`/api/projects/${projectId}/git/pull`, { method: 'POST' }),
  },
  logs: (params?: { limit?: number; level?: string; run_id?: string }) => {
    const q = new URLSearchParams()
    if (params?.limit) q.set('limit', String(params.limit))
    if (params?.level) q.set('level', params.level)
    if (params?.run_id) q.set('run_id', params.run_id)
    return request<{ lines: Array<Record<string, unknown>> }>(`/api/logs?${q}`)
  },
}

export function wsUrl(path: string): string {
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const host = window.location.host
  const sep = path.includes('?') ? '&' : '?'
  return `${proto}//${host}${path}${sep}token=${encodeURIComponent(getToken())}`
}
