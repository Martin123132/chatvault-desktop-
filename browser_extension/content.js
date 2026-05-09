const PROVIDERS = [
  {
    id: 'chatgpt',
    hosts: ['chatgpt.com', 'chat.openai.com'],
    titleSelectors: ['main h1', 'h1'],
    messages: [
      { selector: 'main [data-message-author-role]', role: (el) => (el.getAttribute('data-message-author-role') === 'user' ? 'user' : 'assistant') }
    ]
  },
  {
    id: 'claude',
    hosts: ['claude.ai'],
    titleSelectors: ['main h1', 'h1'],
    messages: [
      { selector: '[data-testid="user-message"]', role: 'user' },
      { selector: '[data-testid="assistant-message"]', role: 'assistant' },
      { selector: '[data-testid*="user"][data-testid*="message"]', role: 'user' },
      { selector: '[data-testid*="assistant"][data-testid*="message"]', role: 'assistant' },
      { selector: '[class*="user-message"]', role: 'user' },
      { selector: '[class*="assistant-message"]', role: 'assistant' }
    ]
  },
  {
    id: 'gemini',
    hosts: ['gemini.google.com'],
    titleSelectors: ['main h1', 'h1'],
    messages: [
      { selector: 'user-query', role: 'user' },
      { selector: '[class*="user-query"]', role: 'user' },
      { selector: 'model-response', role: 'assistant' },
      { selector: '[class*="model-response"]', role: 'assistant' },
      { selector: '[data-test-id*="user"]', role: 'user' },
      { selector: '[data-test-id*="response"]', role: 'assistant' }
    ]
  }
];

const LIVE_DEBOUNCE_MS = 1600;
let liveEnabled = false;
let liveTimer = null;
let lastLiveHash = '';
let observer = null;

function providerConfig() {
  const host = location.hostname.replace(/^www\./, '');
  return PROVIDERS.find((provider) => provider.hosts.includes(host)) || null;
}

function visibleText(el) {
  return (el.innerText || el.textContent || '')
    .replace(/\n{3,}/g, '\n\n')
    .replace(/[ \t]+\n/g, '\n')
    .trim();
}

function getTitle(provider) {
  for (const selector of provider.titleSelectors) {
    const el = document.querySelector(selector);
    const text = el ? visibleText(el) : '';
    if (text && text.length < 160) return text;
  }
  return document.title.replace(/\s+[|-]\s+(ChatGPT|Claude|Gemini).*$/i, '').trim() || `${provider.id} capture`;
}

function roleFor(rule, el) {
  return typeof rule.role === 'function' ? rule.role(el) : rule.role;
}

function stablePageUrl() {
  return `${location.origin}${location.pathname}`.replace(/\/$/, '') || location.href;
}

function externalId(provider) {
  return `browser_capture:${provider.id}:${stablePageUrl()}`;
}

function collectMessages(provider) {
  const candidates = [];
  const seen = new Set();

  for (const rule of provider.messages) {
    document.querySelectorAll(rule.selector).forEach((el) => {
      if (seen.has(el)) return;
      seen.add(el);
      const content = visibleText(el);
      if (!content || content.length < 2) return;
      candidates.push({ el, role: roleFor(rule, el), content });
    });
  }

  candidates.sort((a, b) => {
    if (a.el === b.el) return 0;
    return a.el.compareDocumentPosition(b.el) & Node.DOCUMENT_POSITION_PRECEDING ? 1 : -1;
  });

  const messages = [];
  for (const item of candidates) {
    const role = item.role === 'user' ? 'user' : 'assistant';
    const previous = messages[messages.length - 1];
    if (previous && previous.role === role && previous.content === item.content) continue;
    messages.push({ role, content: item.content });
  }
  return messages;
}

function toMarkdown(messages) {
  return messages.map((m) => `### ${m.role}\n\n${m.content}`).join('\n\n');
}

function buildCapturePayload(captureMode = 'manual') {
  const provider = providerConfig();
  if (!provider) return null;
  const messages = collectMessages(provider);
  return {
    provider: provider.id,
    external_id: externalId(provider),
    capture_mode: captureMode,
    replace_existing: captureMode === 'live' || captureMode === 'manual_thread',
    messages,
    markdown: toMarkdown(messages),
    conversation_title: getTitle(provider),
    page_url: location.href
  };
}

function nearestAssistantFromSelection() {
  const sel = window.getSelection();
  if (!sel || !sel.anchorNode) return null;
  let node = sel.anchorNode.nodeType === Node.ELEMENT_NODE ? sel.anchorNode : sel.anchorNode.parentElement;
  while (node && node !== document.body) {
    const provider = providerConfig();
    if (!provider) return null;
    for (const rule of provider.messages) {
      if (node.matches && node.matches(rule.selector) && roleFor(rule, node) !== 'user') {
        return { role: 'assistant', content: visibleText(node) };
      }
    }
    node = node.parentElement;
  }
  return null;
}

function hashPayload(payload) {
  return JSON.stringify((payload.messages || []).map((m) => [m.role, m.content]));
}

function queueLiveCapture() {
  if (!liveEnabled) return;
  clearTimeout(liveTimer);
  liveTimer = setTimeout(() => {
    const payload = buildCapturePayload('live');
    if (!payload || payload.messages.length === 0) return;
    const hash = hashPayload(payload);
    if (hash === lastLiveHash) return;
    lastLiveHash = hash;
    chrome.runtime.sendMessage({ type: 'LIVE_CAPTURE_SNAPSHOT', payload });
  }, LIVE_DEBOUNCE_MS);
}

function configureLiveCapture(enabled) {
  liveEnabled = Boolean(enabled);
  if (liveEnabled && !observer) {
    observer = new MutationObserver(queueLiveCapture);
    observer.observe(document.body, { childList: true, subtree: true, characterData: true });
    queueLiveCapture();
  }
  if (!liveEnabled && observer) {
    observer.disconnect();
    observer = null;
  }
}

chrome.storage.local.get({ autoCapture: false }, (settings) => {
  configureLiveCapture(settings.autoCapture);
});

chrome.storage.onChanged.addListener((changes, areaName) => {
  if (areaName === 'local' && changes.autoCapture) {
    configureLiveCapture(changes.autoCapture.newValue);
  }
});

chrome.runtime.onMessage.addListener((req, _sender, sendResponse) => {
  if (req.type === 'CAPTURE_THREAD') {
    const payload = buildCapturePayload('manual_thread');
    sendResponse({ ok: Boolean(payload), payload });
  }
  if (req.type === 'CAPTURE_SELECTION') {
    const text = (window.getSelection() || '').toString().trim();
    const base = buildCapturePayload('manual');
    sendResponse({
      ok: Boolean(text && base),
      payload: base ? { ...base, replace_existing: false, external_id: null, messages: [{ role: 'user', content: text }], markdown: text } : null
    });
  }
  if (req.type === 'CAPTURE_NEAREST_ASSISTANT') {
    const msg = nearestAssistantFromSelection();
    const base = buildCapturePayload('manual');
    sendResponse({
      ok: Boolean(msg && base),
      payload: base ? { ...base, replace_existing: false, external_id: null, messages: msg ? [msg] : [], markdown: msg ? msg.content : '' } : null
    });
  }
  if (req.type === 'GET_PAGE_STATUS') {
    const provider = providerConfig();
    const payload = provider ? buildCapturePayload(liveEnabled ? 'live' : 'manual') : null;
    sendResponse({ ok: Boolean(provider), provider: provider?.id || null, message_count: payload?.messages.length || 0, live_enabled: liveEnabled });
  }
  return true;
});
