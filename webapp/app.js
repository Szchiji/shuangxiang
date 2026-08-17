'use strict';

/* globals window, document, location, fetch */

const tg = window.Telegram?.WebApp;
const _params = new URLSearchParams(location.search);
const tenantId = _params.get('tenant_id') || '0';
const initData = tg?.initData || '';

const BASE    = `/api/${tenantId}`;
const HEADERS = { 'Content-Type': 'application/json', 'X-Init-Data': initData };

function show(id) { document.getElementById(id).style.display = ''; }
function hide(id) { document.getElementById(id).style.display = 'none'; }

async function api(method, path, body) {
  const opts = { method, headers: HEADERS };
  if (body !== undefined) opts.body = JSON.stringify(body);
  try {
    const res = await fetch(BASE + path, opts);
    return res.json();
  } catch (_) {
    return { error: '网络错误，请检查连接后重试' };
  }
}

function showError(msg) {
  hide('loading');
  hide('main');
  const el = document.getElementById('error-msg');
  el.textContent = msg;
  show('error-msg');
}

function esc(s) {
  return String(s || '')
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function summarizeText(text, maxLen = 48) {
  const s = String(text || '').replace(/\s+/g, ' ').trim();
  if (!s) return '—';
  return s.length > maxLen ? s.slice(0, maxLen - 1) + '…' : s;
}

function formatDateTime(value) {
  if (!value) return '—';
  const normalized = String(value).replace(' ', 'T');
  const date = new Date(normalized);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

async function saveSettingsPartial(payload, msgId, successText) {
  const msgEl = document.getElementById(msgId);
  msgEl.className = 'msg';
  msgEl.textContent = '保存中…';
  const res = await api('POST', '/settings', payload);
  if (res.ok) {
    msgEl.className = 'msg ok';
    msgEl.textContent = successText;
    tg?.HapticFeedback?.notificationOccurred('success');
    return true;
  }
  msgEl.className = 'msg fail';
  msgEl.textContent = '❌ ' + (res.error || '保存失败');
  return false;
}

// ── Sidebar ───────────────────────────────────────────────────────────────────

function initSidebar() {
  const sidebar = document.getElementById('sidebar');
  const toggleBtn = document.getElementById('sidebar-toggle');
  toggleBtn.addEventListener('click', () => {
    sidebar.classList.toggle('collapsed');
  });
}

// ── Tabs ──────────────────────────────────────────────────────────────────────

function initTabs() {
  document.querySelectorAll('.nav-item').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.nav-item').forEach(b => b.classList.remove('active'));
      document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
      btn.classList.add('active');
      document.getElementById('tab-' + btn.dataset.tab).classList.add('active');
      if (btn.dataset.tab === 'stats')      loadStats();
      if (btn.dataset.tab === 'banned')     loadBanned();
      if (btn.dataset.tab === 'auto-reply') loadAutoReplies();
      if (btn.dataset.tab === 'force-sub')  loadForceSub();
    });
  });
}

// ── Interactive button builder ────────────────────────────────────────────────

/**
 * Initialise an interactive button-row builder inside `containerEl`.
 * `addRowBtnId` is the id of the "add row" button below the builder.
 * Returns { getText } — serialises to "text - url && text - url\ntext - url" format.
 */
function initButtonBuilder(containerEl, addRowBtnId) {
  /**
   * Each button is stored as a data object { text, url } on the pill element.
   * Pills are rendered inside .btn-pills-area of each .btn-row.
   * An inline edit form (.btn-inline-form) is shown/hidden per row when
   * the user clicks "＋ 添加按钮" or clicks an existing pill.
   */

  function showInlineForm(row, pillEl) {
    // Close any open form in this row first
    closeInlineForm(row);

    const pillsArea = row.querySelector('.btn-pills-area');
    const form = document.createElement('div');
    form.className = 'btn-inline-form';

    const isEdit = !!pillEl;
    const initText = isEdit ? pillEl.dataset.btnText : '';
    const initUrl  = isEdit ? pillEl.dataset.btnUrl  : '';

    form.innerHTML = `
      <input class="btn-inline-txt" type="text" placeholder="按钮文字" value="${esc(initText)}">
      <input class="btn-inline-url" type="text" placeholder="https://链接" value="${esc(initUrl)}">
      <div class="btn-inline-actions">
        <button class="btn-ghost btn-sm btn-inline-save">💾 保存</button>
        <button class="btn-ghost btn-sm btn-inline-cancel">取消</button>
        ${isEdit ? '<button class="btn-icon danger btn-inline-del" title="删除此按钮">🗑</button>' : ''}
      </div>`;

    row.insertBefore(form, pillsArea.nextSibling);

    const txtInput = form.querySelector('.btn-inline-txt');
    const urlInput = form.querySelector('.btn-inline-url');
    txtInput.focus();

    form.querySelector('.btn-inline-save').addEventListener('click', () => {
      const t = txtInput.value.trim();
      const u = urlInput.value.trim();
      if (!t || !u) {
        txtInput.style.borderColor = t ? '' : 'var(--danger)';
        urlInput.style.borderColor = u ? '' : 'var(--danger)';
        return;
      }
      if (isEdit) {
        pillEl.dataset.btnText = t;
        pillEl.dataset.btnUrl  = u;
        pillEl.querySelector('.pill-label').textContent = t;
        pillEl.title = u;
      } else {
        pillsArea.appendChild(createPill(t, u));
      }
      closeInlineForm(row);
    });

    form.querySelector('.btn-inline-cancel').addEventListener('click', () => {
      closeInlineForm(row);
      // Remove the row if it has no pills (e.g. newly added row where user cancelled)
      if (!row.querySelector('.btn-pill')) row.remove();
    });

    if (isEdit) {
      form.querySelector('.btn-inline-del').addEventListener('click', () => {
        pillEl.remove();
        closeInlineForm(row);
        if (!row.querySelector('.btn-pill')) row.remove();
      });
    }
  }

  function closeInlineForm(row) {
    row.querySelector('.btn-inline-form')?.remove();
  }

  function createPill(text, url) {
    const pill = document.createElement('div');
    pill.className = 'btn-pill';
    pill.dataset.btnText = text;
    pill.dataset.btnUrl  = url;
    pill.title = url;
    pill.innerHTML = `<span class="pill-label">${esc(text)}</span><span class="pill-edit-hint">✏️</span>`;
    pill.addEventListener('click', () => {
      const row = pill.closest('.btn-row');
      showInlineForm(row, pill);
    });
    return pill;
  }

  function createRow(initialEntries = []) {
    const row = document.createElement('div');
    row.className = 'btn-row';

    const header = document.createElement('div');
    header.className = 'btn-row-header';
    header.innerHTML = '<span>一行按钮</span>';

    const removeRowBtn = document.createElement('button');
    removeRowBtn.className = 'btn-icon danger remove-row';
    removeRowBtn.title = '删除此行';
    removeRowBtn.textContent = '✕';
    removeRowBtn.addEventListener('click', () => row.remove());
    header.appendChild(removeRowBtn);

    const pillsArea = document.createElement('div');
    pillsArea.className = 'btn-pills-area';

    const actions = document.createElement('div');
    actions.className = 'btn-row-actions';
    const addBtnInRow = document.createElement('button');
    addBtnInRow.className = 'btn-ghost btn-sm add-btn-in-row';
    addBtnInRow.textContent = '＋ 添加按钮';
    addBtnInRow.addEventListener('click', () => showInlineForm(row, null));
    actions.appendChild(addBtnInRow);

    row.append(header, pillsArea, actions);

    initialEntries.forEach(([t, u]) => {
      if (t && u) pillsArea.appendChild(createPill(t, u));
    });

    return row;
  }

  document.getElementById(addRowBtnId).addEventListener('click', () => {
    const row = createRow();
    containerEl.appendChild(row);
    // Immediately open the add form for the new row
    showInlineForm(row, null);
  });

  function getText() {
    const lines = [];
    containerEl.querySelectorAll('.btn-row').forEach(row => {
      const parts = [];
      row.querySelectorAll('.btn-pill').forEach(pill => {
        const t = pill.dataset.btnText;
        const u = pill.dataset.btnUrl;
        if (t && u) parts.push(`${t} - ${u}`);
      });
      if (parts.length) lines.push(parts.join(' && '));
    });
    return lines.join('\n');
  }

  function loadText(raw) {
    containerEl.innerHTML = '';
    if (!raw || !raw.trim()) return;
    raw.trim().split('\n').forEach(line => {
      line = line.trim();
      if (!line) return;
      const parts = line.split('&&').map(s => s.trim()).filter(Boolean);
      const entries = parts.map(p => {
        const idx = p.lastIndexOf(' - ');
        if (idx < 0) return [p, ''];
        return [p.slice(0, idx).trim(), p.slice(idx + 3).trim()];
      });
      containerEl.appendChild(createRow(entries));
    });
  }

  return { getText, loadText };
}

// ── Settings ──────────────────────────────────────────────────────────────────

let _welcomeBuilder;

async function loadSettings() {
  const data = await api('GET', '/settings');
  if (data.error) { showError('无法加载设置：' + data.error); return; }
  document.getElementById('welcome-text').value = data.welcome_text || '';
  _welcomeBuilder.loadText(data.welcome_btns_text || '');
  document.getElementById('antiflood').checked      = !!data.antiflood;
  document.getElementById('alphabet-latin').checked = !!data.alphabet_latin;
  if (data.bot_name) {
    document.getElementById('bot-name').textContent = '🤖 ' + data.bot_name;
  }
  hide('loading');
  show('main');
}

document.getElementById('save-welcome-text').addEventListener('click', async () => {
  await saveSettingsPartial({
    welcome_text:      document.getElementById('welcome-text').value,
  }, 'welcome-text-msg', '✅ 欢迎语已保存');
});

document.getElementById('save-welcome-buttons').addEventListener('click', async () => {
  await saveSettingsPartial({
    welcome_btns_text: _welcomeBuilder.getText(),
  }, 'welcome-buttons-msg', '✅ 欢迎按钮已保存');
});

document.getElementById('save-security-settings').addEventListener('click', async () => {
  await saveSettingsPartial({
    antiflood:         document.getElementById('antiflood').checked,
    alphabet_latin:    document.getElementById('alphabet-latin').checked,
  }, 'settings-msg', '✅ 安全设置已保存');
});

// ── Auto Replies ──────────────────────────────────────────────────────────────

let _arBuilder;
let _arEditId = null;
let _autoRepliesCache = [];

function showArListView() {
  show('ar-list-view');
  hide('ar-editor-view');
}

function showArEditorView() {
  hide('ar-list-view');
  show('ar-editor-view');
}

function resetArForm() {
  _arEditId = null;
  document.getElementById('ar-edit-id').value = '';
  document.getElementById('ar-form-title').textContent = '➕ 添加规则';
  document.getElementById('ar-submit').textContent = '➕ 添加';
  hide('ar-cancel');
  document.getElementById('ar-keyword').value = '';
  document.getElementById('ar-reply').value   = '';
  document.getElementById('ar-match').value   = 'contains';
  _arBuilder.loadText('');
  document.getElementById('ar-msg').textContent = '';
  document.getElementById('ar-msg').className   = 'msg';
  showArListView();
}

function startEditAr(r) {
  _arEditId = r.id;
  document.getElementById('ar-edit-id').value = r.id;
  document.getElementById('ar-form-title').textContent = '✏️ 编辑规则';
  document.getElementById('ar-submit').textContent = '💾 保存修改';
  show('ar-cancel');
  document.getElementById('ar-keyword').value = r.keyword || '';
  document.getElementById('ar-reply').value   = r.reply   || '';
  document.getElementById('ar-match').value   = r.match_type || 'contains';
  _arBuilder.loadText(r.buttons_text || '');
  document.getElementById('ar-msg').textContent = '';
  document.getElementById('ar-msg').className = 'msg';
  showArEditorView();
  document.getElementById('ar-editor-view').scrollIntoView({ behavior: 'smooth' });
}

function startCreateAr() {
  _arEditId = null;
  document.getElementById('ar-edit-id').value = '';
  document.getElementById('ar-form-title').textContent = '➕ 添加规则';
  document.getElementById('ar-submit').textContent = '➕ 添加';
  show('ar-cancel');
  document.getElementById('ar-keyword').value = '';
  document.getElementById('ar-reply').value = '';
  document.getElementById('ar-match').value = 'contains';
  _arBuilder.loadText('');
  document.getElementById('ar-msg').textContent = '';
  document.getElementById('ar-msg').className = 'msg';
  showArEditorView();
  document.getElementById('ar-editor-view').scrollIntoView({ behavior: 'smooth' });
}

function renderAutoReplies() {
  const list = document.getElementById('ar-list');
  const query = document.getElementById('ar-search').value.trim().toLowerCase();
  const match = document.getElementById('ar-filter-match').value;
  const rows = _autoRepliesCache.filter(r => {
    if (match && r.match_type !== match) return false;
    if (!query) return true;
    return [r.keyword, r.reply, matchLabel(r.match_type)]
      .some(v => String(v || '').toLowerCase().includes(query));
  });

  if (!rows.length) {
    list.innerHTML = `<p class="empty-state">${
      _autoRepliesCache.length ? '没有匹配的自动回复规则。' : '暂无自动回复规则。'
    }</p>`;
    return;
  }

  list.innerHTML = '';
  rows.forEach(r => {
    const div = document.createElement('div');
    div.className = 'ar-item';
    const buttons = (r.buttons_text || '').trim();
    div.innerHTML = `
      <div class="ar-text">
        <div class="ar-kw">🔑 ${esc(r.keyword)}</div>
        <div class="ar-reply-preview">💬 ${esc(summarizeText(r.reply, 72))}</div>
        <div class="ar-meta">
          ${esc(matchLabel(r.match_type))}
          ${buttons ? '　🔘 有按钮' : ''}
          ${r.updated_at || r.created_at ? `　🕒 ${esc(formatDateTime(r.updated_at || r.created_at))}` : ''}
        </div>
      </div>
      <div class="ar-actions">
        <button class="btn-icon edit" title="编辑">✏️</button>
        <button class="btn-icon danger" title="删除">🗑</button>
      </div>`;
    div.querySelector('.btn-icon.edit').addEventListener('click', () => startEditAr(r));
    div.querySelector('.btn-icon.danger').addEventListener('click', () => deleteAR(r.id));
    list.appendChild(div);
  });
}

async function loadAutoReplies() {
  const list = document.getElementById('ar-list');
  showArListView();
  list.innerHTML = '<p class="empty-state">加载中…</p>';
  const data = await api('GET', '/auto_replies');
  if (data.error) { list.innerHTML = `<p class="msg fail">加载失败：${esc(data.error)}</p>`; return; }
  _autoRepliesCache = Array.isArray(data) ? data : [];
  renderAutoReplies();
}

function matchLabel(t) {
  return { contains: '包含', exact: '完全匹配', startswith: '开头匹配', regex: '正则' }[t] || t;
}

async function deleteAR(id) {
  if (!window.confirm('确定要删除这条规则吗？')) return;
  await api('DELETE', '/auto_replies/' + id);
  if (_arEditId === id) resetArForm();
  loadAutoReplies();
}

document.getElementById('ar-submit').addEventListener('click', async () => {
  const msgEl  = document.getElementById('ar-msg');
  const keyword = document.getElementById('ar-keyword').value.trim();
  const reply   = document.getElementById('ar-reply').value.trim();
  const match   = document.getElementById('ar-match').value;
  const buttons = _arBuilder.getText();
  if (!keyword || !reply) {
    msgEl.className = 'msg fail';
    msgEl.textContent = '关键词和回复内容不能为空';
    return;
  }
  msgEl.className = 'msg';
  msgEl.textContent = '保存中…';
  let res;
  if (_arEditId !== null) {
    res = await api('PUT', '/auto_replies/' + _arEditId, {
      keyword, reply, match_type: match, buttons_text: buttons,
    });
    if (res.ok) {
      msgEl.className = 'msg ok';
      msgEl.textContent = '✅ 已保存修改';
      resetArForm();
      loadAutoReplies();
    } else {
      msgEl.className = 'msg fail';
      msgEl.textContent = '❌ ' + (res.error || '失败');
    }
  } else {
    res = await api('POST', '/auto_replies', {
      keyword, reply, match_type: match, buttons_text: buttons,
    });
    if (res.id) {
      msgEl.className = 'msg ok';
      msgEl.textContent = '✅ 已添加';
      resetArForm();
      loadAutoReplies();
    } else {
      msgEl.className = 'msg fail';
      msgEl.textContent = '❌ ' + (res.error || '失败');
    }
  }
});

document.getElementById('ar-cancel').addEventListener('click', resetArForm);
document.getElementById('ar-back').addEventListener('click', resetArForm);
document.getElementById('ar-start-create').addEventListener('click', startCreateAr);
document.getElementById('ar-search').addEventListener('input', renderAutoReplies);
document.getElementById('ar-filter-match').addEventListener('change', renderAutoReplies);

// ── Force Subscribe ───────────────────────────────────────────────────────────

// In-memory channel list (loaded from server); mutated by add/remove, saved on change.
let _fsubChannels = [];
let _fsubEditIndex = null;

function showFsubView(view) {
  ['fsub-list-view', 'fsub-editor-view', 'fsub-settings-view'].forEach(id => hide(id));
  show(view);
}

function resetFsubEditor() {
  _fsubEditIndex = null;
  document.getElementById('fsub-editor-title').textContent = '➕ 添加频道';
  document.getElementById('fsub-add-title').value = '';
  document.getElementById('fsub-add-chat').value = '';
  document.getElementById('fsub-add-url').value = '';
  document.getElementById('fsub-msg').textContent = '';
  document.getElementById('fsub-msg').className = 'msg';
  showFsubView('fsub-list-view');
}

function startCreateFsub() {
  _fsubEditIndex = null;
  document.getElementById('fsub-editor-title').textContent = '➕ 添加频道';
  document.getElementById('fsub-add-title').value = '';
  document.getElementById('fsub-add-chat').value = '';
  document.getElementById('fsub-add-url').value = '';
  document.getElementById('fsub-msg').textContent = '';
  document.getElementById('fsub-msg').className = 'msg';
  showFsubView('fsub-editor-view');
}

function startEditFsub(index) {
  const ch = _fsubChannels[index];
  if (!ch) return;
  _fsubEditIndex = index;
  document.getElementById('fsub-editor-title').textContent = '✏️ 编辑频道';
  document.getElementById('fsub-add-title').value = ch.title || '';
  document.getElementById('fsub-add-chat').value = ch.chat || '';
  document.getElementById('fsub-add-url').value = ch.url || '';
  document.getElementById('fsub-msg').textContent = '';
  document.getElementById('fsub-msg').className = 'msg';
  showFsubView('fsub-editor-view');
}

function renderFsubList() {
  const list = document.getElementById('fsub-list');
  if (!_fsubChannels.length) {
    list.innerHTML = '<p class="empty-state">暂无配置频道。</p>';
    return;
  }
  list.innerHTML = '';
  _fsubChannels.forEach((ch, i) => {
    const div = document.createElement('div');
    div.className = 'fsub-item';

    const info = document.createElement('div');
    info.className = 'fsub-info';

    const titleEl = document.createElement('div');
    titleEl.className = 'fsub-title';
    titleEl.textContent = ch.title || ch.chat;

    const chatEl = document.createElement('div');
    chatEl.className = 'fsub-chat';
    chatEl.textContent = ch.chat;

    const safeUrl = ch.url || '';
    if (safeUrl && (safeUrl.startsWith('https://') || safeUrl.startsWith('http://') || safeUrl.startsWith('tg://'))) {
      const sep = document.createTextNode(' · ');
      const a = document.createElement('a');
      a.href = safeUrl;
      a.target = '_blank';
      a.rel = 'noopener noreferrer';
      a.textContent = '加入链接';
      chatEl.append(sep, a);
    }

    info.append(titleEl, chatEl);

    const actions = document.createElement('div');
    actions.className = 'fsub-actions';

    const editBtn = document.createElement('button');
    editBtn.className = 'btn-icon edit';
    editBtn.title = '编辑';
    editBtn.textContent = '✏️';
    editBtn.addEventListener('click', () => startEditFsub(i));

    const delBtn = document.createElement('button');
    delBtn.className = 'btn-icon danger';
    delBtn.title = '删除';
    delBtn.textContent = '🗑';
    delBtn.addEventListener('click', () => {
      if (!window.confirm('确定要删除这个频道吗？')) return;
      _fsubChannels.splice(i, 1);
      saveFsubChannels();
    });

    actions.append(editBtn, delBtn);
    div.append(info, actions);
    list.appendChild(div);
  });
}

async function saveFsubChannels() {
  renderFsubList();
  const lines = _fsubChannels.map(ch => {
    const parts = [ch.title || '', ch.chat, ch.url || ''];
    return parts.join(' | ');
  });
  const msgEl = document.getElementById('fsub-msg');
  msgEl.className = 'msg';
  msgEl.textContent = '保存中…';
  const res = await api('POST', '/settings', { force_sub_text: lines.join('\n') });
  if (res.ok) {
    msgEl.className = 'msg ok';
    msgEl.textContent = '✅ 已保存';
    tg?.HapticFeedback?.notificationOccurred('success');
    return true;
  } else {
    msgEl.className = 'msg fail';
    msgEl.textContent = '❌ ' + (res.error || '保存失败');
    return false;
  }
}

async function loadForceSub() {
  const data = await api('GET', '/settings');
  if (data.error) return;
  _fsubChannels = Array.isArray(data.force_sub_channels) ? data.force_sub_channels : [];
  document.getElementById('force-sub-on').checked = !!data.force_sub_on;
  document.getElementById('fsub-msg-text').value = data.force_sub_msg || '';
  renderFsubList();
  showFsubView('fsub-list-view');
}

document.getElementById('fsub-save-btn').addEventListener('click', async () => {
  const msgEl = document.getElementById('fsub-msg');
  const chat  = document.getElementById('fsub-add-chat').value.trim();
  if (!chat) {
    msgEl.className = 'msg fail';
    msgEl.textContent = '频道标识不能为空';
    return;
  }
  const title = document.getElementById('fsub-add-title').value.trim();
  const url   = document.getElementById('fsub-add-url').value.trim();
  const next = { title, chat, url };
  if (_fsubEditIndex === null) _fsubChannels.push(next);
  else _fsubChannels.splice(_fsubEditIndex, 1, next);
  if (await saveFsubChannels()) resetFsubEditor();
});

document.getElementById('fsub-save-settings').addEventListener('click', async () => {
  await saveSettingsPartial({
    force_sub_on: document.getElementById('force-sub-on').checked,
    force_sub_msg: document.getElementById('fsub-msg-text').value,
  }, 'fsub-save-msg-result', '✅ 规则设置已保存');
});

document.getElementById('fsub-start-add').addEventListener('click', startCreateFsub);
document.getElementById('fsub-open-settings').addEventListener('click', () => showFsubView('fsub-settings-view'));
document.getElementById('fsub-back-from-editor').addEventListener('click', resetFsubEditor);
document.getElementById('fsub-cancel-btn').addEventListener('click', resetFsubEditor);
document.getElementById('fsub-back-from-settings').addEventListener('click', () => showFsubView('fsub-list-view'));

// ── Broadcast ─────────────────────────────────────────────────────────────────

let _bcBuilder;

document.getElementById('bc-send').addEventListener('click', async () => {
  const msgEl = document.getElementById('bc-msg');
  const text  = document.getElementById('bc-text').value.trim();
  const photo = document.getElementById('bc-photo').value.trim();
  const silent = document.getElementById('bc-silent').checked;
  const buttons = _bcBuilder.getText();
  if (!text && !photo) {
    msgEl.className = 'msg fail';
    msgEl.textContent = '请填写消息内容或图片链接';
    return;
  }
  if (!window.confirm('确定要向所有活跃用户群发这条消息吗？')) return;
  const btn = document.getElementById('bc-send');
  btn.disabled = true;
  msgEl.className = 'msg';
  msgEl.textContent = '发送中，请稍候…';
  const payload = { text, silent };
  if (photo) payload.photo = photo;
  if (buttons) payload.buttons = buttons;
  const res = await api('POST', '/broadcast', payload);
  btn.disabled = false;
  if (res.ok) {
    msgEl.className = 'msg ok';
    msgEl.textContent = `✅ 已排队发送给 ${res.queued} 位用户，发送将在后台完成。`;
    tg?.HapticFeedback?.notificationOccurred('success');
  } else {
    msgEl.className = 'msg fail';
    msgEl.textContent = '❌ ' + (res.error || '发送失败');
  }
});

// ── Banned Users ──────────────────────────────────────────────────────────────

let _bannedUsersCache = [];

function renderBanned() {
  const list = document.getElementById('banned-list');
  const query = document.getElementById('banned-search').value.trim().toLowerCase();
  const rows = _bannedUsersCache.filter(u => {
    if (!query) return true;
    return [u.user_id, u.username, u.full_name]
      .some(v => String(v || '').toLowerCase().includes(query));
  });
  if (!rows.length) {
    list.innerHTML = `<p class="empty-state">${
      _bannedUsersCache.length ? '没有匹配的封禁用户。' : '暂无封禁用户。'
    }</p>`;
    return;
  }
  list.innerHTML = '';
  rows.forEach(u => {
    const div  = document.createElement('div');
    div.className = 'ban-item';
    const displayName = u.full_name
      || (u.username ? '@' + u.username : '')
      || String(u.user_id);
    div.innerHTML = `
      <div class="ban-info">
        <div class="ban-name">👤 ${esc(displayName)}</div>
        <small>${u.username ? '@' + esc(u.username) + ' · ' : ''}ID: ${esc(String(u.user_id))}</small>
        <span class="ban-status">状态：已封禁</span>
      </div>
      <button class="btn-unban">✅ 解封</button>`;
    div.querySelector('.btn-unban').addEventListener('click', () => unban(u.user_id));
    list.appendChild(div);
  });
}

async function loadBanned() {
  const list = document.getElementById('banned-list');
  document.getElementById('banned-msg').textContent = '';
  document.getElementById('banned-msg').className = 'msg';
  list.innerHTML = '<p class="empty-state">加载中…</p>';
  const data = await api('GET', '/banned');
  if (data.error) { list.innerHTML = `<p class="msg fail">加载失败：${esc(data.error)}</p>`; return; }
  _bannedUsersCache = Array.isArray(data) ? data : [];
  renderBanned();
}

async function unban(uid) {
  if (!window.confirm('确定要解封这个用户吗？')) return;
  const msgEl = document.getElementById('banned-msg');
  msgEl.className = 'msg';
  msgEl.textContent = '处理中…';
  const res = await api('POST', '/unban/' + uid);
  if (res.ok) {
    msgEl.className = 'msg ok';
    msgEl.textContent = '✅ 已解封';
    loadBanned();
  } else {
    msgEl.className = 'msg fail';
    msgEl.textContent = '❌ ' + (res.error || '解封失败');
  }
}

document.getElementById('banned-search').addEventListener('input', renderBanned);

// ── Stats ─────────────────────────────────────────────────────────────────────

async function loadStats() {
  const el = document.getElementById('stats-content');
  el.innerHTML = '<p style="color:var(--hint);padding:4px">加载中…</p>';
  const s = await api('GET', '/stats');
  if (s.error) { el.innerHTML = `<p class="msg fail">加载失败：${esc(s.error)}</p>`; return; }
  el.innerHTML = `<div class="stats-grid">${
    [
      ['👥 总用户',    s.total],
      ['✅ 正常',      s.active],
      ['⛔ 封禁',      s.banned],
      ['📅 近7天活跃', s.active_7d],
      ['🆕 近7天新增', s.new_7d],
    ].map(([label, val]) => `
      <div class="stat-card">
        <div class="stat-label">${label}</div>
        <div class="stat-val">${val ?? '—'}</div>
      </div>`).join('')
  }</div>`;
}

// ── Init ──────────────────────────────────────────────────────────────────────

tg?.ready();
tg?.expand();

_welcomeBuilder = initButtonBuilder(
  document.getElementById('welcome-buttons-builder'),
  'welcome-buttons-add-row'
);
_arBuilder = initButtonBuilder(
  document.getElementById('ar-buttons-builder'),
  'ar-buttons-add-row'
);
_bcBuilder = initButtonBuilder(
  document.getElementById('bc-buttons-builder'),
  'bc-buttons-add-row'
);

initSidebar();
initTabs();
loadSettings();
