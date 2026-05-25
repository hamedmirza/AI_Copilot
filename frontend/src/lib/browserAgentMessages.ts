/** postMessage protocol for agent browser automation (parent ↔ copilot-picker-bridge.js). */

export const AGENT_MSG = {
  COMMAND: 'COPILOT_AGENT_COMMAND',
  RESULT: 'COPILOT_AGENT_RESULT',
  NAVIGATE: 'COPILOT_AGENT_NAVIGATE',
} as const

export type AgentAction =
  | 'snapshot'
  | 'click'
  | 'type'
  | 'wait_for'
  | 'screenshot'
  | 'scroll_into_view'
  | 'get_console_errors'

export interface AgentCommandPayload {
  requestId: string
  action: AgentAction
  selector?: string
  text?: string
  clear?: boolean
  timeoutMs?: number
  url?: string
}

export interface AgentResultPayload {
  requestId: string
  ok: boolean
  result?: Record<string, unknown>
  error?: string
}

export interface BrowserWsCommand {
  type: 'browser_command'
  request_id: string
  action: string
  args: Record<string, unknown>
  run_id?: string
  highlight?: boolean
}

export interface BrowserWsResult {
  type: 'browser_result'
  request_id: string
  ok: boolean
  result?: Record<string, unknown>
  error?: string
}

export interface BrowserWsReady {
  type: 'browser_ready'
  project_id?: string
}
