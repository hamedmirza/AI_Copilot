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
  return res.json()
}

export const api = {
  health: () => request<{ status: string; version: string }>('/api/health'),
  providerHealth: () => request<{ lmstudio: string; model_count: number; error?: string }>('/api/health/provider'),
  settings: {
    get: () => request<Record<string, unknown>>('/api/settings'),
    update: (data: Record<string, unknown>) =>
      request('/api/settings', { method: 'PUT', body: JSON.stringify(data) }),
    models: () => request<{ models: string[] }>('/api/settings/models'),
  },
  onboarding: {
    status: () => request<{ complete: boolean; project_count: number }>('/api/onboarding/status'),
  },
  dialog: {
    pickDirectory: (prompt?: string) =>
      request<{ cancelled: boolean; path: string | null }>('/api/dialog/pick-directory', {
        method: 'POST',
        body: JSON.stringify({ prompt }),
      }),
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
  },
  files: {
    read: (projectId: string, path: string) =>
      request<{ content: string; line_count: number }>(`/api/projects/${projectId}/files/${path}`),
    write: (projectId: string, path: string, content: string) =>
      request(`/api/projects/${projectId}/files/${path}`, {
        method: 'PUT',
        body: JSON.stringify({ content }),
      }),
    create: (projectId: string, path: string, content = '', isDirectory = false) =>
      request(`/api/projects/${projectId}/files`, {
        method: 'POST',
        body: JSON.stringify({ path, content, is_directory: isDirectory }),
      }),
    delete: (projectId: string, path: string) =>
      request(`/api/projects/${projectId}/files/${path}`, { method: 'DELETE' }),
    rename: (projectId: string, path: string, newPath: string) =>
      request(`/api/projects/${projectId}/files/${path}/rename`, {
        method: 'POST',
        body: JSON.stringify({ new_path: newPath }),
      }),
  },
  tasks: {
    create: (data: Record<string, unknown>) =>
      request('/api/tasks', { method: 'POST', body: JSON.stringify(data) }),
  },
  runs: {
    get: (id: string) => request(`/api/runs/${id}`),
    events: (id: string) => request(`/api/runs/${id}/events`),
    artifacts: (id: string) => request(`/api/runs/${id}/artifacts`),
    approve: (id: string, comment = '') =>
      request(`/api/runs/${id}/approve`, { method: 'POST', body: JSON.stringify({ comment }) }),
    reject: (id: string, reason: string) =>
      request(`/api/runs/${id}/reject`, { method: 'POST', body: JSON.stringify({ reason }) }),
    retry: (id: string) => request(`/api/runs/${id}/retry`, { method: 'POST' }),
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
