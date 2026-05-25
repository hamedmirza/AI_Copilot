import type { AgentAction, AgentResultPayload } from '@/lib/browserAgentMessages'

export type BrowserAgentExecutor = (
  action: AgentAction,
  args: Record<string, unknown>,
  requestId: string,
) => Promise<AgentResultPayload>

let executor: BrowserAgentExecutor | null = null

export function registerBrowserAgentExecutor(fn: BrowserAgentExecutor | null): void {
  executor = fn
}

export async function executeBrowserAgentCommand(
  action: AgentAction,
  args: Record<string, unknown>,
  requestId: string,
): Promise<AgentResultPayload> {
  if (!executor) {
    return { requestId, ok: false, error: 'Browser panel not ready' }
  }
  return executor(action, args, requestId)
}
