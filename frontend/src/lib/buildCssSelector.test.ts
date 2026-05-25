/**
 * @vitest-environment jsdom
 */
import { describe, expect, it } from 'vitest'
import { buildCssSelector } from './buildCssSelector'

describe('buildCssSelector', () => {
  it('prefers unique id', () => {
    document.body.innerHTML = '<div id="root"><button id="save">Save</button></div>'
    const btn = document.getElementById('save')!
    expect(buildCssSelector(btn)).toBe('#save')
  })

  it('uses nth-child when siblings share tag', () => {
    document.body.innerHTML = '<div><span>a</span><span>b</span></div>'
    const spans = document.querySelectorAll('span')
    const sel = buildCssSelector(spans[1] as Element)
    expect(sel).toContain('nth-child')
  })

  it('prefers data-testid when tag alone is ambiguous', () => {
    document.body.innerHTML = '<button>Cancel</button><button data-testid="submit-btn">Go</button>'
    const btn = document.querySelector('[data-testid="submit-btn"]')!
    expect(buildCssSelector(btn)).toContain('data-testid')
  })
})
