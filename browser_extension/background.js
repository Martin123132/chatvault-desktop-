const API_URL = 'http://127.0.0.1:8000/api/browser-capture';

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({ id: 'save_selection', title: 'Save selected text to ChatVault', contexts: ['selection'], documentUrlPatterns: ['https://chatgpt.com/*'] });
  chrome.contextMenus.create({ id: 'save_assistant', title: 'Save nearest assistant message', contexts: ['selection', 'page'], documentUrlPatterns: ['https://chatgpt.com/*'] });
});

async function sendCapture(data, project = '', tags = []) {
  const body = { provider: 'chatgpt', page_url: data.page_url, conversation_title: data.conversation_title, captured_at: new Date().toISOString(), messages: data.messages, markdown: data.markdown, project, tags };
  const res = await fetch(API_URL, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

async function captureFromTab(tabId, type) {
  const resp = await chrome.tabs.sendMessage(tabId, { type });
  if (!resp?.ok) throw new Error('Capture failed');
  return resp.payload;
}

function notify(title, message) {
  chrome.notifications.create({ type: 'basic', iconUrl: 'icon.svg', title, message });
}

chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  try {
    const type = info.menuItemId === 'save_selection' ? 'CAPTURE_SELECTION' : 'CAPTURE_NEAREST_ASSISTANT';
    const data = await captureFromTab(tab.id, type);
    const result = await sendCapture(data);
    notify('ChatVault Capture', `Saved (${result.messages_imported} messages)`);
  } catch (e) {
    notify('ChatVault Capture error', String(e));
  }
});

chrome.runtime.onMessage.addListener((req, _sender, sendResponse) => {
  if (req.type !== 'SAVE_FROM_POPUP') return;
  (async () => {
    try {
      const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
      const data = await captureFromTab(tab.id, 'CAPTURE_THREAD');
      const tags = (req.tags || '').split(',').map(s => s.trim()).filter(Boolean);
      const result = await sendCapture(data, req.project || '', tags);
      sendResponse({ ok: true, result });
    } catch (e) {
      sendResponse({ ok: false, error: String(e) });
    }
  })();
  return true;
});
