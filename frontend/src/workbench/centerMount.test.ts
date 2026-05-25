import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

const srcRoot = join(dirname(fileURLToPath(import.meta.url)), '..')
const appTsx = readFileSync(join(srcRoot, 'App.tsx'), 'utf-8')
const builtinsTsx = readFileSync(join(srcRoot, 'workbench', 'builtins.tsx'), 'utf-8')

describe('center workbench mount', () => {
  it('App mounts center panels via getContribution', () => {
    expect(appTsx).toMatch(/getContribution\(['"]center['"]/)
    expect(appTsx).not.toMatch(/activeCenterView === 'browser' && BrowserComponent/)
  })

  it('builtins registers kanban and reporting as center panels', () => {
    expect(builtinsTsx).toMatch(/id:\s*['"]kanban['"][\s\S]*zone:\s*['"]center['"]|zone:\s*['"]center['"][\s\S]*id:\s*['"]kanban['"]/)
    expect(builtinsTsx).toMatch(/id:\s*['"]reporting['"][\s\S]*zone:\s*['"]center['"]|zone:\s*['"]center['"][\s\S]*id:\s*['"]reporting['"]/)
  })
})
