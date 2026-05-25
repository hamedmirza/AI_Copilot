const STABLE_DATA_ATTRIBUTES = ['data-testid', 'data-test', 'data-qa', 'data-cy'] as const

function cssEscape(value: string): string {
  if (typeof CSS !== 'undefined' && typeof CSS.escape === 'function') {
    return CSS.escape(value)
  }
  return value.replace(/[^a-zA-Z0-9_-]/g, (char) => `\\${char}`)
}

function safeQuerySelectorAll(selector: string, root: ParentNode = document): Element[] {
  try {
    return Array.from(root.querySelectorAll(selector))
  } catch {
    return []
  }
}

function isUniqueSelector(selector: string, element: Element, root: ParentNode = document): boolean {
  const matches = safeQuerySelectorAll(selector, root)
  return matches.length === 1 && matches[0] === element
}

function stableDataSelector(element: Element): string | null {
  for (const attribute of STABLE_DATA_ATTRIBUTES) {
    const value = element.getAttribute(attribute)
    if (!value) continue
    return `${element.tagName.toLowerCase()}[${attribute}="${cssEscape(value)}"]`
  }
  return null
}

function stableClassSelector(element: Element): string | null {
  const stableClasses = Array.from(element.classList)
    .filter((className) => (
      className.length > 1
      && !/^\d/.test(className)
      && !className.includes(':')
    ))
    .slice(0, 2)

  if (stableClasses.length === 0) return null
  return `${element.tagName.toLowerCase()}${stableClasses.map((className) => `.${cssEscape(className)}`).join('')}`
}

function nthChildSelector(element: Element): string {
  const parent = element.parentElement
  if (!parent) return element.tagName.toLowerCase()
  const index = Array.from(parent.children).indexOf(element) + 1
  return `${element.tagName.toLowerCase()}:nth-child(${index})`
}

function candidateSegments(element: Element): string[] {
  const tagName = element.tagName.toLowerCase()
  const candidates = new Set<string>([tagName])
  const dataSelector = stableDataSelector(element)
  if (dataSelector) candidates.add(dataSelector)
  const classSelector = stableClassSelector(element)
  if (classSelector) candidates.add(classSelector)
  candidates.add(nthChildSelector(element))
  return Array.from(candidates)
}

export function buildCssSelector(element: Element, root: ParentNode = document): string {
  const elementId = element.id?.trim()
  if (elementId) {
    const idSelector = `#${cssEscape(elementId)}`
    if (isUniqueSelector(idSelector, element, root)) {
      return idSelector
    }
  }

  for (const selector of candidateSegments(element)) {
    if (isUniqueSelector(selector, element, root)) {
      return selector
    }
  }

  const segments: string[] = []
  let current: Element | null = element
  while (current && current.nodeType === Node.ELEMENT_NODE) {
    const currentId = current.id?.trim()
    if (currentId) {
      const idSelector = `#${cssEscape(currentId)}`
      segments.unshift(idSelector)
      return segments.join(' > ')
    }

    const nextSegment = candidateSegments(current).find((segment) => {
      const candidate = [...segments, segment].join(' > ')
      return isUniqueSelector(candidate, element, root)
    }) || nthChildSelector(current)

    segments.unshift(nextSegment)
    const candidate = segments.join(' > ')
    if (isUniqueSelector(candidate, element, root)) {
      return candidate
    }
    current = current.parentElement
  }

  return segments.join(' > ') || element.tagName.toLowerCase()
}

export const __selectorTestUtils = {
  candidateSegments,
  stableClassSelector,
  stableDataSelector,
}
