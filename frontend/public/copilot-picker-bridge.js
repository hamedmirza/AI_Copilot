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
    AGENT_COMMAND: 'COPILOT_AGENT_COMMAND',
    AGENT_RESULT: 'COPILOT_AGENT_RESULT',
    AGENT_NAVIGATE: 'COPILOT_AGENT_NAVIGATE',
  }
  var MAX_SELECTOR_LEN = 512
  var consoleErrors = []

  function recordConsoleError(message) {
    if (!message) return
    consoleErrors.push(String(message).slice(0, 500))
    if (consoleErrors.length > 20) consoleErrors.shift()
  }

  window.addEventListener('error', function (event) {
    recordConsoleError(event.message || 'window error')
  })
  window.addEventListener('unhandledrejection', function (event) {
    recordConsoleError(String(event.reason || 'unhandled rejection'))
  })
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
    if (!value || value === 'null') return null
    try {
      return new URL(value, window.location.href).origin
    } catch (_error) {
      return null
    }
  }

  function isTrustedParentMessage(event) {
    if (!state.parentOrigin) return false
    var eventOrigin = safeOrigin(event.origin)
    if (eventOrigin === state.parentOrigin) return true
    // Sandboxed preview (allow-scripts without allow-same-origin): parent uses postMessage('*').
    return event.origin === 'null'
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

  function validateSelector(selector) {
    if (!selector || typeof selector !== 'string') return null
    var trimmed = selector.trim()
    if (!trimmed || trimmed.length > MAX_SELECTOR_LEN) return null
    return trimmed
  }

  function queryElement(selector) {
    var safe = validateSelector(selector)
    if (!safe) return null
    try {
      return document.querySelector(safe)
    } catch (_error) {
      return null
    }
  }

  function visibleText(root) {
    var node = root || document.body
    if (!node) return ''
    return trimText(node.innerText || node.textContent || '', 12000)
  }

  function agentReply(requestId, ok, result, error) {
    postToParent(MSG.AGENT_RESULT, {
      requestId: requestId,
      ok: ok,
      result: result || {},
      error: error || undefined,
    })
  }

  function captureScreenshot(selector) {
    var target = selector ? queryElement(selector) : document.documentElement
    if (!target) return null
    var rect = target.getBoundingClientRect()
    var width = Math.max(1, Math.round(rect.width || window.innerWidth))
    var height = Math.max(1, Math.round(rect.height || window.innerHeight))
    var canvas = document.createElement('canvas')
    canvas.width = width
    canvas.height = height
    var ctx = canvas.getContext('2d')
    if (!ctx) return null
    ctx.fillStyle = '#ffffff'
    ctx.fillRect(0, 0, width, height)
    try {
      return canvas.toDataURL('image/png')
    } catch (_error) {
      return null
    }
  }

  function waitForCondition(selector, text, timeoutMs, requestId) {
    var deadline = Date.now() + Math.max(500, timeoutMs || 8000)
    function poll() {
      if (selector) {
        var element = queryElement(selector)
        if (element) {
          agentReply(requestId, true, { found: true, selector: selector })
          return
        }
      }
      if (text) {
        var body = visibleText(document.body)
        if (body.toLowerCase().indexOf(String(text).toLowerCase()) !== -1) {
          agentReply(requestId, true, { found: true, text: text })
          return
        }
      }
      if (Date.now() >= deadline) {
        agentReply(requestId, false, {}, 'wait_for timeout')
        return
      }
      window.setTimeout(poll, 200)
    }
    poll()
  }

  function handleAgentCommand(payload) {
    var requestId = payload && payload.requestId
    var action = payload && payload.action
    if (!requestId || !action) {
      return
    }
    if (action === 'snapshot') {
      var snapRoot = payload.selector ? queryElement(payload.selector) : document.body
      if (payload.selector && !snapRoot) {
        agentReply(requestId, false, {}, 'selector not found')
        return
      }
      agentReply(requestId, true, {
        url: sourceUrl(),
        title: document.title || '',
        visibleText: visibleText(snapRoot),
        selector: payload.selector || undefined,
      })
      return
    }
    if (action === 'click') {
      var clickTarget = queryElement(payload.selector)
      if (!clickTarget) {
        agentReply(requestId, false, {}, 'selector not found')
        return
      }
      clickTarget.scrollIntoView({ block: 'center', inline: 'nearest' })
      clickTarget.click()
      agentReply(requestId, true, { clicked: true, selector: payload.selector })
      return
    }
    if (action === 'type') {
      var typeTarget = queryElement(payload.selector)
      if (!typeTarget) {
        agentReply(requestId, false, {}, 'selector not found')
        return
      }
      typeTarget.scrollIntoView({ block: 'center', inline: 'nearest' })
      if (payload.clear) {
        typeTarget.value = ''
      }
      var textValue = String(payload.text || '')
      if ('value' in typeTarget) {
        typeTarget.value = textValue
        typeTarget.dispatchEvent(new Event('input', { bubbles: true }))
        typeTarget.dispatchEvent(new Event('change', { bubbles: true }))
      } else {
        typeTarget.textContent = textValue
      }
      agentReply(requestId, true, { typed: true, selector: payload.selector })
      return
    }
    if (action === 'scroll_into_view') {
      var scrollTarget = queryElement(payload.selector)
      if (!scrollTarget) {
        agentReply(requestId, false, {}, 'selector not found')
        return
      }
      scrollTarget.scrollIntoView({ block: 'center', inline: 'nearest' })
      agentReply(requestId, true, { scrolled: true, selector: payload.selector })
      return
    }
    if (action === 'wait_for') {
      waitForCondition(payload.selector, payload.text, payload.timeoutMs, requestId)
      return
    }
    if (action === 'screenshot') {
      var shot = captureScreenshot(payload.selector)
      if (!shot) {
        agentReply(requestId, false, {}, 'screenshot failed')
        return
      }
      agentReply(requestId, true, { dataUrl: shot, selector: payload.selector || undefined })
      return
    }
    if (action === 'get_console_errors') {
      agentReply(requestId, true, { errors: consoleErrors.slice() })
      return
    }
    agentReply(requestId, false, {}, 'unknown action')
  }

  function handleMessage(event) {
    var message = event.data
    if (!message || typeof message.type !== 'string') {
      return
    }

    if (message.type === MSG.AGENT_COMMAND) {
      if (!state.parentOrigin || safeOrigin(event.origin) !== state.parentOrigin) {
        var eventOrigin = safeOrigin(event.origin)
        if (eventOrigin) state.parentOrigin = eventOrigin
      }
      handleAgentCommand(message.payload || {})
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

    if (!isTrustedParentMessage(event)) {
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
