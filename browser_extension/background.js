const DEFAULT_API_URL = 'http://127.0.0.1:8000/api/browser-capture';
const SUPPORTED_URLS = [
  'https://chatgpt.com/*',
  'https://chat.openai.com/*',
  'https://claude.ai/*',
  'https://gemini.google.com/*'
];

const liveCache = new Map();

chrome.runtime.onInstalled.addListener(() => {
  chrome.storage.local.get({
    apiUrl: DEFAULT_API_URL,
    autoCapture: false,
    project: '',
    tags: ''
  }, (settings) => chrome.storage.local.set(settings));

  chrome.contextMenus.removeAll(() => {
    chrome.contextMenus.create({
      id: 'save_selection',
      title: 'Save selected text to ChatVault',
      contexts: ['selection'],
      documentUrlPatterns: SUPPORTED_URLS
    });
    chrome.contextMenus.create({
      id: 'save_assistant',
      title: 'Save nearest assistant message',
      contexts: ['selection', 'page'],
      documentUrlPatterns: SUPPORTED_URLS
    });
  });
});

function storageGet(defaults) {
  return new Promise((resolve) => chrome.storage.local.get(defaults, resolve));
}

function storageSet(values) {
  return new Promise((resolve) => chrome.storage.local.set(values, resolve));
}

function activeTab() {
  return new Promise((resolve) => {
    chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => resolve(tabs[0]));
  });
}

function sendTabMessage(tabId, message) {
  return new Promise((resolve, reject) => {
    chrome.tabs.sendMessage(tabId, message, (response) => {
      if (chrome.runtime.lastError) {
        reject(new Error(chrome.runtime.lastError.message));
        return;
      }
      resolve(response);
    });
  });
}

function tagList(tags) {
  return String(tags || '')
    .split(',')
    .map((tag) => tag.trim())
    .filter(Boolean);
}

async function sendCapture(data, overrides = {}) {
  const settings = await storageGet({
    apiUrl: DEFAULT_API_URL,
    project: '',
    tags: ''
  });
  const body = {
    provider: data.provider || 'chatgpt',
    page_url: data.page_url,
    conversation_title: data.conversation_title,
    captured_at: new Date().toISOString(),
    external_id: data.external_id || null,
    capture_mode: overrides.captureMode || data.capture_mode || 'manual',
    replace_existing: Boolean(overrides.replaceExisting ?? data.replace_existing),
    messages: data.messages || [],
    markdown: data.markdown || '',
    project: overrides.project ?? settings.project,
    tags: tagList(overrides.tags ?? settings.tags)
  };
  const apiUrl = overrides.apiUrl || settings.apiUrl || DEFAULT_API_URL;
  const res = await fetch(apiUrl, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

async function captureFromTab(tabId, type) {
  const resp = await sendTabMessage(tabId, { type });
  if (!resp?.ok || !resp.payload) throw new Error('Capture failed on this page');
  return resp.payload;
}

function notify(title, message) {
  chrome.notifications.create({ type: 'basic', iconUrl: 'icon.svg', title, message });
}

async function setBadge(text, color = '#00c2c7') {
  chrome.action.setBadgeBackgroundColor({ color });
  chrome.action.setBadgeText({ text });
}

chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  try {
    const type = info.menuItemId === 'save_selection' ? 'CAPTURE_SELECTION' : 'CAPTURE_NEAREST_ASSISTANT';
    const data = await captureFromTab(tab.id, type);
    const result = await sendCapture(data, { captureMode: 'manual', replaceExisting: false });
    notify('ChatVault Capture', `Saved (${result.messages_imported} messages)`);
  } catch (e) {
    notify('ChatVault Capture error', String(e));
  }
});

chrome.runtime.onMessage.addListener((req, sender, sendResponse) => {
  if (req.type === 'LIVE_CAPTURE_SNAPSHOT') {
    (async () => {
      try {
        const settings = await storageGet({ autoCapture: false, project: '', tags: '' });
        if (!settings.autoCapture) return;
        const payload = req.payload || {};
        const key = payload.external_id || `${payload.provider}:${payload.page_url}`;
        const hash = JSON.stringify((payload.messages || []).map((m) => [m.role, m.content]));
        if (liveCache.get(key) === hash) return;
        liveCache.set(key, hash);
        const result = await sendCapture(payload, { captureMode: 'live', replaceExisting: true });
        await storageSet({
          lastCaptureStatus: `Live saved ${result.messages_imported} messages`,
          lastCaptureAt: new Date().toISOString()
        });
        await setBadge('OK');
      } catch (e) {
        await storageSet({ lastCaptureStatus: String(e), lastCaptureAt: new Date().toISOString() });
        await setBadge('!', '#d84f68');
      }
    })();
    sendResponse({ ok: true });
    return true;
  }

  if (req.type === 'SAVE_FROM_POPUP') {
    (async () => {
      try {
        const tab = await activeTab();
        const data = await captureFromTab(tab.id, 'CAPTURE_THREAD');
        const result = await sendCapture(data, {
          captureMode: 'manual_thread',
          replaceExisting: true,
          project: req.project || '',
          tags: req.tags || '',
          apiUrl: req.apiUrl || ''
        });
        await storageSet({ project: req.project || '', tags: req.tags || '', apiUrl: req.apiUrl || DEFAULT_API_URL });
        sendResponse({ ok: true, result });
      } catch (e) {
        sendResponse({ ok: false, error: String(e) });
      }
    })();
    return true;
  }

  if (req.type === 'GET_ACTIVE_STATUS') {
    (async () => {
      try {
        const tab = await activeTab();
        const resp = await sendTabMessage(tab.id, { type: 'GET_PAGE_STATUS' });
        sendResponse(resp || { ok: false });
      } catch {
        sendResponse({ ok: false, provider: null, message_count: 0 });
      }
    })();
    return true;
  }
});
