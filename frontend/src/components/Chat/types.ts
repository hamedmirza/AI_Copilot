import { parseApiDateTime } from '@/lib/datetime'
import type {
  ChatMessage,
  ChatMode,
  ChatModelSelectionMode,
  ChatSession,
  ChatToolCall,
} from '@/store'

type JsonRecord = Record<string, unknown>

export const CHAT_MODE_OPTIONS: Array<{ value: ChatMode; label: string }> = [
  { value: 'general', label: 'General' },
  { value: 'agent', label: 'Agent' },
  { value: 'planner', label: 'Planner' },
  { value: 'debugger', label: 'Debugger' },
  { value: 'architect', label: 'Architect' },
]

export const STAGES = ['planner', 'architect', 'ui_designer', 'coder', 'reviewer', 'tester', 'supervisor']

export function normalizeChatMode(value: unknown): ChatMode {
  const normalized = String(value || 'general').toLowerCase()
  if (normalized === 'agent' || normalized === 'planner' || normalized === 'debugger' || normalized === 'architect') {
    return normalized
  }
  return 'general'
}

export function normalizeModelOverride(value: unknown): string | null {
  const normalized = String(value || '').trim()
  if (!normalized || normalized.toLowerCase() === 'auto') {
    return null
  }
  return normalized
}

export function normalizeModelSelectionMode(value: unknown): ChatModelSelectionMode {
  return normalizeModelOverride(value) ? 'manual' : 'auto'
}

export function normalizeSessionNothink(value: unknown): boolean | null {
  if (value === null || value === undefined) return null
  if (typeof value === 'boolean') return value
  if (typeof value === 'string') {
    const normalized = value.trim().toLowerCase()
    if (normalized === 'true' || normalized === '1') return true
    if (normalized === 'false' || normalized === '0') return false
  }
  return null
}

export function resolveEffectiveNothink(
  sessionNothink: boolean | null | undefined,
  globalDefault: unknown,
): boolean {
  const normalized = normalizeSessionNothink(sessionNothink)
  if (normalized !== null) return normalized
  if (typeof globalDefault === 'boolean') return globalDefault
  if (typeof globalDefault === 'string') {
    const value = globalDefault.trim().toLowerCase()
    if (value === 'false' || value === '0') return false
    if (value === 'true' || value === '1') return true
  }
  return true
}

export function parseUnknownObject(value: unknown): JsonRecord | undefined {
  if (!value) return undefined
  if (typeof value === 'string') {
    try {
      return JSON.parse(value) as JsonRecord
    } catch {
      return undefined
    }
  }
  if (typeof value === 'object') return value as JsonRecord
  return undefined
}

export function parseUnknownArray(value: unknown): unknown[] {
  if (!value) return []
  if (Array.isArray(value)) return value
  if (typeof value === 'string') {
    try {
      const parsed = JSON.parse(value)
      return Array.isArray(parsed) ? parsed : []
    } catch {
      return []
    }
  }
  return []
}

export function toChatSession(value: JsonRecord): ChatSession {
  return {
    id: String(value.id || crypto.randomUUID()),
    project_id: String(value.project_id || ''),
    title: String(value.title || 'New chat'),
    mode: normalizeChatMode(value.mode),
    model_override: normalizeModelOverride(value.model_override),
    nothink: normalizeSessionNothink(value.nothink),
    message_count: Number(value.message_count || 0),
    last_message_preview: value.last_message_preview ? String(value.last_message_preview) : null,
    last_message_at: value.last_message_at ? String(value.last_message_at) : null,
    created_at: value.created_at ? String(value.created_at) : undefined,
    updated_at: value.updated_at ? String(value.updated_at) : undefined,
  }
}

export function toChatToolCall(value: JsonRecord, fallbackId: string = crypto.randomUUID()): ChatToolCall {
  return {
    id: String(value.id || value.tool_call_id || fallbackId),
    name: String(value.name || value.tool_name || 'tool'),
    args: value.args ?? value.input ?? {},
    result: value.result ?? value.output,
    status: value.status === 'error' ? 'error' : value.status === 'completed' ? 'completed' : 'pending',
    startedAt: value.startedAt ? String(value.startedAt) : value.started_at ? String(value.started_at) : undefined,
    completedAt: value.completedAt ? String(value.completedAt) : value.completed_at ? String(value.completed_at) : undefined,
    error: value.error ? String(value.error) : undefined,
  }
}

export function toChatMessage(value: JsonRecord): ChatMessage {
  const metadata = parseUnknownObject(value.metadata ?? value.metadata_json)
  const toolCalls = parseUnknownArray(value.tool_calls ?? value.tool_calls_json)
    .map((item, index) => toChatToolCall((item || {}) as JsonRecord, `${String(value.id || 'message')}-${index}`))

  return {
    id: String(value.id || crypto.randomUUID()),
    session_id: value.session_id ? String(value.session_id) : undefined,
    role: String(value.role || 'assistant') as ChatMessage['role'],
    content: String(value.content || ''),
    tool_call_id: value.tool_call_id ? String(value.tool_call_id) : undefined,
    created_at: value.created_at ? String(value.created_at) : undefined,
    metadata,
    tool_calls: toolCalls.length > 0 ? toolCalls : undefined,
  }
}

function parseToolOutput(content: string): unknown {
  if (!content.trim()) return ''
  try {
    return JSON.parse(content) as unknown
  } catch {
    return content
  }
}

/** Hide raw tool rows; merge tool output into assistant tool cards. */
export function prepareMessagesForDisplay(messages: ChatMessage[]): ChatMessage[] {
  const toolOutputs = new Map<string, { result: unknown; error: boolean }>()
  for (const message of messages) {
    if (message.role !== 'tool') continue
    const callId = message.tool_call_id || ''
    if (!callId) continue
    toolOutputs.set(callId, {
      result: parseToolOutput(message.content),
      error: Boolean(message.metadata?.error),
    })
  }

  const display: ChatMessage[] = []
  for (let index = 0; index < messages.length; index += 1) {
    const message = messages[index]
    if (message.role === 'tool' || message.role === 'system') continue

    if (message.role === 'assistant' && message.tool_calls?.length) {
      const mergedToolCalls = message.tool_calls.map((toolCall) => {
        const output = toolOutputs.get(toolCall.id)
        if (!output) return toolCall
        return {
          ...toolCall,
          result: output.result,
          status: output.error ? 'error' as const : 'completed' as const,
          error: output.error ? summarizeToolResult(output.result) : toolCall.error,
        }
      })
      const hasLaterAnswer = messages
        .slice(index + 1)
        .some((later) => later.role === 'assistant' && later.content.trim())

      if (!message.content.trim() && hasLaterAnswer && !message.pending) {
        continue
      }

      display.push({ ...message, tool_calls: mergedToolCalls })
      continue
    }

    display.push(message)
  }
  return display
}

export function formatChatTimestamp(value?: string): string {
  const date = parseApiDateTime(value)
  if (!date) return ''
  return date.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
}

export function formatAnswerDuration(ms: number): string {
  const safe = Math.max(0, Math.round(ms))
  if (safe < 10_000) {
    const seconds = safe / 1000
    return seconds < 10 ? `${seconds.toFixed(1)}s` : `${Math.round(seconds)}s`
  }
  const totalSec = Math.round(safe / 1000)
  if (totalSec < 60) return `${totalSec}s`
  const minutes = Math.floor(totalSec / 60)
  const remainder = totalSec % 60
  return remainder > 0 ? `${minutes}m ${remainder}s` : `${minutes}m`
}

export function resolveAnswerDurationMs(message: ChatMessage, now = Date.now()): number | null {
  if (message.role !== 'assistant') return null

  const persisted = message.metadata?.duration_ms
  if (persisted != null && !message.pending) {
    const parsed = Number(persisted)
    if (!Number.isNaN(parsed) && parsed >= 0) return parsed
  }

  const started = parseApiDateTime(String(message.metadata?.answer_started_at || ''))
  if (!started) return null
  const completed = parseApiDateTime(String(message.metadata?.answer_completed_at || ''))
  if (completed) {
    return Math.max(0, completed.getTime() - started.getTime())
  }
  if (message.pending) {
    return Math.max(0, now - started.getTime())
  }
  return null
}

export function buildAnswerTimingMetadata(
  existing: Record<string, unknown> | undefined,
  override: Record<string, unknown> | undefined,
): Record<string, unknown> {
  const merged = { ...(existing || {}), ...(override || {}) }
  const startedAt = String(merged.answer_started_at || '')
  const started = parseApiDateTime(startedAt)
  const completedAt = new Date().toISOString()
  const durationMs = merged.duration_ms != null
    ? Number(merged.duration_ms)
    : started
      ? Date.now() - started.getTime()
      : null

  return {
    ...merged,
    answer_started_at: startedAt || completedAt,
    answer_completed_at: completedAt,
    ...(durationMs != null && !Number.isNaN(durationMs) && durationMs >= 0
      ? { duration_ms: Math.round(durationMs) }
      : {}),
  }
}

const relativeTimeFormatter = new Intl.RelativeTimeFormat(undefined, { numeric: 'auto' })

export function formatRelativeChatTime(value?: string | null): string {
  const timestamp = parseApiDateTime(value)
  if (!timestamp) return ''

  const diffMs = timestamp.getTime() - Date.now()
  const minute = 60 * 1000
  const hour = 60 * minute
  const day = 24 * hour
  const week = 7 * day

  if (Math.abs(diffMs) < hour) {
    return relativeTimeFormatter.format(Math.round(diffMs / minute), 'minute')
  }
  if (Math.abs(diffMs) < day) {
    return relativeTimeFormatter.format(Math.round(diffMs / hour), 'hour')
  }
  if (Math.abs(diffMs) < week) {
    return relativeTimeFormatter.format(Math.round(diffMs / day), 'day')
  }
  return timestamp.toLocaleDateString([], { month: 'short', day: 'numeric' })
}

export function summarizeToolResult(value: unknown, maxLength = 4000): string {
  if (value === null || value === undefined) return ''
  let text: string
  if (typeof value === 'string') {
    text = value
  } else {
    try {
      text = JSON.stringify(value, null, 2)
    } catch {
      text = String(value)
    }
  }
  if (text.length <= maxLength) return text
  return `${text.slice(0, maxLength)}\n… (${text.length - maxLength} more characters)`
}
