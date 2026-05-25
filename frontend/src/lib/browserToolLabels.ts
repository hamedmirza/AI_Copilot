export function browserToolLabel(name: string, args: unknown): string {
  const row = args && typeof args === 'object' ? (args as Record<string, unknown>) : {}
  switch (name) {
    case 'browser_navigate':
      return `Navigate → ${String(row.url || 'URL')}`
    case 'browser_snapshot':
      return 'Snapshot page (accessibility tree + visible text)'
    case 'browser_click':
      return `Click ${String(row.selector || row.ref || 'element')}`
    case 'browser_type':
      return `Type into ${String(row.selector || row.ref || 'element')}`
    case 'browser_screenshot':
      return 'Capture screenshot'
    case 'browser_wait':
      return `Wait ${String(row.ms ?? row.timeout_ms ?? '…')}ms`
    default:
      return name.startsWith('browser_') ? name.replace(/^browser_/, 'Browser: ') : name
  }
}

export function isBrowserTool(name: string): boolean {
  return name.startsWith('browser_')
}

export function screenshotDataUrl(result: unknown): string | null {
  if (!result || typeof result !== 'object') return null
  const dataUrl = (result as Record<string, unknown>).dataUrl
  if (typeof dataUrl !== 'string') return null
  if (!dataUrl.startsWith('data:image')) return null
  if (dataUrl.endsWith('…')) return null
  return dataUrl
}

export function evidenceFilename(screenshotPath: string): string {
  const normalized = screenshotPath.replace(/\\/g, '/')
  const parts = normalized.split('/')
  return parts[parts.length - 1] || normalized
}
