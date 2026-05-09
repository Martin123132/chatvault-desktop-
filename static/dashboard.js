
const state = {
  settings: {},
  stats: {},
  conversations: [],
  projects: [],
  selectedConversationId: null,
  selectedProjectId: null,
  currentChatId: null,
  replayMessages: [],
  replayTimer: null,
};

const $ = (id) => document.getElementById(id);

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, (ch) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;'
  }[ch]));
}

function showToast(message, isError = false) {
  const toast = $('toast');
  toast.textContent = message;
  toast.className = `toast show${isError ? ' error' : ''}`;
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => { toast.className = 'toast'; }, 4200);
}

async function jget(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(await errorText(res));
  return res.json();
}

async function jpost(url, body) {
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await errorText(res));
  return res.json();
}

async function jdelete(url) {
  const res = await fetch(url, { method: 'DELETE' });
  if (!res.ok) throw new Error(await errorText(res));
  return res.json();
}

async function errorText(res) {
  try {
    const data = await res.json();
    return data.detail || JSON.stringify(data);
  } catch {
    return res.text();
  }
}

function setBusy(button, busy, label = 'Working...') {
  if (!button) return;
  if (busy) {
    button.dataset.label = button.textContent;
    button.textContent = label;
    button.disabled = true;
  } else {
    button.textContent = button.dataset.label || button.textContent;
    button.disabled = false;
  }
}

function switchView(name) {
  document.querySelectorAll('.view').forEach((view) => view.classList.remove('active'));
  document.querySelector(`#view-${name}`)?.classList.add('active');
  document.querySelectorAll('[data-view-target]').forEach((btn) => {
    btn.classList.toggle('active', btn.dataset.viewTarget === name && btn.closest('.nav'));
  });
  if (name === 'doctor') loadDoctor();
}

function initialView() {
  const requested = window.location.hash.replace(/^#/, '').trim();
  return requested && document.querySelector(`#view-${requested}`) ? requested : 'home';
}

function wireNavigation() {
  document.querySelectorAll('[data-view-target]').forEach((el) => {
    el.addEventListener('click', () => {
      switchView(el.dataset.viewTarget);
      if (el.id === 'setupImportBtn') $('setupOverlay').hidden = true;
    });
  });
}

function formatNumber(value) {
  return Number(value || 0).toLocaleString();
}

function renderStatus() {
  const s = state.settings || {};
  $('statusBackend').textContent = `${s.backend || 'openai'}${s.offline ? ' offline' : ''}`;
  $('statusOpenAI').textContent = s.openai_key_saved ? `OpenAI key ${s.openai_key_hint}` : 'OpenAI key missing';
  $('statusAnthropic').textContent = s.anthropic_key_saved ? `Anthropic key ${s.anthropic_key_hint}` : 'Anthropic key missing';
  $('backendDot').className = `dot${s.offline && s.backend !== 'ollama' ? ' warn' : ''}`;
  $('openaiDot').className = `dot${s.openai_key_saved ? '' : ' warn'}`;
  $('anthropicDot').className = `dot${s.anthropic_key_saved ? '' : ' warn'}`;
}

function renderStats() {
  const stats = state.stats || {};
  const messages = stats.total_messages || 0;
  const conversations = stats.total_conversations || 0;
  const documents = stats.document_count || 0;
  const tags = stats.tag_count || 0;
  const projects = stats.project_count || 0;
  $('metricMessages').textContent = formatNumber(messages);
  $('metricConversations').textContent = formatNumber(conversations);
  $('metricDocuments').textContent = formatNumber(documents);
  $('metricTags').textContent = formatNumber(tags);
  $('metricProjects').textContent = formatNumber(projects);
  $('sideMessages').textContent = formatNumber(messages);
  $('sideConversations').textContent = formatNumber(conversations);
  $('sideDocuments').textContent = formatNumber(documents);

  const cloud = $('tagCloud');
  cloud.innerHTML = '';
  const topTags = stats.top_tags || [];
  if (!topTags.length) {
    cloud.innerHTML = '<span class="muted mini">No tags yet.</span>';
  } else {
    topTags.forEach((tag, i) => {
      const badge = document.createElement('button');
      badge.className = `badge ${i % 3 === 1 ? 'violet' : i % 3 === 2 ? 'amber' : ''}`;
      badge.textContent = `#${tag.tag} ${tag.count}`;
      badge.addEventListener('click', () => {
        $('tagSearchName').value = tag.tag;
        switchView('tags');
        searchTag();
      });
      cloud.appendChild(badge);
    });
  }
}

function statusClass(status) {
  if (status === 'error') return 'status-error';
  if (status === 'warn') return 'status-warn';
  return 'status-ok';
}

async function loadDoctor() {
  const list = $('doctorList');
  if (!list) return;
  list.innerHTML = '<div class="muted">Running checks...</div>';
  try {
    const data = await jget('/api/setup/doctor');
    renderDoctor(data);
  } catch (err) {
    list.innerHTML = `<div class="item"><div class="item-title">Setup Doctor failed</div><div class="item-text">${escapeHtml(err.message)}</div></div>`;
    showToast(err.message, true);
  }
}

function renderDoctor(data) {
  const counts = data.counts || {};
  $('doctorSummary').innerHTML = `
    <span class="status-pill status-ok">${counts.ok || 0} OK</span>
    <span class="status-pill status-warn">${counts.warn || 0} Warning</span>
    <span class="status-pill status-error">${counts.error || 0} Error</span>
  `;
  const list = $('doctorList');
  list.innerHTML = '';
  (data.items || []).forEach((item) => {
    const div = document.createElement('div');
    div.className = 'item doctor-item';
    div.innerHTML = `
      <div class="item-head">
        <div>
          <div class="item-title">${escapeHtml(item.label)}</div>
          <div class="item-text">${escapeHtml(item.detail || '')}</div>
        </div>
        <span class="status-pill ${statusClass(item.status)}">${escapeHtml(item.status || 'ok')}</span>
      </div>
    `;
    if (item.action_view) {
      const row = document.createElement('div');
      row.className = 'action-row';
      row.style.marginTop = '8px';
      const btn = document.createElement('button');
      btn.className = 'ghost';
      btn.textContent = item.action_label || 'Open';
      btn.addEventListener('click', () => switchView(item.action_view));
      row.appendChild(btn);
      div.appendChild(row);
    }
    list.appendChild(div);
  });
}

function conversationItem(conversation) {
  const div = document.createElement('div');
  div.className = 'item';
  div.innerHTML = `
    <div class="item-head">
      <div>
        <div class="item-title">#${conversation.id} ${escapeHtml(conversation.title || '(untitled)')}</div>
        <div class="muted mini">${escapeHtml(conversation.provider || '')} - ${conversation.message_count || 0} messages</div>
      </div>
      <div class="item-actions">
        <button class="ghost" data-action="open">Open</button>
        <button class="ghost" data-action="project">Project</button>
        <button class="danger" data-action="delete">Delete</button>
      </div>
    </div>
    <div class="badge-row">
      <span class="badge">${escapeHtml(conversation.source || 'conversation')}</span>
      <span class="badge violet">${escapeHtml(conversation.updated_at || conversation.created_at || 'no date')}</span>
    </div>
  `;
  div.querySelector('[data-action="open"]').addEventListener('click', () => {
    switchView('conversations');
    loadConversation(conversation.id);
  });
  div.querySelector('[data-action="project"]').addEventListener('click', () => {
    $('projectConversationId').value = conversation.id;
    switchView('projects');
  });
  div.querySelector('[data-action="delete"]').addEventListener('click', () => deleteConversation(conversation.id));
  return div;
}

function renderConversations() {
  const list = $('conversationList');
  const home = $('homeConversations');
  const activity = $('recentActivity');
  [list, home, activity].forEach((target) => { target.innerHTML = ''; });

  if (!state.conversations.length) {
    list.innerHTML = '<div class="muted">No conversations imported yet.</div>';
    home.innerHTML = '<div class="muted">Import a conversation to begin.</div>';
    activity.innerHTML = '<div class="muted mini">No recent activity.</div>';
    return;
  }

  state.conversations.forEach((conversation) => list.appendChild(conversationItem(conversation)));
  state.conversations.slice(0, 5).forEach((conversation) => home.appendChild(conversationItem(conversation)));
  state.conversations.slice(0, 5).forEach((conversation) => {
    const div = document.createElement('div');
    div.className = 'item';
    div.innerHTML = `<div class="item-title">${escapeHtml(conversation.title || '(untitled)')}</div><div class="muted mini">#${conversation.id} - ${conversation.message_count || 0} messages</div>`;
    div.addEventListener('click', () => loadConversation(conversation.id));
    activity.appendChild(div);
  });
}

function messageElement(message) {
  const div = document.createElement('div');
  const role = String(message.role || 'message').toLowerCase();
  div.className = `message ${role}`;
  div.innerHTML = `
    <div class="message-head">
      <strong>#${message.id} ${escapeHtml(message.role)}</strong>
      <span>${escapeHtml(message.created_at || '')}</span>
    </div>
    <div class="message-content">${escapeHtml(message.content || '')}</div>
    <div class="message-actions">
      <button class="ghost" data-action="context">Context</button>
      <button class="ghost" data-action="tag">Tag</button>
    </div>
  `;
  div.querySelector('[data-action="context"]').addEventListener('click', () => {
    $('contextMessageId').value = message.id;
    loadContext();
  });
  div.querySelector('[data-action="tag"]').addEventListener('click', () => {
    $('tagMessageId').value = message.id;
    switchView('tags');
  });
  return div;
}

async function loadSettings() {
  state.settings = await jget('/api/settings');
  renderStatus();
  $('settingsBackend').value = state.settings.backend || 'openai';
  $('settingsOffline').checked = Boolean(state.settings.offline);
  $('settingsEmbeddingsModel').value = state.settings.embeddings_model || '';
  $('settingsOpenAIModel').value = state.settings.openai_model || '';
  $('settingsAnthropicModel').value = state.settings.anthropic_model || '';
  $('settingsOllamaHost').value = state.settings.ollama_host || '';
  $('settingsOllamaModel').value = state.settings.ollama_model || '';
  $('settingsPath').textContent = state.settings.env_file || '';
  $('openaiKeyLabel').textContent = state.settings.openai_key_saved ? `OpenAI API key (${state.settings.openai_key_hint})` : 'OpenAI API key';
  $('anthropicKeyLabel').textContent = state.settings.anthropic_key_saved ? `Anthropic API key (${state.settings.anthropic_key_hint})` : 'Anthropic API key';
  if ($('setupBackend')) {
    $('setupBackend').value = state.settings.backend || 'openai';
    $('setupOffline').checked = Boolean(state.settings.offline);
    $('setupOllamaHost').value = state.settings.ollama_host || '';
    $('setupOllamaModel').value = state.settings.ollama_model || '';
  }
}

async function loadStats() {
  state.stats = await jget('/api/stats');
  state.settings = state.stats.settings || state.settings;
  renderStats();
  renderStatus();
}

async function loadConversations() {
  state.conversations = await jget('/api/conversations?limit=100');
  renderConversations();
}

async function loadProjects() {
  state.projects = await jget('/api/projects');
  renderProjectOptions();
  renderProjects();
}

function renderProjectOptions() {
  const selects = [$('askProject'), $('projectSelect')].filter(Boolean);
  selects.forEach((select) => {
    const current = select.value;
    const first = select.id === 'askProject' ? '<option value="">Entire vault</option>' : '<option value="">Choose project</option>';
    select.innerHTML = first;
    state.projects.forEach((project) => {
      const opt = document.createElement('option');
      opt.value = project.id;
      opt.textContent = project.name;
      select.appendChild(opt);
    });
    select.value = current;
  });
}

function renderProjects() {
  const list = $('projectList');
  if (!list) return;
  list.innerHTML = '';
  if (!state.projects.length) {
    list.innerHTML = '<div class="muted">No projects yet.</div>';
    return;
  }
  state.projects.forEach((project) => {
    const div = document.createElement('div');
    div.className = 'item';
    div.innerHTML = `
      <div class="item-head">
        <div>
          <div class="item-title">${escapeHtml(project.name)}</div>
          <div class="muted mini">${project.conversation_count || 0} conversations - ${project.note_count || 0} notes</div>
        </div>
        <button class="ghost">Open</button>
      </div>
    `;
    div.querySelector('button').addEventListener('click', () => loadProject(project.id));
    list.appendChild(div);
  });
}

async function loadProject(id) {
  const data = await jget(`/api/projects/${id}`);
  state.selectedProjectId = data.id;
  $('projectSelect').value = data.id;
  $('projectDetailTitle').textContent = data.name;
  $('projectDetailMeta').textContent = `${data.conversations.length} conversations - ${data.notes.length} notes`;
  const conversations = $('projectConversationList');
  conversations.innerHTML = '';
  if (!data.conversations.length) {
    conversations.innerHTML = '<div class="muted">No conversations attached.</div>';
  } else {
    data.conversations.forEach((conversation) => {
      const div = document.createElement('div');
      div.className = 'item';
      div.innerHTML = `<div class="item-title">#${conversation.id} ${escapeHtml(conversation.title || '(untitled)')}</div><div class="muted mini">${escapeHtml(conversation.updated_at || '')}</div>`;
      div.addEventListener('click', () => loadConversation(conversation.id));
      conversations.appendChild(div);
    });
  }
  const notes = $('projectNoteList');
  notes.innerHTML = '';
  if (!data.notes.length) {
    notes.innerHTML = '<div class="muted">No notes saved.</div>';
  } else {
    data.notes.forEach((note) => {
      const div = document.createElement('div');
      div.className = 'item';
      div.innerHTML = `<div class="item-title">${escapeHtml(note.title)}</div><div class="item-text">${escapeHtml(note.content || '')}</div>`;
      notes.appendChild(div);
    });
  }
  switchView('projects');
  return data;
}

async function loadConversation(id) {
  const data = await jget(`/api/conversations/${id}`);
  state.selectedConversationId = data.id;
  $('conversationTitle').textContent = `#${data.id} ${data.title || '(untitled)'}`;
  $('conversationMeta').textContent = `${data.provider || ''} - ${data.messages.length} messages`;
  $('replayConversationId').value = data.id;
  const box = $('conversationMessages');
  box.innerHTML = '';
  if (!data.messages.length) {
    box.innerHTML = '<div class="muted">No messages in this conversation.</div>';
  } else {
    data.messages.forEach((message) => box.appendChild(messageElement(message)));
  }
  switchView('conversations');
}

async function runSearch(queryOverride, semanticOverride) {
  const query = (queryOverride ?? $('searchQuery').value ?? '').trim();
  const semantic = semanticOverride ?? ($('searchMode').value === 'semantic');
  if (!query) return;
  const rows = await jget(`/api/search?q=${encodeURIComponent(query)}&semantic=${semantic ? 'true' : 'false'}&limit=40`);
  const target = $('searchResults');
  target.innerHTML = '';
  $('homeSearchPreview').classList.remove('muted');
  $('homeSearchPreview').textContent = rows.length ? `${rows.length} result(s) for "${query}"` : `No results for "${query}"`;
  if (!rows.length) {
    target.innerHTML = '<div class="muted">No results.</div>';
    return;
  }
  rows.forEach((row) => {
    const div = document.createElement('div');
    div.className = 'item';
    const score = row.score !== undefined ? `<span class="badge">score ${row.score}</span>` : '';
    div.innerHTML = `
      <div class="item-head">
        <div>
          <div class="item-title">#${row.message_id} ${escapeHtml(row.conversation_title || '(untitled)')}</div>
          <div class="muted mini">${escapeHtml(row.role || '')} - ${escapeHtml(row.mode || '')}</div>
        </div>
        <button class="ghost">Open</button>
      </div>
      <div class="item-text">${escapeHtml(row.snippet || '')}</div>
      <div class="badge-row">${score}</div>
    `;
    div.querySelector('button').addEventListener('click', () => loadConversation(row.conversation_id));
    target.appendChild(div);
  });
}

async function askVault(options = {}) {
  const button = options.button || $('askVaultBtn');
  const question = (options.question ?? $('askQuestion').value ?? '').trim();
  if (!question) return showToast('Ask a question first.', true);
  setBusy(button, true, 'Asking...');
  try {
    const data = await jpost('/api/ask', {
      question,
      project_id: options.projectId ?? (Number($('askProject').value || 0) || null),
      semantic: options.semantic ?? $('askSemantic').checked,
      use_llm: options.useLlm ?? $('askUseLlm').checked,
      limit: 8,
    });
    const answerTarget = options.answerTarget || $('askAnswer');
    const citationsTarget = options.citationsTarget || $('askCitations');
    answerTarget.classList.remove('muted');
    answerTarget.textContent = data.answer || '';
    citationsTarget.innerHTML = '';
    (data.citations || []).forEach((row, index) => {
      const div = document.createElement('div');
      div.className = 'item';
      const score = row.score !== undefined ? `<span class="badge">score ${row.score}</span>` : '';
      div.innerHTML = `
        <div class="item-head">
          <div>
            <div class="item-title">[${index + 1}] #${row.message_id} ${escapeHtml(row.conversation_title || '(untitled)')}</div>
            <div class="muted mini">${escapeHtml(row.role || '')} - ${escapeHtml(row.mode || '')}</div>
          </div>
          <button class="ghost">Open</button>
        </div>
        <div class="item-text">${escapeHtml(row.snippet || '')}</div>
        <div class="badge-row">${score}</div>
      `;
      div.querySelector('button').addEventListener('click', () => loadConversation(row.conversation_id));
      citationsTarget.appendChild(div);
    });
    if (data.warning) showToast(data.warning, true);
    return data;
  } catch (err) {
    (options.answerTarget || $('askAnswer')).textContent = err.message;
    showToast(err.message, true);
  } finally {
    setBusy(button, false);
  }
}

async function createProject() {
  const btn = $('createProjectBtn');
  setBusy(btn, true, 'Creating...');
  try {
    const data = await jpost('/api/projects', {
      name: $('projectName').value.trim(),
      system_prompt: $('projectPrompt').value.trim() || null,
      preferred_model: $('projectModel').value.trim() || null,
    });
    $('projectName').value = '';
    await loadProjects();
    await loadStats();
    await loadProject(data.project.id);
    showToast('Project created.');
  } catch (err) {
    showToast(err.message, true);
  } finally {
    setBusy(btn, false);
  }
}

async function attachConversationToProject() {
  const projectId = Number($('projectSelect').value || state.selectedProjectId || 0);
  const conversationId = Number($('projectConversationId').value || 0);
  if (!projectId || !conversationId) return showToast('Choose a project and conversation.', true);
  try {
    await jpost(`/api/projects/${projectId}/conversations`, { conversation_id: conversationId });
    $('projectConversationId').value = '';
    await loadProjects();
    await loadProject(projectId);
    showToast('Conversation attached.');
  } catch (err) {
    showToast(err.message, true);
  }
}

async function saveProjectNote() {
  const projectId = Number($('projectSelect').value || state.selectedProjectId || 0);
  if (!projectId) return showToast('Choose a project first.', true);
  try {
    await jpost(`/api/projects/${projectId}/notes`, {
      title: $('projectNoteTitle').value.trim(),
      content: $('projectNoteContent').value,
    });
    $('projectNoteTitle').value = '';
    $('projectNoteContent').value = '';
    await loadProjects();
    await loadProject(projectId);
    showToast('Project note saved.');
  } catch (err) {
    showToast(err.message, true);
  }
}

async function askSelectedProject() {
  const projectId = Number($('projectSelect').value || state.selectedProjectId || 0);
  if (!projectId) return showToast('Choose a project first.', true);
  const question = $('projectAskQuestion').value.trim();
  return askVault({
    button: $('projectAskBtn'),
    question,
    projectId,
    semantic: true,
    useLlm: $('askUseLlm').checked,
    answerTarget: $('projectAskOut'),
    citationsTarget: $('projectAskCitations'),
  });
}

async function deleteConversation(id) {
  if (!window.confirm(`Delete conversation #${id}?`)) return;
  try {
    await jdelete(`/api/conversations/${id}`);
    if (state.selectedConversationId === id) {
      state.selectedConversationId = null;
      $('conversationTitle').textContent = 'Conversation Viewer';
      $('conversationMeta').textContent = '';
      $('conversationMessages').classList.add('muted');
      $('conversationMessages').textContent = 'Select a conversation.';
    }
    await refreshAll();
    showToast('Conversation deleted.');
  } catch (err) {
    showToast(err.message, true);
  }
}

async function importSharedChat() {
  const btn = $('importSharedBtn');
  setBusy(btn, true, 'Importing...');
  try {
    const data = await jpost('/api/import/shared-chat', {
      url: $('sharedUrl').value.trim(),
      title: $('sharedTitle').value.trim() || null,
      save_raw_html: $('sharedSaveHtml').checked,
      no_embeddings: $('sharedNoEmbeddings').checked,
    });
    $('sharedImportOut').textContent = JSON.stringify(data, null, 2);
    showToast('Shared chat imported.');
    await refreshAll();
    if (data.conversation_id) loadConversation(data.conversation_id);
  } catch (err) {
    $('sharedImportOut').textContent = err.message;
    showToast(err.message, true);
  } finally {
    setBusy(btn, false);
  }
}

function inferImportSource(selected, name) {
  if (selected && selected !== 'auto') return selected;
  const value = String(name || '').toLowerCase();
  if (value.endsWith('.html') || value.endsWith('.htm')) return 'chatgpt_html';
  if (value.includes('claude') && value.endsWith('.json')) return 'claude';
  if (value.endsWith('.json')) return 'chatgpt';
  return 'documents';
}

async function importWizard() {
  const btn = $('wizardImportBtn');
  const out = $('wizardImportOut');
  const file = $('wizardFile').files[0];
  const pathOrUrl = $('wizardPath').value.trim();
  const selectedSource = $('wizardSource').value;
  setBusy(btn, true, 'Importing...');
  out.classList.remove('muted');
  out.textContent = 'Importing...';
  try {
    let data;
    if (file) {
      const form = new FormData();
      form.append('source', inferImportSource(selectedSource, file.name));
      form.append('recursive', $('wizardRecursive').checked ? 'true' : 'false');
      form.append('no_embeddings', $('wizardNoEmbeddings').checked ? 'true' : 'false');
      form.append('chunk_size', '260');
      form.append('chunk_overlap', '40');
      form.append('file', file);
      const res = await fetch('/api/import/upload', { method: 'POST', body: form });
      if (!res.ok) throw new Error(await errorText(res));
      data = await res.json();
    } else if (/^https?:\/\/chatgpt\.com\/share\//i.test(pathOrUrl)) {
      data = await jpost('/api/import/shared-chat', {
        url: pathOrUrl,
        title: null,
        save_raw_html: false,
        no_embeddings: $('wizardNoEmbeddings').checked,
      });
    } else if (pathOrUrl) {
      data = await jpost('/api/import/path', {
        path: pathOrUrl,
        source: inferImportSource(selectedSource, pathOrUrl),
        recursive: $('wizardRecursive').checked,
        no_embeddings: $('wizardNoEmbeddings').checked,
        chunk_size: 260,
        chunk_overlap: 40,
      });
    } else {
      throw new Error('Choose a file, shared URL, or local path.');
    }
    out.textContent = JSON.stringify(data, null, 2);
    showToast('Import complete.');
    await refreshAll();
    if (data.conversation_id) loadConversation(data.conversation_id);
  } catch (err) {
    out.textContent = err.message;
    showToast(err.message, true);
  } finally {
    setBusy(btn, false);
  }
}

async function importUpload() {
  const file = $('uploadFile').files[0];
  if (!file) return showToast('Choose a file first.', true);
  const btn = $('uploadImportBtn');
  setBusy(btn, true, 'Importing...');
  const form = new FormData();
  form.append('source', $('uploadSource').value);
  form.append('recursive', 'true');
  form.append('no_embeddings', $('uploadNoEmbeddings').checked ? 'true' : 'false');
  form.append('chunk_size', $('uploadChunkSize').value || '260');
  form.append('chunk_overlap', $('uploadChunkOverlap').value || '40');
  form.append('file', file);
  try {
    const res = await fetch('/api/import/upload', { method: 'POST', body: form });
    if (!res.ok) throw new Error(await errorText(res));
    const data = await res.json();
    $('uploadImportOut').textContent = JSON.stringify(data, null, 2);
    showToast('Upload imported.');
    await refreshAll();
  } catch (err) {
    $('uploadImportOut').textContent = err.message;
    showToast(err.message, true);
  } finally {
    setBusy(btn, false);
  }
}

async function importPath() {
  const btn = $('pathImportBtn');
  setBusy(btn, true, 'Importing...');
  try {
    const data = await jpost('/api/import/path', {
      path: $('pathImportValue').value.trim(),
      source: $('pathSource').value,
      recursive: $('pathRecursive').checked,
      no_embeddings: $('pathNoEmbeddings').checked,
      chunk_size: 260,
      chunk_overlap: 40,
    });
    $('pathImportOut').textContent = JSON.stringify(data, null, 2);
    showToast('Path imported.');
    await refreshAll();
  } catch (err) {
    $('pathImportOut').textContent = err.message;
    showToast(err.message, true);
  } finally {
    setBusy(btn, false);
  }
}

async function runCouncil() {
  const btn = $('runCouncilBtn');
  setBusy(btn, true, 'Running...');
  try {
    const data = await jpost('/api/council', { question: $('councilQuestion').value.trim() });
    $('councilOut').textContent = [
      `Conversation #${data.conversation_id || ''}`,
      '',
      'OpenAI:',
      data.openai || '',
      '',
      'Claude:',
      data.claude || '',
      '',
      'Ollama:',
      data.ollama || '',
      '',
      'Synthesis:',
      data.synthesis || '',
    ].join('\n');
    showToast('Council session complete.');
    await refreshAll();
  } catch (err) {
    $('councilOut').textContent = err.message;
    showToast(err.message, true);
  } finally {
    setBusy(btn, false);
  }
}

async function createChat() {
  const data = await jpost('/api/chat', { title: $('chatTitle').value.trim() || 'New chat' });
  state.currentChatId = data.conversation_id;
  $('chatLog').classList.remove('muted');
  $('chatLog').innerHTML = `<div class="message system"><div class="message-content">Chat #${data.conversation_id} created.</div></div>`;
  await refreshAll();
  showToast('Chat created.');
}

async function sendChat() {
  if (!state.currentChatId) await createChat();
  const text = $('chatMessage').value.trim();
  if (!text) return;
  const btn = $('sendChatBtn');
  setBusy(btn, true, 'Sending...');
  appendChatMessage('user', text);
  $('chatMessage').value = '';
  try {
    const data = await jpost(`/api/chat/${state.currentChatId}/send`, {
      message: text,
      backend: $('chatBackend').value || null,
      model: $('chatModel').value.trim() || null,
    });
    appendChatMessage('assistant', data.reply || '');
    await refreshAll();
  } catch (err) {
    appendChatMessage('system', err.message);
    showToast(err.message, true);
  } finally {
    setBusy(btn, false);
  }
}

function appendChatMessage(role, content) {
  const box = $('chatLog');
  if (box.classList.contains('muted')) {
    box.classList.remove('muted');
    box.innerHTML = '';
  }
  const div = document.createElement('div');
  div.className = `message ${role}`;
  div.innerHTML = `<div class="message-head"><strong>${escapeHtml(role)}</strong></div><div class="message-content">${escapeHtml(content)}</div>`;
  box.appendChild(div);
  box.scrollTop = box.scrollHeight;
}

async function summarize() {
  const btn = $('summaryBtn');
  setBusy(btn, true, 'Summarizing...');
  try {
    const data = await jpost('/api/summary', { range: $('summaryRange').value, use_llm: $('summaryUseLlm').checked });
    $('summaryOut').textContent = JSON.stringify(data, null, 2);
  } catch (err) {
    $('summaryOut').textContent = err.message;
    showToast(err.message, true);
  } finally {
    setBusy(btn, false);
  }
}

async function recommend() {
  const btn = $('recommendBtn');
  setBusy(btn, true, 'Working...');
  try {
    const data = await jpost('/api/recommend', { use_llm: $('recommendUseLlm').checked });
    $('recommendOut').textContent = JSON.stringify(data, null, 2);
  } catch (err) {
    $('recommendOut').textContent = err.message;
    showToast(err.message, true);
  } finally {
    setBusy(btn, false);
  }
}

async function loadReplay() {
  const id = Number($('replayConversationId').value || state.selectedConversationId || 0);
  if (!id) return showToast('Choose a conversation first.', true);
  const data = await jget(`/api/replay/${id}`);
  state.replayMessages = data.messages || [];
  const box = $('replayOut');
  box.innerHTML = '';
  if (!state.replayMessages.length) {
    box.innerHTML = '<div class="muted">No messages to replay.</div>';
    return;
  }
  state.replayMessages.forEach((message) => box.appendChild(messageElement(message)));
}

function playReplay() {
  stopReplay();
  const box = $('replayOut');
  box.innerHTML = '';
  let index = 0;
  const speed = Number($('replaySpeed').value || 1);
  const tick = () => {
    if (index >= state.replayMessages.length) return;
    const message = state.replayMessages[index++];
    box.appendChild(messageElement(message));
    box.scrollTop = box.scrollHeight;
    const next = state.replayMessages[index];
    if (next) {
      const delay = Math.max(150, ((next.delay_s || 0.5) * 1000) / speed);
      state.replayTimer = window.setTimeout(tick, delay);
    }
  };
  tick();
}

function stopReplay() {
  if (state.replayTimer) window.clearTimeout(state.replayTimer);
  state.replayTimer = null;
}

async function loadContext() {
  const id = Number($('contextMessageId').value || 0);
  if (!id) return;
  try {
    const data = await jget(`/api/messages/${id}/context?window=${Number($('contextWindow').value || 6)}`);
    const box = $('contextOut');
    box.classList.remove('muted');
    box.innerHTML = '';
    data.items.forEach((item) => {
      const div = document.createElement('div');
      div.className = `message ${item.role}`;
      div.style.marginBottom = '8px';
      div.innerHTML = `<div class="message-head"><strong>#${item.id} ${escapeHtml(item.role)}</strong>${item.is_target ? '<span class="badge amber">target</span>' : ''}</div><div class="message-content">${escapeHtml(item.content || '')}</div>`;
      box.appendChild(div);
    });
  } catch (err) {
    $('contextOut').textContent = err.message;
    showToast(err.message, true);
  }
}

async function addTag() {
  const id = Number($('tagMessageId').value || 0);
  const tag = $('tagName').value.trim();
  if (!id || !tag) return;
  try {
    const data = await jpost(`/api/messages/${id}/tags`, { tag });
    $('tagOut').textContent = JSON.stringify(data, null, 2);
    await loadStats();
  } catch (err) {
    $('tagOut').textContent = err.message;
    showToast(err.message, true);
  }
}

async function searchTag() {
  const tag = $('tagSearchName').value.trim();
  if (!tag) return;
  const rows = await jget(`/api/tags/${encodeURIComponent(tag)}`);
  const target = $('tagSearchOut');
  target.innerHTML = '';
  if (!rows.length) {
    target.innerHTML = '<div class="muted">No tagged messages found.</div>';
    return;
  }
  rows.forEach((row) => {
    const div = document.createElement('div');
    div.className = 'item';
    div.innerHTML = `<div class="item-head"><div><div class="item-title">#${row.message_id} ${escapeHtml(row.conversation_title)}</div><div class="muted mini">${escapeHtml(row.role)}</div></div><button class="ghost">Open</button></div><div class="item-text">${escapeHtml(row.snippet || '')}</div>`;
    div.querySelector('button').addEventListener('click', () => loadConversation(row.conversation_id));
    target.appendChild(div);
  });
}

async function saveSettings() {
  const btn = $('saveSettingsBtn');
  setBusy(btn, true, 'Saving...');
  try {
    const data = await jpost('/api/settings', {
      backend: $('settingsBackend').value,
      offline: $('settingsOffline').checked,
      openai_api_key: $('settingsOpenAIKey').value.trim() || null,
      anthropic_api_key: $('settingsAnthropicKey').value.trim() || null,
      openai_model: $('settingsOpenAIModel').value.trim() || null,
      anthropic_model: $('settingsAnthropicModel').value.trim() || null,
      ollama_host: $('settingsOllamaHost').value.trim() || null,
      ollama_model: $('settingsOllamaModel').value.trim() || null,
      embeddings_model: $('settingsEmbeddingsModel').value.trim() || null,
      clear_openai_key: $('settingsClearOpenAI').checked,
      clear_anthropic_key: $('settingsClearAnthropic').checked,
    });
    state.settings = data.settings;
    $('settingsOpenAIKey').value = '';
    $('settingsAnthropicKey').value = '';
    $('settingsClearOpenAI').checked = false;
    $('settingsClearAnthropic').checked = false;
    $('settingsOut').textContent = `Saved to ${data.env_file}`;
    await loadSettings();
    await loadStats();
    showToast('Settings saved.');
  } catch (err) {
    $('settingsOut').textContent = err.message;
    showToast(err.message, true);
  } finally {
    setBusy(btn, false);
  }
}

async function testModel(backend) {
  const buttons = {
    openai: $('testOpenAIBtn'),
    anthropic: $('testAnthropicBtn'),
    ollama: $('testOllamaBtn'),
  };
  const models = {
    openai: $('settingsOpenAIModel').value.trim() || null,
    anthropic: $('settingsAnthropicModel').value.trim() || null,
    ollama: $('settingsOllamaModel').value.trim() || null,
  };
  const btn = buttons[backend];
  const out = $('modelTestOut');
  setBusy(btn, true, 'Testing...');
  out.classList.remove('muted');
  out.textContent = 'Testing...';
  try {
    const data = await jpost('/api/settings/test-model', {
      backend,
      model: models[backend],
      openai_api_key: $('settingsOpenAIKey').value.trim() || null,
      anthropic_api_key: $('settingsAnthropicKey').value.trim() || null,
      ollama_host: $('settingsOllamaHost').value.trim() || null,
    });
    out.textContent = `${data.ok ? 'OK' : 'Needs attention'}: ${data.detail || ''}`;
    showToast(data.ok ? `${backend} test passed.` : `${backend} test needs attention.`, !data.ok);
    if (backend === 'ollama') await loadDoctor();
  } catch (err) {
    out.textContent = err.message;
    showToast(err.message, true);
  } finally {
    setBusy(btn, false);
  }
}

async function showSetupIfNeeded() {
  try {
    const data = await jget('/api/setup/status');
    if (data.needs_setup) {
      $('setupOverlay').hidden = false;
    }
  } catch {
    // The dashboard can still run if setup status is unavailable.
  }
}

async function saveSetup(complete = true) {
  const btn = complete ? $('setupSaveBtn') : $('setupSkipBtn');
  setBusy(btn, true, complete ? 'Saving...' : 'Skipping...');
  try {
    const data = await jpost('/api/settings', {
      backend: $('setupBackend').value,
      offline: $('setupOffline').checked,
      openai_api_key: $('setupOpenAIKey').value.trim() || null,
      anthropic_api_key: $('setupAnthropicKey').value.trim() || null,
      ollama_host: $('setupOllamaHost').value.trim() || null,
      ollama_model: $('setupOllamaModel').value.trim() || null,
      setup_complete: complete,
    });
    state.settings = data.settings;
    $('setupOpenAIKey').value = '';
    $('setupAnthropicKey').value = '';
    $('setupOverlay').hidden = true;
    await refreshAll();
    showToast(complete ? 'Setup saved.' : 'Setup skipped.');
  } catch (err) {
    $('setupOut').textContent = err.message;
    showToast(err.message, true);
  } finally {
    setBusy(btn, false);
  }
}

async function refreshAll() {
  await Promise.all([loadSettings(), loadStats(), loadConversations(), loadProjects()]);
}

function wireActions() {
  $('globalSearchBtn').addEventListener('click', () => {
    $('searchQuery').value = $('globalSearch').value;
    $('searchMode').value = $('globalSemantic').checked ? 'semantic' : 'keyword';
    switchView('search');
    runSearch($('globalSearch').value, $('globalSemantic').checked);
  });
  $('globalSearch').addEventListener('keydown', (event) => {
    if (event.key === 'Enter') $('globalSearchBtn').click();
  });
  $('searchBtn').addEventListener('click', () => runSearch());
  $('searchQuery').addEventListener('keydown', (event) => {
    if (event.key === 'Enter') runSearch();
  });
  $('refreshConversations').addEventListener('click', loadConversations);
  $('runDoctorBtn').addEventListener('click', loadDoctor);
  $('askVaultBtn').addEventListener('click', () => askVault());
  $('createProjectBtn').addEventListener('click', createProject);
  $('projectSelect').addEventListener('change', () => {
    const id = Number($('projectSelect').value || 0);
    if (id) loadProject(id);
  });
  $('attachProjectConversationBtn').addEventListener('click', attachConversationToProject);
  $('saveProjectNoteBtn').addEventListener('click', saveProjectNote);
  $('projectAskBtn').addEventListener('click', askSelectedProject);
  $('importSharedBtn').addEventListener('click', importSharedChat);
  $('wizardImportBtn').addEventListener('click', importWizard);
  $('uploadImportBtn').addEventListener('click', importUpload);
  $('pathImportBtn').addEventListener('click', importPath);
  $('runCouncilBtn').addEventListener('click', runCouncil);
  $('newChatTop').addEventListener('click', () => { switchView('chat'); createChat(); });
  $('newChatBtn').addEventListener('click', createChat);
  $('sendChatBtn').addEventListener('click', sendChat);
  $('summaryBtn').addEventListener('click', summarize);
  $('recommendBtn').addEventListener('click', recommend);
  $('loadReplayBtn').addEventListener('click', loadReplay);
  $('playReplayBtn').addEventListener('click', playReplay);
  $('stopReplayBtn').addEventListener('click', stopReplay);
  $('loadContextBtn').addEventListener('click', loadContext);
  $('addTagBtn').addEventListener('click', addTag);
  $('searchTagBtn').addEventListener('click', searchTag);
  $('saveSettingsBtn').addEventListener('click', saveSettings);
  $('testOpenAIBtn').addEventListener('click', () => testModel('openai'));
  $('testAnthropicBtn').addEventListener('click', () => testModel('anthropic'));
  $('testOllamaBtn').addEventListener('click', () => testModel('ollama'));
  $('setupSaveBtn').addEventListener('click', () => saveSetup(true));
  $('setupSkipBtn').addEventListener('click', () => saveSetup(false));
}

async function init() {
  wireNavigation();
  wireActions();
  try {
    await refreshAll();
    switchView(initialView());
    await showSetupIfNeeded();
  } catch (err) {
    showToast(err.message, true);
  }
}

init();

