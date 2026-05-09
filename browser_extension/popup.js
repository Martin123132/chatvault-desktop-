const DEFAULT_API_URL = 'http://127.0.0.1:8000/api/browser-capture';

const els = {
  apiUrl: document.getElementById('apiUrl'),
  autoCapture: document.getElementById('autoCapture'),
  project: document.getElementById('project'),
  tags: document.getElementById('tags'),
  save: document.getElementById('save'),
  refresh: document.getElementById('refresh'),
  provider: document.getElementById('provider'),
  messageCount: document.getElementById('messageCount'),
  status: document.getElementById('status')
};

function setStatus(message, ok = true) {
  els.status.textContent = message;
  els.status.className = ok ? 'ok' : 'bad';
}

function storageGet(defaults) {
  return new Promise((resolve) => chrome.storage.local.get(defaults, resolve));
}

function storageSet(values) {
  return new Promise((resolve) => chrome.storage.local.set(values, resolve));
}

function runtimeMessage(message) {
  return new Promise((resolve) => chrome.runtime.sendMessage(message, resolve));
}

async function loadSettings() {
  const settings = await storageGet({
    apiUrl: DEFAULT_API_URL,
    autoCapture: false,
    project: '',
    tags: '',
    lastCaptureStatus: ''
  });
  els.apiUrl.value = settings.apiUrl || DEFAULT_API_URL;
  els.autoCapture.checked = Boolean(settings.autoCapture);
  els.project.value = settings.project || '';
  els.tags.value = settings.tags || '';
  if (settings.lastCaptureStatus) setStatus(settings.lastCaptureStatus, !/^error|failed/i.test(settings.lastCaptureStatus));
}

async function saveSettings() {
  await storageSet({
    apiUrl: els.apiUrl.value.trim() || DEFAULT_API_URL,
    autoCapture: els.autoCapture.checked,
    project: els.project.value.trim(),
    tags: els.tags.value.trim()
  });
}

async function refreshStatus() {
  const resp = await runtimeMessage({ type: 'GET_ACTIVE_STATUS' });
  if (!resp?.ok) {
    els.provider.textContent = 'Unsupported';
    els.messageCount.textContent = '0 messages';
    return;
  }
  els.provider.textContent = resp.provider;
  els.messageCount.textContent = `${resp.message_count || 0} messages`;
}

els.autoCapture.addEventListener('change', async () => {
  await saveSettings();
  setStatus(els.autoCapture.checked ? 'Live capture on.' : 'Live capture off.');
  await refreshStatus();
});

els.apiUrl.addEventListener('change', saveSettings);
els.project.addEventListener('change', saveSettings);
els.tags.addEventListener('change', saveSettings);
els.refresh.addEventListener('click', refreshStatus);

els.save.addEventListener('click', async () => {
  await saveSettings();
  els.save.disabled = true;
  setStatus('Saving...');
  const resp = await runtimeMessage({
    type: 'SAVE_FROM_POPUP',
    project: els.project.value.trim(),
    tags: els.tags.value.trim(),
    apiUrl: els.apiUrl.value.trim() || DEFAULT_API_URL
  });
  els.save.disabled = false;
  if (resp?.ok) {
    setStatus(`Saved ${resp.result.messages_imported} messages.`);
    await refreshStatus();
  } else {
    setStatus(`Failed: ${resp?.error || 'unknown error'}`, false);
  }
});

(async function init() {
  await loadSettings();
  await refreshStatus();
})();
