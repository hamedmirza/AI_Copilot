;(function () {
  'use strict'

  if (window.__AI_COPILOT_PICKER_BRIDGE__) {
    return
  }
  window.__AI_COPILOT_PICKER_BRIDGE__ = true

  var MSG = {
    BRIDGE_READY: 'COPILOT_PICKER_BRIDGE_READY',
    ENABLE_PICKER: 'COPILOT_PICKER_ENABLE',
    DISABLE_PICKER: 'COPILOT_PICKER_DISABLE',
    ELEMENT_SELECTED: 'COPILOT_PICKER_ELEMENT_SELECTED',
    QUICK_ADD: 'COPILOT_PICKER_QUICK_ADD',
    PICKER_CANCELLED: 'COPILOT_PICKER_CANCELLED',
  }
  var STABLE_DATA_ATTRIBUTES = ['data-testid', 'data-test', 'data-qa', 'data-cy']
  var OVERLAY_Z_INDEX = '2147483647'

  var state = {
    enabled: false,
    parentOrigin: safeOrigin(document.referrer),
    hoverElement: null,
    selectedElement: null,
    overlayRoot: null,
    outlineEl: null,
    labelEl: null,
  }

  function safeOrigin(value) {
    if (!value) return null
    try {
      return new URL(value, window.location.href).origin
    } catch (_error) {
      return null
    }
  }

  function trimText(value, limit) {
    var text = String(value || '').replace(/\s+/g, ' ').trim()
    if (text.length <= limit) return text
    return text.slice(0, Math.max(0, limit - 3)).trimEnd() + '...'
  }

  function cssEscape(value) {
    if (window.CSS && typeof window.CSS.escape === 'function') {
      return window.CSS.escape(value)
    }
    return String(value).replace(/[^a-zA-Z0-9_-]/g, function (char) {
      return '\\' + char
    })
  }

  function safeQuerySelectorAll(selector) {
    try {
      return Array.prototype.slice.call(document.querySelectorAll(selector))
    } catch (_error) {
      return []
    }
  }

  function isUniqueSelector(selector, element) {
    var matches = safeQuerySelectorAll(selector)
    return matches.length === 1 && matches[0] === element
  }

  function stableDataSelector(element) {
    for (var i = 0; i < STABLE_DATA_ATTRIBUTES.length; i += 1) {
      var attribute = STABLE_DATA_ATTRIBUTES[i]
      var value = element.getAttribute(attribute)
      if (!value) continue
      return element.tagName.toLowerCase() + '[' + attribute + '="' + cssEscape(value) + '"]'
    }
    return null
  }

  function stableClassSelector(element) {
    var classNames = Array.prototype.slice.call(element.classList || [])
      .filter(function (className) {
        return className.length > 1 && !/^\d/.test(className) && className.indexOf(':') === -1
      })
      .slice(0, 2)

    if (classNames.length === 0) return null
    return element.tagName.toLowerCase() + classNames.map(function (className) {
      return '.' + cssEscape(className)
    }).join('')
  }

  function nthChildSelector(element) {
    var parent = element.parentElement
    if (!parent) return element.tagName.toLowerCase()
    var index = Array.prototype.indexOf.call(parent.children, element) + 1
    return element.tagName.toLowerCase() + ':nth-child(' + index + ')'
  }

  function candidateSegments(element) {
    var tagName = element.tagName.toLowerCase()
    var candidates = [tagName]
    var dataSelector = stableDataSelector(element)
    if (dataSelector) candidates.push(dataSelector)
    var classSelector = stableClassSelector(element)
    if (classSelector) candidates.push(classSelector)
    candidates.push(nthChildSelector(element))
    return Array.from(new Set(candidates))
  }

  function buildCssSelector(element) {
    var elementId = element.id && element.id.trim()
    if (elementId) {
      var idSelector = '#' + cssEscape(elementId)
      if (isUniqueSelector(idSelector, element)) {
        return idSelector
      }
    }

    var directCandidates = candidateSegments(element)
    for (var i = 0; i < directCandidates.length; i += 1) {
      if (isUniqueSelector(directCandidates[i], element)) {
        return directCandidates[i]
      }
    }

    var segments = []
    var current = element
    while (current && current.nodeType === Node.ELEMENT_NODE) {
      var currentId = current.id && current.id.trim()
      if (currentId) {
        segments.unshift('#' + cssEscape(currentId))
        return segments.join(' > ')
      }

      var options = candidateSegments(current)
      var chosen = options[options.length - 1]
      for (var j = 0; j < options.length; j += 1) {
        var candidate = [options[j]].concat(segments).join(' > ')
        if (isUniqueSelector(candidate, element)) {
          chosen = options[j]
          segments.unshift(chosen)
          return segments.join(' > ')
        }
      }

      segments.unshift(chosen)
      var joined = segments.join(' > ')
      if (isUniqueSelector(joined, element)) {
        return joined
      }
      current = current.parentElement
    }

    return segments.join(' > ') || element.tagName.toLowerCase()
  }

  function createOverlay() {
    if (state.overlayRoot) return

    var root = document.createElement('div')
    root.setAttribute('data-ai-copilot-picker-overlay', 'true')
    root.style.position = 'fixed'
    root.style.inset = '0'
    root.style.pointerEvents = 'none'
    root.style.zIndex = OVERLAY_Z_INDEX

    var outline = document.createElement('div')
    outline.style.position = 'fixed'
    outline.style.border = '2px solid rgba(59, 130, 246, 0.95)'
    outline.style.background = 'rgba(59, 130, 246, 0.12)'
    outline.style.boxShadow = '0 0 0 99999px rgba(15, 23, 42, 0.08)'
    outline.style.borderRadius = '6px'
    outline.style.pointerEvents = 'none'
    outline.style.display = 'none'

    var label = document.createElement('div')
    label.style.position = 'fixed'
    label.style.padding = '4px 8px'
    label.style.borderRadius = '999px'
    label.style.background = 'rgba(15, 23, 42, 0.95)'
    label.style.color = '#ffffff'
    label.style.font = '12px/1.4 system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif'
    label.style.pointerEvents = 'none'
    label.style.display = 'none'
    label.style.maxWidth = 'min(480px, calc(100vw - 24px))'
    label.style.whiteSpace = 'nowrap'
    label.style.overflow = 'hidden'
    label.style.textOverflow = 'ellipsis'

    root.appendChild(outline)
    root.appendChild(label)
    ;(document.body || document.documentElement).appendChild(root)
    state.overlayRoot = root
    state.outlineEl = outline
    state.labelEl = label
  }

  function hideOverlay() {
    if (state.outlineEl) state.outlineEl.style.display = 'none'
    if (state.labelEl) state.labelEl.style.display = 'none'
  }

  function updateOverlay(element) {
    createOverlay()
    if (!element || !state.outlineEl || !state.labelEl) {
      hideOverlay()
      return
    }

    var rect = element.getBoundingClientRect()
    if (!rect.width && !rect.height) {
      hideOverlay()
      return
    }

    state.outlineEl.style.display = 'block'
    state.outlineEl.style.left = rect.left + 'px'
    state.outlineEl.style.top = rect.top + 'px'
    state.outlineEl.style.width = rect.width + 'px'
    state.outlineEl.style.height = rect.height + 'px'

    state.labelEl.textContent = trimText(buildCssSelector(element), 96) || element.tagName.toLowerCase()
    state.labelEl.style.display = 'block'
    state.labelEl.style.left = Math.max(8, rect.left) + 'px'
    state.labelEl.style.top = Math.max(8, rect.top - 30) + 'px'
  }

  function currentComputedStyles(element) {
    var computed = window.getComputedStyle(element)
    return {
      color: computed.color,
      backgroundColor: computed.backgroundColor,
      fontSize: computed.fontSize,
      fontWeight: computed.fontWeight,
      padding: computed.padding,
      margin: computed.margin,
      display: computed.display,
      borderRadius: computed.borderRadius,
    }
  }

  function sourceUrl() {
    return window.__AI_COPILOT_PICKER_SOURCE_URL__ || window.location.href
  }

  function buildSelectionPayload(element) {
    var rect = element.getBoundingClientRect()
    return {
      url: sourceUrl(),
      title: document.title || '',
      selector: buildCssSelector(element),
      tagName: element.tagName.toLowerCase(),
      id: element.id || undefined,
      classNames: Array.prototype.slice.call(element.classList || []).slice(0, 12),
      textPreview: trimText(element.innerText || element.textContent || '', 220),
      outerHtmlSnippet: trimText(element.outerHTML || '', 700),
      rect: {
        x: Math.round(rect.x),
        y: Math.round(rect.y),
        width: Math.round(rect.width),
        height: Math.round(rect.height),
      },
      computedStyles: currentComputedStyles(element),
      capturedAt: new Date().toISOString(),
    }
  }

  function targetOriginFor(type) {
    if (!window.parent || window.parent === window) return null
    if (state.parentOrigin) return state.parentOrigin
    if (type === MSG.BRIDGE_READY) return '*'
    return null
  }

  function postToParent(type, payload) {
    var targetOrigin = targetOriginFor(type)
    if (!targetOrigin) return
    window.parent.postMessage({ type: type, payload: payload || {} }, targetOrigin)
  }

  function emitBridgeReady() {
    postToParent(MSG.BRIDGE_READY, { url: sourceUrl() })
  }

  function resetCursor() {
    document.documentElement.style.cursor = ''
    if (document.body) {
      document.body.style.cursor = ''
    }
  }

  function enablePicker() {
    state.enabled = true
    document.documentElement.style.cursor = 'crosshair'
    if (document.body) {
      document.body.style.cursor = 'crosshair'
    }
  }

  function disablePicker(keepSelection) {
    state.enabled = false
    state.hoverElement = null
    if (!keepSelection) {
      state.selectedElement = null
      hideOverlay()
    } else if (state.selectedElement) {
      updateOverlay(state.selectedElement)
    }
    resetCursor()
  }

  function resolveTarget(event) {
    var target = document.elementFromPoint(event.clientX, event.clientY)
    if (!target || target === state.overlayRoot || (state.overlayRoot && state.overlayRoot.contains(target))) {
      return null
    }
    return target
  }

  function handleMove(event) {
    if (!state.enabled) return
    var target = resolveTarget(event)
    if (!target) return
    state.hoverElement = target
    updateOverlay(target)
  }

  function handleClick(event) {
    if (!state.enabled) return
    var target = resolveTarget(event)
    if (!target) return

    event.preventDefault()
    event.stopPropagation()
    event.stopImmediatePropagation()

    state.selectedElement = target
    updateOverlay(target)
    disablePicker(true)
    postToParent(event.altKey ? MSG.QUICK_ADD : MSG.ELEMENT_SELECTED, buildSelectionPayload(target))
  }

  function handleKeydown(event) {
    if (!state.enabled || event.key !== 'Escape') return
    event.preventDefault()
    disablePicker(false)
    postToParent(MSG.PICKER_CANCELLED, { url: window.location.href })
  }

  function handleMessage(event) {
    var message = event.data
    if (!message || typeof message.type !== 'string') {
      return
    }

    if (message.type === MSG.ENABLE_PICKER) {
      var requestedOrigin = safeOrigin(message.payload && message.payload.parentOrigin)
      var eventOrigin = safeOrigin(event.origin)
      if (requestedOrigin && eventOrigin && requestedOrigin !== eventOrigin) {
        return
      }
      state.parentOrigin = requestedOrigin || eventOrigin || state.parentOrigin
      if (!state.parentOrigin) return
      enablePicker()
      return
    }

    if (!state.parentOrigin || safeOrigin(event.origin) !== state.parentOrigin) {
      return
    }

    if (message.type === MSG.DISABLE_PICKER) {
      disablePicker(false)
    }
  }

  function registerNavigationHooks() {
    var originalPushState = history.pushState
    var originalReplaceState = history.replaceState

    history.pushState = function () {
      var result = originalPushState.apply(this, arguments)
      window.setTimeout(emitBridgeReady, 0)
      return result
    }

    history.replaceState = function () {
      var result = originalReplaceState.apply(this, arguments)
      window.setTimeout(emitBridgeReady, 0)
      return result
    }
  }

  window.addEventListener('message', handleMessage)
  window.addEventListener('mousemove', handleMove, true)
  window.addEventListener('click', handleClick, true)
  window.addEventListener('keydown', handleKeydown, true)
  window.addEventListener('hashchange', emitBridgeReady)
  window.addEventListener('popstate', emitBridgeReady)
  window.addEventListener('load', emitBridgeReady)

  registerNavigationHooks()
  if (document.readyState !== 'loading') {
    window.setTimeout(emitBridgeReady, 0)
  } else {
    document.addEventListener('DOMContentLoaded', function onReady() {
      document.removeEventListener('DOMContentLoaded', onReady)
      emitBridgeReady()
    })
  }
})()
