interface PackageJsonLike {
  name?: string
  scripts?: Record<string, string>
  workspaces?: string[] | { packages?: string[] }
}

const PORT_PATTERNS = [
  /--port[=\s]+(\d+)/i,
  /-p\s+(\d+)/,
  /:(\d{4,5})\b/,
  /localhost:(\d{4,5})/i,
  /127\.0\.0\.1:(\d{4,5})/,
]

const COMMON_PORT_HINTS = [
  { matcher: /\bnext dev\b/i, port: 3000 },
  { matcher: /\breact-scripts start\b/i, port: 3000 },
  { matcher: /\bnuxt\b/i, port: 3000 },
  { matcher: /\bvite\b/i, port: 5173 },
]

const DEFAULT_PORTS = [5173, 3000, 8080, 4173, 5174]

function parsePortHint(script: string): number | null {
  for (const pattern of PORT_PATTERNS) {
    const match = script.match(pattern)
    if (match?.[1]) {
      const port = Number(match[1])
      if (port > 0 && port < 65536) return port
    }
  }

  for (const hint of COMMON_PORT_HINTS) {
    if (hint.matcher.test(script)) {
      return hint.port
    }
  }

  return null
}

function pickScript(scripts: Record<string, string> | undefined): string | null {
  if (!scripts) return null
  for (const name of ['dev', 'start', 'serve', 'preview']) {
    const script = scripts[name]
    if (script) return script
  }
  return Object.values(scripts)[0] || null
}

export function suggestUrlFromPackageJson(content: string): string | null {
  try {
    const parsed = JSON.parse(content) as PackageJsonLike
    const script = pickScript(parsed.scripts)
    if (!script) return null
    const hintedPort = parsePortHint(script)
    if (hintedPort) {
      return `http://localhost:${hintedPort}`
    }
    if (parsed.workspaces) {
      return 'http://localhost:3000'
    }
    if (parsed.scripts?.dev || parsed.scripts?.start) {
      return `http://localhost:${DEFAULT_PORTS[0]}`
    }
  } catch {
    return null
  }
  return null
}

export function suggestDevServerUrl(entries: Array<{ path: string; content: string }>): string | null {
  const ranked = [...entries].sort((left, right) => {
    const leftScore = left.path.includes('/frontend/') || left.path.startsWith('frontend/') ? 0 : 1
    const rightScore = right.path.includes('/frontend/') || right.path.startsWith('frontend/') ? 0 : 1
    return leftScore - rightScore
  })

  for (const entry of ranked) {
    const suggested = suggestUrlFromPackageJson(entry.content)
    if (suggested) return suggested
  }

  return null
}
