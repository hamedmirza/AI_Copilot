import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { RunActivityFeed } from './RunActivityFeed'

describe('RunActivityFeed', () => {
  let container: HTMLDivElement
  let root: Root

  beforeEach(() => {
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)
  })

  afterEach(() => {
    act(() => root.unmount())
    container.remove()
  })

  it('renders pipeline_tool_start as human-readable line', async () => {
    await act(async () => {
      root.render(
        <RunActivityFeed
          status="running"
          events={[
            {
              type: 'pipeline_tool_start',
              message: '',
              payload: { tool: 'read_file', path: 'backend/app/main.py' },
              created_at: new Date().toISOString(),
            },
          ]}
        />,
      )
    })
    expect(container.textContent).toContain('read_file')
    expect(container.textContent).toContain('backend/app/main.py')
  })

  it('shows Still working when running and silent', async () => {
    await act(async () => {
      root.render(
        <RunActivityFeed
          status="running"
          events={[]}
        />,
      )
    })
    expect(container.textContent).toContain('Still working')
  })
})
