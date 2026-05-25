import { describe, expect, it } from 'vitest'
import { isRightPanelTabMounted, rightPanelPanelClass } from '@/lib/rightPanelLayout'

describe('rightPanelLayout', () => {
  it('uses hidden class for inactive tabs while keeping mount semantics', () => {
    expect(rightPanelPanelClass(true)).toContain('flex')
    expect(rightPanelPanelClass(false)).toBe('hidden')
  })

  it('only mounts tabs present in the configured tab list', () => {
    expect(isRightPanelTabMounted('chat', ['chat', 'runs'])).toBe(true)
    expect(isRightPanelTabMounted('agents', ['chat', 'runs'])).toBe(false)
    expect(isRightPanelTabMounted('agents', ['chat', 'agents', 'runs'])).toBe(true)
  })
})
