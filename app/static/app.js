/* CloudLab deliberately uses browser-native modules and a small API surface. */
const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
const state = { user: null, csrf: '', templates: [], workspaces: [], system: null, page: 'dashboard', editor: null, dirty: false, authMode: 'login', socket: null, terminal: null, fit: null, backupWorkspace: null, file: null, loading: false };
const escapeHTML = (value) => String(value ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const date = (seconds) => new Date(seconds * 1000).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
const templateFor = (id) => state.templates.find((t) => t.id === id);
const workspaceURL = (id, suffix = '') => `/api/workspaces/${id}${suffix}`;

async function api(url, options = {}) {
  const response = await fetch(url, { ...options, headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': state.csrf, ...options.headers }, credentials: 'same-origin' });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    if (response.status === 401 && !url.includes('/auth/')) { showAuth(); }
    const message = Array.isArray(data.detail) ? data.detail.map((x) => x.msg.replace('Value error, ', '')).join(' ') : data.detail;
    throw new Error(message || `Request failed (${response.status}). Please try again.`);
  }
  return data;
}
const post = (url, body) => api(url, { method: 'POST', body: body ? JSON.stringify(body) : undefined });
function toast(message, error = false) {
  const item = document.createElement('div'); item.className = `toast${error ? ' error' : ''}`; item.textContent = message;
  $('#toasts').append(item); setTimeout(() => item.remove(), error ? 8500 : 4500);
}
async function busy(button, operation) {
  if (button?.disabled) return;
  const original = button?.innerHTML;
  if (button) { button.disabled = true; button.textContent = 'Working…'; }
  try { return await operation(); } catch (error) { toast(error.message, true); }
  finally { if (button) { button.disabled = false; button.innerHTML = original; } }
}
function showAuth() {
  disconnectTerminal(); state.user = null; state.editor = null;
  $('#editor-screen').classList.add('hidden'); $('#app-shell').classList.add('hidden'); $('#auth-screen').classList.remove('hidden'); $('#loading').classList.add('hidden');
}
async function enterApp(session) {
  state.user = session.user; state.csrf = session.csrf;
  $('#auth-screen').classList.add('hidden'); $('#app-shell').classList.remove('hidden'); $('#loading').classList.add('hidden');
  $('#profile-name').textContent = state.user.name; $('#profile-role').textContent = state.user.role;
  $('#avatar').textContent = state.user.name.slice(0, 2).toUpperCase(); $('#admin-nav').classList.toggle('hidden', state.user.role !== 'admin');
  state.templates = await api('/api/templates');
  await refresh(); render();
}
async function refresh() {
  const results = await Promise.allSettled([api('/api/workspaces'), api('/api/system')]);
  if (results[0].status === 'fulfilled') state.workspaces = results[0].value;
  if (results[1].status === 'fulfilled') state.system = results[1].value;
  if (results[0].status === 'rejected') toast(results[0].reason.message, true);
  $('#lab-count').textContent = state.workspaces.filter((w) => w.mode === 'lab').length;
  $('#workspace-count').textContent = state.workspaces.filter((w) => w.mode === 'workspace').length;
  const ready = state.system?.runtime.ready;
  $('#engine-dot').classList.toggle('offline', !ready); $('#engine-title').textContent = ready ? 'Engine is ready' : 'Engine unavailable';
  $('#engine-description').textContent = ready ? `Auto-stop after ${state.system.idle_minutes} minutes of inactivity` : 'See the setup guide to connect Docker';
  $('#storage-label').textContent = state.system?.backup_storage === 's3' ? 'S3 cloud backups connected' : 'Local backups enabled';
}

function templateCards() {
  return `<div class="template-grid">${state.templates.map((t) => `<article class="template-card"><div class="template-card-top"><span class="template-icon">${escapeHTML(t.icon)}</span><span class="tag">${escapeHTML(t.tag)}</span></div><h3>${escapeHTML(t.name)}</h3><p>${escapeHTML(t.description)}</p><div class="template-bottom"><span>${t.cpu} vCPU &nbsp;·&nbsp; ${t.memory_mb} MB RAM</span><button class="launch-arrow" data-launch="${t.id}" title="Launch ${escapeHTML(t.name)}" aria-label="Launch ${escapeHTML(t.name)}">↗</button></div></article>`).join('')}</div>`;
}
function stats() {
  const running = state.workspaces.filter((w) => w.status === 'running');
  const data = [['Saved environments', state.workspaces.length, `/ ${state.system?.max_workspaces || 5}`, 'Ready whenever you are', '▱'], ['Running now', running.length, `/ ${state.system?.max_running || 2}`, 'Your active environments', '▷'], ['Reserved memory', running.reduce((n, w) => n + w.memory_mb, 0), 'MB', 'Allocated across running spaces', '▥'], ['Auto-stop after', state.system?.idle_minutes || 30, 'min', 'Of keyboard or file inactivity', '◷']];
  return `<div class="stats">${data.map(([name, value, unit, caption, icon]) => `<div class="stat"><div class="stat-top"><span>${name}</span><span class="stat-icon">${icon}</span></div><div class="stat-value">${value}<small>${unit}</small></div><div class="stat-caption">${caption}</div></div>`).join('')}</div>`;
}
function workspaceTable(workspaces, admin = false) {
  if (!workspaces.length) return `<div class="workspace-panel"><div class="empty-state"><span class="empty-icon">▱</span><h3>Your next idea starts here.</h3><p>Launch an environment above. Your saved workspaces will appear here.</p><button class="button" data-create>+ Create your first workspace</button></div></div>`;
  return `<div class="workspace-panel table-scroll"><table><thead><tr><th>ENVIRONMENT</th><th>STATUS</th><th>${admin ? 'OWNER' : 'RESOURCES'}</th><th>CREATED</th><th></th></tr></thead><tbody>${workspaces.map((w) => {
    const t = templateFor(w.template);
    return `<tr data-workspace="${w.id}"><td><div class="workspace-name"><span class="template-icon">${escapeHTML(t?.icon)}</span><div><strong>${escapeHTML(w.name)}</strong><small>${escapeHTML(t?.name)} · ${w.mode === 'lab' ? 'Virtual lab' : 'Workspace'}</small></div></div></td><td><span class="badge ${w.status === 'running' ? '' : 'stopped'}">${escapeHTML(w.status)}</span></td><td class="muted">${admin ? escapeHTML(w.owner_email) : `${w.cpu} CPU · ${w.memory_mb} MB`}</td><td class="muted">${date(w.created_at)}</td><td><div class="row-actions">${w.status === 'running' ? `<button class="button" data-action="open" data-id="${w.id}">Open ↗</button><button class="icon-button" data-action="stop" data-id="${w.id}" title="Stop workspace" aria-label="Stop ${escapeHTML(w.name)}">Ⅱ</button>` : `<button class="button" data-action="start" data-id="${w.id}">Resume ▷</button>`}<button class="icon-button" data-action="backups" data-id="${w.id}" title="Backups" aria-label="Backups for ${escapeHTML(w.name)}">⇩</button><button class="icon-button" data-action="delete" data-id="${w.id}" title="Delete workspace" aria-label="Delete ${escapeHTML(w.name)}">×</button></div></td></tr>`;
  }).join('')}</tbody></table></div>`;
}
function heading(title, subtitle, create = true) { return `<div class="page-heading"><div><h1>${escapeHTML(title)}</h1><p>${escapeHTML(subtitle)}</p></div>${create ? '<button class="button primary" data-create>+ &nbsp; New workspace</button>' : ''}</div>`; }
function guide() {
  return heading('From an idea to a running workspace.', 'A quick guide to finding your feet in CloudLab.', false) + `<div class="guide-grid"><article class="guide-card"><span class="guide-number">01</span><h3>Choose your starting point</h3><p>Pick Linux Basics, Python Lab, or Web Development. Choose <strong>Virtual lab</strong> for guided tasks, or <strong>Workspace</strong> to work on your own project.</p></article><article class="guide-card"><span class="guide-number">02</span><h3>Edit, run, and explore</h3><p>Open a file in the editor. Save with the button or <code>Ctrl / ⌘ + S</code>. Run the starter program or type commands in the terminal. New files appear when you refresh the explorer.</p></article><article class="guide-card"><span class="guide-number">03</span><h3>Pause without losing your place</h3><p>Stop an environment to free its CPU and memory. Files under <code>/workspace</code> stay saved in a Docker volume. Resume when you’re ready. Unsaved editor text must be saved before closing.</p></article><article class="guide-card"><span class="guide-number">04</span><h3>Keep a copy of your work</h3><p>Stop your workspace, open Backups, and create a snapshot. Download it or restore it later. Restoring replaces the current files. Backups use ${state.system?.backup_storage === 's3' ? 'your configured S3 bucket' : 'local server storage; the deployment guide explains how to enable S3'}.</p></article><article class="guide-card"><h3>Resource limits & isolation</h3><p>Each environment has its own filesystem, CPU/RAM allowance, and process limit. Containers run as a regular user without internet access. Python, Node.js, npm, and Bash are preinstalled. Add extra dependencies when building the workspace image.</p></article><article class="guide-card"><h3>What keeps a workspace active?</h3><p>Typing in the terminal or saving/deleting a file resets its idle timer. Leaving a tab open does not. After ${state.system?.idle_minutes || 30} minutes without these actions, the workspace stops, including running programs. Your saved files remain.</p></article></div>`;
}
async function render() {
  if (!state.user) return;
  const titles = { dashboard: 'Overview', labs: 'Virtual labs', workspaces: 'Workspaces', templates: 'Template library', admin: 'Administration', guide: 'Getting started' };
  $('#breadcrumb').textContent = titles[state.page];
  $$('[data-nav]').forEach((el) => el.classList.toggle('active', el.dataset.nav === state.page));
  let html = '';
  if (state.page === 'dashboard') {
    const name = state.user.name.split(' ')[0];
    html = heading(`Welcome to your space, ${name}.`, 'A fresh environment. A new experiment. What will you build today?') + `<section class="hero"><div><span class="eyebrow">LESS SETUP. MORE EXPLORING.</span><h2>Big ideas need a little space.</h2><p>Spin up an isolated environment in seconds.<br>Your tools are ready. Your files stay with you.</p><a href="#templates" class="hero-link">Find your starting point <span>↗</span></a></div><div class="hero-art" aria-hidden="true"><div class="mini-window"><div class="window-dots">•••</div><div class="window-code">$ workspace start<br>✓ environment ready<br><span>▌</span></div></div><div class="float-chip">&lt;/&gt;</div></div></section>` + stats() + `<div class="section-heading"><div><h2>Start with a template</h2><p>A few good starting points, ready to make your own.</p></div><a href="#templates">Explore templates &nbsp;↗</a></div>` + templateCards() + `<div class="section-heading"><h2>Your environments <span class="muted">(${state.workspaces.length})</span></h2><input id="workspace-search" class="search" aria-label="Search environments" placeholder="⌕  Find an environment"></div><div id="workspace-results">${workspaceTable(state.workspaces)}</div><div class="helper-banner"><span>◇</span><div><strong>A pause, not a goodbye.</strong> Stopped environments keep your files and free up resources.</div><button class="text-button" data-nav="guide">How it works ↗</button></div>`;
  } else if (state.page === 'templates') html = heading('A head start for your next idea.', 'Three ready-to-use environments. Choose one and make it yours.') + templateCards();
  else if (state.page === 'guide') html = guide();
  else if (state.page === 'admin') {
    $('#main-content').innerHTML = heading('Your server, at a glance.', 'People, environments, and the activity behind them.', false) + '<p class="muted">Loading server activity…</p>';
    try {
      const data = await api('/api/admin/overview');
      if (state.page !== 'admin') return;
      state.adminWorkspaces = data.workspaces;
      html = heading('Your server, at a glance.', `${data.users.length} users · ${data.workspaces.length} environments · ${data.workspaces.filter((w) => w.status === 'running').length} running`, false) + `<div class="section-heading"><h2>All environments</h2></div>` + workspaceTable(data.workspaces, true) + `<div class="section-heading"><h2>Registered users</h2></div><div class="workspace-panel table-scroll"><table><thead><tr><th>NAME</th><th>EMAIL</th><th>ROLE</th><th>JOINED</th></tr></thead><tbody>${data.users.map((u) => `<tr><td>${escapeHTML(u.name)}</td><td>${escapeHTML(u.email)}</td><td>${u.role}</td><td>${date(u.created_at)}</td></tr>`).join('')}</tbody></table></div><div class="section-heading"><h2>Recent activity</h2></div><div class="workspace-panel admin-events">${data.events.map((e) => `<div class="event"><div>${escapeHTML(e.action.replaceAll('_', ' '))}<small>${escapeHTML(e.email || 'System')} ${e.detail ? '· ' + escapeHTML(e.detail) : ''}</small></div><span class="muted">${date(e.created_at)}</span></div>`).join('') || '<p class="muted">No activity yet.</p>'}</div>`;
    } catch (error) { html = `<p class="error">${escapeHTML(error.message)}</p>`; }
  } else {
    const lab = state.page === 'labs';
    html = heading(lab ? 'Learn by doing.' : 'Your ideas, in progress.', lab ? 'A personal lab for every question worth exploring.' : 'Your saved projects. Ready when inspiration strikes.') + `<div class="section-heading"><h2>${lab ? 'Your virtual labs' : 'Your workspaces'}</h2><input id="workspace-search" class="search" aria-label="Search environments" placeholder="⌕  Find an environment"></div><div id="workspace-results">${workspaceTable(state.workspaces.filter((w) => w.mode === (lab ? 'lab' : 'workspace')))}</div>`;
  }
  $('#main-content').innerHTML = html;
}
function openCreate(template = 'python') {
  $('#create-form').reset(); $('#create-error').textContent = ''; $('#create-template').value = template;
  $('#create-form').elements.mode.value = state.page === 'workspaces' ? 'workspace' : 'lab';
  $('#create-dialog').showModal(); $('#create-name').focus();
}
async function workspaceAction(action, id, button) {
  const workspace = [...state.workspaces, ...(state.adminWorkspaces || [])].find((w) => w.id === id);
  if (action === 'open') return busy(button, () => openEditor(workspace));
  if (action === 'backups') return busy(button, () => openBackups(workspace));
  if (action === 'delete' && !confirm(`Delete “${workspace.name}” and ALL its files and backups? This cannot be undone.`)) return;
  await busy(button, async () => {
    if (action === 'delete') await api(workspaceURL(id), { method: 'DELETE' });
    else await post(workspaceURL(id, `/${action}`));
    toast(action === 'delete' ? 'Workspace deleted.' : action === 'start' ? 'Workspace is ready. Open it to continue.' : 'Workspace stopped. Your files are saved.');
    await refresh(); await render();
  });
}
async function openBackups(workspace) {
  state.backupWorkspace = workspace;
  $('#backup-subtitle').textContent = `${workspace.name} · Stop the workspace before creating or restoring a backup.`;
  $('#backup-create').disabled = workspace.status === 'running';
  await renderBackups(); $('#backups-dialog').showModal();
}
async function renderBackups() {
  const workspace = state.backupWorkspace;
  const backups = await api(workspaceURL(workspace.id, '/backups'));
  $('#backup-list').innerHTML = backups.map((b) => `<div class="backup-row"><div><strong>${date(b.created_at)}</strong><small>${(b.size / 1024).toFixed(1)} KiB · ${b.storage === 's3' ? 'S3 cloud' : 'Local server'}</small></div><div class="backup-actions"><a class="text-button" href="${workspaceURL(workspace.id, `/backups/${b.id}/download`)}" title="Download backup">Download</a><button class="text-button" data-restore="${b.id}" ${workspace.status === 'running' ? 'disabled' : ''}>Restore</button><button class="icon-button" data-delete-backup="${b.id}" aria-label="Delete backup">×</button></div></div>`).join('') || '<div class="empty-state"><h3>No backups yet.</h3><p>Create a snapshot to keep a copy of your files.</p></div>';
}

async function openEditor(workspace) {
  state.editor = workspace; state.file = null; state.dirty = false;
  $('#editor-name').textContent = workspace.name; $('#editor-template').textContent = templateFor(workspace.template).name;
  $('#code-editor').value = ''; $('#current-file').textContent = 'Select a file'; $('#save-status').textContent = 'Saved';
  $('#preview-button').classList.toggle('hidden', workspace.template !== 'web');
  $('#lab-instructions').innerHTML = workspace.mode === 'lab' ? `<h3>YOUR LAB CHECKLIST</h3>${templateFor(workspace.template).tasks.map((task, i) => `<label class="task-item"><input type="checkbox" data-task="${i}" ${localStorage.getItem(`task:${state.user.id}:${workspace.id}:${i}`) === 'done' ? 'checked' : ''}><span>${escapeHTML(task)}</span></label>`).join('')}` : '';
  $('#editor-screen').classList.remove('hidden');
  try { await loadFiles(); await selectFile(templateFor(workspace.template).entry); } catch (error) { toast(error.message, true); }
  connectTerminal(); updateMetrics();
}
async function loadFiles() {
  const result = await api(workspaceURL(state.editor.id, '/files'));
  $('#file-tree').innerHTML = result.files.map((f) => `<button class="file-item ${f.path === state.file ? 'active' : ''}" data-file="${escapeHTML(f.path)}" title="${escapeHTML(f.path)}">▱ ${escapeHTML(f.path)}</button>`).join('');
  if (result.truncated) toast('Showing the first 2,000 files. Use the terminal to explore more.');
}
async function selectFile(path) {
  if (state.dirty && !confirm('Discard unsaved changes to the current file?')) return;
  const data = await api(workspaceURL(state.editor.id, `/file?path=${encodeURIComponent(path)}`));
  state.file = path; state.dirty = false; $('#code-editor').value = data.content;
  $('#current-file').textContent = path; $('#save-status').textContent = 'Saved';
  $$('.file-item').forEach((el) => el.classList.toggle('active', el.dataset.file === path));
}
async function saveFile() {
  if (!state.file) throw new Error('Select or create a file first.');
  const path = state.file, content = $('#code-editor').value;
  await api(workspaceURL(state.editor.id, '/file'), { method: 'PUT', body: JSON.stringify({ path, content }) });
  if (state.file === path && $('#code-editor').value === content) { state.dirty = false; $('#save-status').textContent = 'Saved'; }
}
function disconnectTerminal() {
  if (state.socket) { state.socket.onclose = null; state.socket.close(); state.socket = null; }
  state.terminal?.dispose(); state.terminal = null; state.fit = null;
}
function connectTerminal() {
  disconnectTerminal();
  state.terminal = new Terminal({ cursorBlink: true, fontSize: 12, fontFamily: 'Consolas, monospace', theme: { background: '#122c25', foreground: '#d6e5cd', cursor: '#bdce9c', green: '#91bc78' }, scrollback: 3000 });
  state.fit = new FitAddon.FitAddon(); state.terminal.loadAddon(state.fit); state.terminal.open($('#terminal')); state.fit.fit();
  const socket = new WebSocket(`${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}${workspaceURL(state.editor.id, '/terminal')}`);
  state.socket = socket; socket.binaryType = 'arraybuffer'; $('#terminal-status').textContent = 'Connecting…';
  socket.onopen = () => { socket.send(JSON.stringify({ csrf: state.csrf })); $('#terminal-status').textContent = 'Connected'; resizeTerminal(); };
  socket.onmessage = (event) => state.terminal?.write(event.data instanceof ArrayBuffer ? new Uint8Array(event.data) : event.data);
  socket.onclose = () => { $('#terminal-status').textContent = 'Disconnected — resume the workspace or reconnect'; };
  socket.onerror = () => { $('#terminal-status').textContent = 'Connection failed'; };
  state.terminal.onData((data) => { if (socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ type: 'input', data })); });
}
function resizeTerminal() {
  state.fit?.fit();
  if (state.socket?.readyState === WebSocket.OPEN && state.terminal) state.socket.send(JSON.stringify({ type: 'resize', cols: state.terminal.cols, rows: state.terminal.rows }));
}
async function updateMetrics() {
  if (!state.editor) return;
  try { const metrics = await api(workspaceURL(state.editor.id, '/metrics')); $('#editor-metrics').textContent = `${metrics.cpu_percent}% CPU · ${metrics.memory_mb} MB used`; }
  catch { $('#editor-metrics').textContent = 'Workspace is stopped or unavailable'; }
}
function closeEditor() {
  if (state.dirty && !confirm('Discard unsaved editor changes and return to the dashboard?')) return;
  disconnectTerminal(); state.editor = null; state.dirty = false;
  $('#editor-screen').classList.add('hidden'); refresh().then(render).catch((e) => toast(e.message, true));
}

document.addEventListener('click', (event) => {
  const target = event.target.closest('button, a'); if (!target) return;
  if (target.hasAttribute('data-create')) openCreate();
  if (target.dataset.launch) openCreate(target.dataset.launch);
  if (target.dataset.nav) { location.hash = target.dataset.nav; }
  if (target.hasAttribute('data-close')) target.closest('dialog').close();
  if (target.dataset.action) workspaceAction(target.dataset.action, target.dataset.id, target);
  if (target.dataset.file) busy(null, () => selectFile(target.dataset.file));
  if (target.dataset.restore && confirm('Restore this backup? It will replace every current file in this workspace.')) busy(target, async () => { await post(workspaceURL(state.backupWorkspace.id, `/backups/${target.dataset.restore}/restore`)); toast('Backup restored. Resume your workspace to see the files.'); });
  if (target.dataset.deleteBackup && confirm('Delete this backup permanently?')) busy(target, async () => { await api(workspaceURL(state.backupWorkspace.id, `/backups/${target.dataset.deleteBackup}`), { method: 'DELETE' }); await renderBackups(); });
});
document.addEventListener('input', (event) => {
  if (event.target.id === 'workspace-search') {
    let workspaces = state.workspaces.filter((w) => w.name.toLowerCase().includes(event.target.value.toLowerCase()));
    if (state.page === 'labs') workspaces = workspaces.filter((w) => w.mode === 'lab');
    if (state.page === 'workspaces') workspaces = workspaces.filter((w) => w.mode === 'workspace');
    $('#workspace-results').innerHTML = workspaceTable(workspaces);
  }
  if (event.target.id === 'code-editor') { state.dirty = true; $('#save-status').textContent = 'Unsaved changes'; }
});
document.addEventListener('change', (event) => { if (event.target.dataset.task) localStorage.setItem(`task:${state.user.id}:${state.editor.id}:${event.target.dataset.task}`, event.target.checked ? 'done' : ''); });
$('#toggle-auth').onclick = () => {
  state.authMode = state.authMode === 'login' ? 'register' : 'login'; const register = state.authMode === 'register';
  $('#auth-title').textContent = register ? 'Make yourself at home.' : 'Welcome back.';
  $('#auth-subtitle').textContent = register ? 'A place to learn, experiment, and build something new.' : 'Your workspace is right where you left it.';
  $('#name-label').classList.toggle('hidden', !register); $('#auth-form').elements.name.required = register;
  $('#auth-form').elements.password.autocomplete = register ? 'new-password' : 'current-password';
  $('#auth-submit').innerHTML = `${register ? 'Create account' : 'Sign in'} <span>↗</span>`;
  $('#toggle-auth').textContent = register ? 'Already have an account? Sign in' : 'Create an account'; $('#auth-error').textContent = '';
};
$('#auth-form').onsubmit = async (event) => {
  event.preventDefault(); const button = $('#auth-submit'); button.disabled = true; $('#auth-error').textContent = '';
  try { const data = Object.fromEntries(new FormData(event.target)); const session = await post(`/api/auth/${state.authMode}`, data); event.target.reset(); await enterApp(session); }
  catch (error) { $('#auth-error').textContent = error.message; } finally { button.disabled = false; }
};
$('#logout').onclick = () => busy($('#logout'), async () => { await post('/api/auth/logout'); showAuth(); });
$('#create-form').onsubmit = async (event) => {
  event.preventDefault(); const button = event.target.querySelector('[type=submit]'); button.disabled = true; button.textContent = 'Preparing your workspace…'; $('#create-error').textContent = '';
  try { await post('/api/workspaces', Object.fromEntries(new FormData(event.target))); $('#create-dialog').close(); toast('Your workspace is ready.'); await refresh(); await render(); }
  catch (error) { $('#create-error').textContent = error.message; }
  finally { button.disabled = false; button.innerHTML = 'Launch workspace <span>↗</span>'; }
};
$('#backup-create').onclick = () => busy($('#backup-create'), async () => { await post(workspaceURL(state.backupWorkspace.id, '/backups')); await renderBackups(); toast('Backup created.'); });
$('#save-button').onclick = () => busy($('#save-button'), saveFile);
$('#close-editor').onclick = closeEditor;
$('#refresh-files').onclick = () => busy($('#refresh-files'), loadFiles);
$('#reconnect-terminal').onclick = connectTerminal;
$('#new-file').onclick = () => busy($('#new-file'), async () => {
  const path = prompt('File path, relative to /workspace (for example, src/hello.py):'); if (!path) return;
  if (state.dirty) { if (!confirm('Save the current file before creating a new one?')) return; await saveFile(); }
  const existing = await api(workspaceURL(state.editor.id, '/files'));
  if (existing.files.some((file) => file.path === path)) throw new Error('That file already exists. Open it from the explorer.');
  await api(workspaceURL(state.editor.id, '/file'), { method: 'PUT', body: JSON.stringify({ path, content: '' }) }); await loadFiles(); await selectFile(path);
});
$('#delete-file').onclick = () => busy($('#delete-file'), async () => {
  if (!state.file || !confirm(`Permanently delete ${state.file}?`)) return;
  await api(workspaceURL(state.editor.id, `/file?path=${encodeURIComponent(state.file)}`), { method: 'DELETE' });
  state.file = null; state.dirty = false; $('#code-editor').value = ''; $('#current-file').textContent = 'Select a file'; $('#save-status').textContent = ''; await loadFiles();
});
$('#run-button').onclick = () => busy($('#run-button'), async () => {
  if (state.dirty) await saveFile();
  if (state.socket?.readyState !== WebSocket.OPEN) throw new Error('Reconnect the terminal before running code.');
  state.socket.send(JSON.stringify({ type: 'input', data: `${templateFor(state.editor.template).run}\r` })); state.terminal.focus();
});
$('#preview-button').onclick = () => busy($('#preview-button'), async () => {
  if (state.dirty) await saveFile();
  const response = await fetch(workspaceURL(state.editor.id, '/preview')); if (!response.ok) throw new Error('Could not build preview. Make sure index.html is saved.');
  // Fetch first to surface errors, then navigate to the same authenticated URL.
  $('#preview-frame').src = workspaceURL(state.editor.id, `/preview?t=${Date.now()}`); $('#preview-dialog').showModal();
});
$('#code-editor').addEventListener('keydown', (event) => {
  if (event.key === 'Tab') { event.preventDefault(); const editor = event.target; editor.setRangeText('    ', editor.selectionStart, editor.selectionEnd, 'end'); state.dirty = true; $('#save-status').textContent = 'Unsaved changes'; }
});
document.addEventListener('keydown', (event) => { if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's' && state.editor) { event.preventDefault(); busy($('#save-button'), saveFile); } });
window.addEventListener('beforeunload', (event) => { if (state.dirty) { event.preventDefault(); event.returnValue = ''; } });
window.addEventListener('resize', resizeTerminal);
window.addEventListener('hashchange', () => { state.page = ['dashboard', 'labs', 'workspaces', 'templates', 'admin', 'guide'].includes(location.hash.slice(1)) ? location.hash.slice(1) : 'dashboard'; render(); });
setInterval(() => { if (state.editor) updateMetrics(); }, 15000);
setInterval(async () => {
  if (!state.user || state.editor || document.hidden || document.querySelector('dialog[open]') || $('#workspace-search')?.value || state.loading) return;
  state.loading = true;
  try { await refresh(); await render(); } catch (error) { console.error(error); } finally { state.loading = false; }
}, 30000);
(async function initialize() {
  state.page = ['labs', 'workspaces', 'templates', 'admin', 'guide'].includes(location.hash.slice(1)) ? location.hash.slice(1) : 'dashboard';
  try { const config = await api('/api/config'); $('#auth-switch').classList.toggle('hidden', !config.registration); } catch { /* The form surfaces connection errors. */ }
  try { await enterApp(await api('/api/auth/me')); } catch { showAuth(); }
})();
