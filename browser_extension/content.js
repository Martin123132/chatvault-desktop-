function extractMessages() {
  const blocks = Array.from(document.querySelectorAll('main [data-message-author-role]'));
  return blocks.map((el) => ({
    role: el.getAttribute('data-message-author-role') === 'user' ? 'user' : 'assistant',
    content: el.innerText || ''
  })).filter(m => m.content.trim());
}

function getTitle() {
  const h = document.querySelector('h1');
  return (h && h.innerText) || document.title || 'ChatGPT Capture';
}

function toMarkdown(messages) {
  return messages.map(m => `### ${m.role}\n\n${m.content}`).join('\n\n');
}

function nearestAssistantFromSelection() {
  const sel = window.getSelection();
  if (!sel || !sel.anchorNode) return null;
  let n = sel.anchorNode.nodeType === 1 ? sel.anchorNode : sel.anchorNode.parentElement;
  while (n && n !== document.body) {
    if (n.getAttribute && n.getAttribute('data-message-author-role') === 'assistant') {
      return { role: 'assistant', content: n.innerText || '' };
    }
    n = n.parentElement;
  }
  return null;
}

chrome.runtime.onMessage.addListener((req, _sender, sendResponse) => {
  if (req.type === 'CAPTURE_THREAD') {
    const messages = extractMessages();
    sendResponse({ ok: true, payload: { messages, markdown: toMarkdown(messages), conversation_title: getTitle(), page_url: location.href } });
  }
  if (req.type === 'CAPTURE_SELECTION') {
    const text = (window.getSelection() || '').toString();
    sendResponse({ ok: true, payload: { messages: [{ role: 'user', content: text }], markdown: text, conversation_title: getTitle(), page_url: location.href } });
  }
  if (req.type === 'CAPTURE_NEAREST_ASSISTANT') {
    const msg = nearestAssistantFromSelection();
    sendResponse({ ok: !!msg, payload: { messages: msg ? [msg] : [], markdown: msg ? msg.content : '', conversation_title: getTitle(), page_url: location.href } });
  }
  return true;
});
