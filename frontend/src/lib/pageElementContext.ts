import type { PageElementSelection } from '@/store'
import type { PickerElementPayload } from '@/lib/browserPickerMessages'

export interface PageElementContextPayload {
  url: string
  title: string
  selector: string
  tag_name: string
  id?: string
  class_names: string[]
  text_preview: string
  outer_html_snippet: string
  rect: PageElementSelection['rect']
  computed_styles?: Record<string, string>
  captured_at: string
}

const MAX_HTML_CHARS = 800
const MAX_TEXT_CHARS = 200

function trimText(value: string | undefined | null, limit: number): string {
  const normalized = String(value || '').replace(/\s+/g, ' ').trim()
  if (normalized.length <= limit) return normalized
  return `${normalized.slice(0, Math.max(0, limit - 1)).trimEnd()}…`
}

export function formatElementLabel(selection: Pick<PageElementSelection, 'tagName' | 'selector'>): string {
  return `${selection.tagName.toLowerCase()} · ${trimText(selection.selector, 72)}`
}

export function pickerPayloadToSelection(payload: PickerElementPayload): PageElementSelection {
  return {
    url: payload.url,
    title: payload.title,
    selector: payload.selector,
    tagName: payload.tagName,
    id: payload.id,
    classNames: payload.classNames,
    textPreview: trimText(payload.textPreview, MAX_TEXT_CHARS),
    outerHtmlSnippet: trimText(payload.outerHtmlSnippet, MAX_HTML_CHARS),
    rect: payload.rect,
    computedStyles: payload.computedStyles,
    capturedAt: payload.capturedAt,
  }
}

export function elementContextPayload(selection: PageElementSelection): PageElementContextPayload {
  return {
    url: selection.url,
    title: trimText(selection.title, 160),
    selector: trimText(selection.selector, 240),
    tag_name: selection.tagName.toLowerCase(),
    id: selection.id || undefined,
    class_names: selection.classNames.slice(0, 12),
    text_preview: trimText(selection.textPreview, MAX_TEXT_CHARS),
    outer_html_snippet: trimText(selection.outerHtmlSnippet, MAX_HTML_CHARS),
    rect: {
      x: Math.round(selection.rect.x),
      y: Math.round(selection.rect.y),
      width: Math.round(selection.rect.width),
      height: Math.round(selection.rect.height),
    },
    computed_styles: selection.computedStyles
      ? Object.fromEntries(Object.entries(selection.computedStyles).slice(0, 8))
      : undefined,
    captured_at: selection.capturedAt,
  }
}

export function formatElementForChat(selection: PageElementSelection, userNote?: string): string {
  const lines = [
    'Selected page element:',
    `- Page: ${selection.title || selection.url}`,
    `- URL: ${selection.url}`,
    `- Element: <${selection.tagName.toLowerCase()}>`,
    `- Selector: ${selection.selector}`,
    selection.textPreview ? `- Text: "${trimText(selection.textPreview, 140)}"` : '',
    selection.id ? `- Id: ${selection.id}` : '',
    selection.classNames.length ? `- Classes: ${selection.classNames.slice(0, 6).join(', ')}` : '',
    userNote?.trim() ? `\n${userNote.trim()}` : '',
  ].filter(Boolean)
  return lines.join('\n')
}

export function formatElementForAgentTask(selection: PageElementSelection, userIntent?: string): string {
  const intent = trimText(userIntent, 240) || 'Apply a minimal UI fix for the selected element.'
  return [
    `Spot UI change at ${selection.selector} on ${selection.url}`,
    '',
    `User request: ${intent}`,
    `Selector: ${selection.selector}`,
    `Element: <${selection.tagName.toLowerCase()}>`,
    selection.textPreview ? `Text: "${trimText(selection.textPreview, 180)}"` : '',
    selection.id ? `Id: ${selection.id}` : '',
    selection.classNames.length ? `Classes: ${selection.classNames.slice(0, 8).join(', ')}` : '',
    `HTML snippet: ${trimText(selection.outerHtmlSnippet, MAX_HTML_CHARS) || '<unavailable>'}`,
  ].filter(Boolean).join('\n')
}

export function inferValidationProfile(treePaths: string[]): string {
  const hasFrontend = treePaths.some((p) =>
    p.startsWith('frontend/') || p === 'package.json' || p.endsWith('/package.json'),
  )
  if (hasFrontend) return 'react'
  return 'python'
}

export function parsePageElementContext(value: unknown): PageElementContextPayload | null {
  if (!value || typeof value !== 'object') return null
  const payload = value as Record<string, unknown>
  const selector = typeof payload.selector === 'string' ? payload.selector : ''
  const tagName = typeof payload.tag_name === 'string' ? payload.tag_name : ''
  const url = typeof payload.url === 'string' ? payload.url : ''
  if (!selector || !tagName || !url) return null
  return {
    url,
    title: typeof payload.title === 'string' ? payload.title : '',
    selector,
    tag_name: tagName,
    id: typeof payload.id === 'string' ? payload.id : undefined,
    class_names: Array.isArray(payload.class_names) ? payload.class_names.map((item) => String(item)) : [],
    text_preview: typeof payload.text_preview === 'string' ? payload.text_preview : '',
    outer_html_snippet: typeof payload.outer_html_snippet === 'string' ? payload.outer_html_snippet : '',
    rect: {
      x: Number((payload.rect as Record<string, unknown> | undefined)?.x || 0),
      y: Number((payload.rect as Record<string, unknown> | undefined)?.y || 0),
      width: Number((payload.rect as Record<string, unknown> | undefined)?.width || 0),
      height: Number((payload.rect as Record<string, unknown> | undefined)?.height || 0),
    },
    computed_styles: payload.computed_styles && typeof payload.computed_styles === 'object'
      ? Object.fromEntries(
        Object.entries(payload.computed_styles as Record<string, unknown>).map(([key, entry]) => [key, String(entry)])
      )
      : undefined,
    captured_at: typeof payload.captured_at === 'string' ? payload.captured_at : '',
  }
}
