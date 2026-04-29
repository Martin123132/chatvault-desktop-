document.getElementById('save').addEventListener('click', () => {
  const project = document.getElementById('project').value;
  const tags = document.getElementById('tags').value;
  chrome.runtime.sendMessage({ type: 'SAVE_FROM_POPUP', project, tags }, (resp) => {
    document.getElementById('status').textContent = resp?.ok ? 'Saved successfully' : `Failed: ${resp?.error || 'unknown'}`;
  });
});
