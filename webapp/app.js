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
    let data;
    try {
      data = await res.json();
    } catch (_) {
      return { error: res.ok ? '响应格式错误' : `请求失败 (${res.status})` };
    }
    if (!res.ok && data && typeof data === 'object' && data.error == null) {
      data.error = `请求失败 (${res.status})`;
    }
    return data;
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

// ── Theme ─────────────────────────────────────────────────────────────────────

function applyTheme(theme) {
  document.documentElement.setAttribute('data-theme', theme);
  const btn = document.getElementById('theme-toggle');
  if (btn) btn.innerHTML = theme === 'dark' ? '&#9789;' : '&#9788;';
}

function initTheme() {
  const saved = localStorage.getItem('bh_theme') || 'light';
  applyTheme(saved);
  const toggleBtn = document.getElementById('theme-toggle');
  toggleBtn?.addEventListener('click', () => {
    const next = document.documentElement.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
    localStorage.setItem('bh_theme', next);
    applyTheme(next);
  });
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
      if (btn.dataset.tab === 'filters')    loadFilters();
      if (btn.dataset.tab === 'force-sub')  loadForceSub();
      if (btn.dataset.tab === 'logs')       loadInterceptLogs();
      if (btn.dataset.tab === 'scheduled')  loadScheduledMessages();
      if (btn.dataset.tab === 'broadcast')  loadBroadcastEstimate();
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
  document.getElementById('welcome-media-type').value = data.welcome_media_type || '';
  document.getElementById('welcome-media-id').value = data.welcome_media_id || '';
  document.getElementById('antiflood').checked      = !!data.antiflood;
  document.getElementById('alphabet-latin').checked = !!data.alphabet_latin;
  document.getElementById('filter-auto-ban').checked = !!data.filter_auto_ban;
  document.getElementById('block-via-bot').checked   = !!data.block_via_bot;
  document.getElementById('flood-max-msgs').value   = data.flood_max_msgs ?? 5;
  document.getElementById('flood-window').value     = data.flood_window ?? 5;
  const topicsEl = document.getElementById('topics-status');
  if (data.topics_enabled) {
    topicsEl.innerHTML = `✅ 已启用 Topics 模式<br>管理群 ID：<code>${esc(String(data.manage_group))}</code>`;
  } else {
    topicsEl.textContent = '未启用（当前为 DM 私聊模式）';
  }
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

document.getElementById('save-welcome-media').addEventListener('click', async () => {
  const mediaType = document.getElementById('welcome-media-type').value;
  const mediaId = document.getElementById('welcome-media-id').value.trim();
  if (mediaType && !mediaId) {
    const msgEl = document.getElementById('welcome-media-msg');
    msgEl.className = 'msg fail';
    msgEl.textContent = '❌ 请填写媒体 file_id 或 URL';
    return;
  }
  await saveSettingsPartial({
    welcome_media_type: mediaType,
    welcome_media_id: mediaType ? mediaId : '',
  }, 'welcome-media-msg', '✅ 欢迎语封面已保存');
});

document.getElementById('clear-welcome-media').addEventListener('click', async () => {
  document.getElementById('welcome-media-type').value = '';
  document.getElementById('welcome-media-id').value = '';
  await saveSettingsPartial({
    welcome_media_type: '',
    welcome_media_id: '',
  }, 'welcome-media-msg', '✅ 已清除封面');
});

document.getElementById('save-security-settings').addEventListener('click', async () => {
  const floodMaxMsgs = parseInt(document.getElementById('flood-max-msgs').value, 10);
  const floodWindow  = parseInt(document.getElementById('flood-window').value, 10);
  if (Number.isNaN(floodMaxMsgs) || Number.isNaN(floodWindow)) {
    const msgEl = document.getElementById('settings-msg');
    msgEl.className = 'msg fail';
    msgEl.textContent = '❌ 刷屏阈值必须为数字';
    return;
  }
  await saveSettingsPartial({
    antiflood:         document.getElementById('antiflood').checked,
    alphabet_latin:    document.getElementById('alphabet-latin').checked,
    filter_auto_ban:   document.getElementById('filter-auto-ban').checked,
    block_via_bot:     document.getElementById('block-via-bot').checked,
    flood_max_msgs:    floodMaxMsgs,
    flood_window:      floodWindow,
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
  document.getElementById('ar-stop').checked  = false;
  document.getElementById('ar-media-type').value = '';
  document.getElementById('ar-media-id').value = '';
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
  document.getElementById('ar-stop').checked  = !!r.stop;
  document.getElementById('ar-media-type').value = r.media_type || '';
  document.getElementById('ar-media-id').value = r.media_id || '';
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
  document.getElementById('ar-stop').checked = false;
  document.getElementById('ar-media-type').value = '';
  document.getElementById('ar-media-id').value = '';
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
          ${r.stop ? '　🛑 拦截转发' : ''}
          ${r.media_type ? `　🖼 ${esc(r.media_type)}` : ''}
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
  const stop    = document.getElementById('ar-stop').checked;
  const mediaType = document.getElementById('ar-media-type').value;
  const mediaId = document.getElementById('ar-media-id').value.trim();
  const buttons = _arBuilder.getText();
  if (!keyword || !reply) {
    msgEl.className = 'msg fail';
    msgEl.textContent = '关键词和回复内容不能为空';
    return;
  }
  if (mediaType && !mediaId) {
    msgEl.className = 'msg fail';
    msgEl.textContent = '已选媒体类型时请填写 file_id / URL';
    return;
  }
  const payload = {
    keyword,
    reply,
    match_type: match,
    stop,
    buttons_text: buttons,
    media_type: mediaType,
    media_id: mediaType ? mediaId : '',
  };
  msgEl.className = 'msg';
  msgEl.textContent = '保存中…';
  let res;
  if (_arEditId !== null) {
    res = await api('PUT', '/auto_replies/' + _arEditId, payload);
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
    res = await api('POST', '/auto_replies', payload);
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

document.getElementById('ar-export').addEventListener('click', async () => {
  const data = await api('GET', '/auto_replies/export');
  if (data.error) { alert('导出失败：' + data.error); return; }
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = 'auto_replies.json';
  a.click();
  URL.revokeObjectURL(url);
});
document.getElementById('ar-import').addEventListener('click', () => {
  document.getElementById('ar-import-file').click();
});
document.getElementById('ar-import-file').addEventListener('change', async (e) => {
  const file = e.target.files[0];
  e.target.value = '';
  if (!file) return;
  let parsed;
  try { parsed = JSON.parse(await file.text()); }
  catch (_) { alert('导入失败：不是有效的 JSON'); return; }
  const res = await api('POST', '/auto_replies/import', parsed);
  if (res.error) { alert('导入失败：' + res.error); return; }
  alert(`导入完成：成功 ${res.imported} 条${res.errors && res.errors.length ? `，失败 ${res.errors.length} 条` : ''}`);
  loadAutoReplies();
});

// ── Filters ───────────────────────────────────────────────────────────────────

let _filtersCache = [];
let _flEditId = null;

function filterMatchLabel(t) {
  return { contains: '包含', regex: '正则' }[t] || t || '包含';
}

function showFlListView() {
  show('fl-list-card');
  hide('fl-editor-card');
}

function showFlEditorView() {
  hide('fl-list-card');
  show('fl-editor-card');
}

function resetFlForm() {
  _flEditId = null;
  document.getElementById('fl-edit-id').value = '';
  document.getElementById('fl-form-title').textContent = '➕ 添加过滤词';
  document.getElementById('fl-form-hint').textContent =
    '支持包含匹配或正则表达式。可一次粘贴多个词，每行一个。';
  document.getElementById('fl-submit').textContent = '➕ 添加';
  hide('fl-cancel');
  document.getElementById('fl-keyword').value = '';
  document.getElementById('fl-keyword').rows = 3;
  document.getElementById('fl-match').value = 'contains';
  document.getElementById('fl-msg').textContent = '';
  document.getElementById('fl-msg').className = 'msg';
  showFlListView();
}

function startCreateFl() {
  resetFlForm();
  show('fl-cancel');
  showFlEditorView();
  document.getElementById('fl-editor-card').scrollIntoView({ behavior: 'smooth' });
  document.getElementById('fl-keyword').focus();
}

function startEditFl(r) {
  _flEditId = r.id;
  document.getElementById('fl-edit-id').value = r.id;
  document.getElementById('fl-form-title').textContent = '✏️ 编辑过滤词';
  document.getElementById('fl-form-hint').textContent =
    '修改关键词或匹配方式后保存。编辑时一次只能改一条。';
  document.getElementById('fl-submit').textContent = '💾 保存修改';
  show('fl-cancel');
  document.getElementById('fl-keyword').value = r.keyword || '';
  document.getElementById('fl-keyword').rows = 2;
  document.getElementById('fl-match').value = r.match_type || 'contains';
  document.getElementById('fl-msg').textContent = '';
  document.getElementById('fl-msg').className = 'msg';
  showFlEditorView();
  document.getElementById('fl-editor-card').scrollIntoView({ behavior: 'smooth' });
  document.getElementById('fl-keyword').focus();
}

function renderFilters() {
  const list = document.getElementById('fl-list');
  const query = document.getElementById('fl-search').value.trim().toLowerCase();
  const match = document.getElementById('fl-filter-match').value;
  const rows = _filtersCache.filter(r => {
    if (match && (r.match_type || 'contains') !== match) return false;
    if (!query) return true;
    return String(r.keyword || '').toLowerCase().includes(query)
      || filterMatchLabel(r.match_type).includes(query);
  });

  if (!rows.length) {
    list.innerHTML = `<p class="empty-state">${
      _filtersCache.length
        ? '没有匹配的过滤词。'
        : '暂无过滤词。点上方「➕ 添加过滤词」开始配置。'
    }</p>`;
    return;
  }

  list.innerHTML = '';
  const count = document.createElement('div');
  count.className = 'list-count';
  count.textContent = query || match
    ? `显示 ${rows.length} / ${_filtersCache.length} 个过滤词`
    : `已添加 ${rows.length} 个过滤词（可编辑或删除）`;
  list.appendChild(count);

  rows.forEach(r => {
    const div = document.createElement('div');
    div.className = 'fl-item';
    const mt = r.match_type || 'contains';
    div.innerHTML = `
      <div class="fl-text">
        <div class="fl-kw">🚫 ${esc(r.keyword)}</div>
        <div class="fl-meta">
          <span class="tag tag-${esc(mt)}">${esc(filterMatchLabel(mt))}</span>
          <span class="fl-id">#${esc(String(r.id))}</span>
        </div>
      </div>
      <div class="fl-actions">
        <button class="btn-icon edit" title="编辑">✏️</button>
        <button class="btn-icon danger" title="删除">🗑</button>
      </div>`;
    div.querySelector('.btn-icon.edit').addEventListener('click', () => startEditFl(r));
    div.querySelector('.btn-icon.danger').addEventListener('click', () => deleteFilter(r.id));
    list.appendChild(div);
  });
}

async function loadFilters() {
  const list = document.getElementById('fl-list');
  showFlListView();
  list.innerHTML = '<p class="empty-state">加载中…</p>';
  const data = await api('GET', '/filters');
  if (data && data.error) {
    list.innerHTML = `<p class="msg fail">加载失败：${esc(data.error)}</p>`;
    return;
  }
  _filtersCache = Array.isArray(data) ? data : [];
  renderFilters();
}

async function deleteFilter(id) {
  if (!window.confirm('确定要删除这个过滤词吗？')) return;
  const res = await api('DELETE', '/filters/' + id);
  if (res && res.error) {
    window.alert('删除失败：' + res.error);
    return;
  }
  if (_flEditId === id) resetFlForm();
  await loadFilters();
}

document.getElementById('fl-submit').addEventListener('click', async () => {
  const msgEl = document.getElementById('fl-msg');
  const btn = document.getElementById('fl-submit');
  const raw = document.getElementById('fl-keyword').value;
  const match = document.getElementById('fl-match').value;
  const words = raw.split(/\r?\n/).map(s => s.trim()).filter(Boolean);
  if (!words.length) {
    msgEl.className = 'msg fail';
    msgEl.textContent = '请输入至少一个过滤词';
    return;
  }
  btn.disabled = true;
  msgEl.className = 'msg';
  msgEl.textContent = _flEditId != null ? '保存中…' : '添加中…';
  try {
    if (_flEditId != null) {
      if (words.length !== 1) {
        msgEl.className = 'msg fail';
        msgEl.textContent = '编辑时请只保留一行关键词';
        return;
      }
      const res = await api('PUT', '/filters/' + _flEditId, {
        keyword: words[0], match_type: match,
      });
      if (res && res.ok && res.error == null) {
        msgEl.className = 'msg ok';
        msgEl.textContent = '✅ 已保存修改';
        tg?.HapticFeedback?.notificationOccurred('success');
        resetFlForm();
        await loadFilters();
      } else {
        msgEl.className = 'msg fail';
        msgEl.textContent = '❌ ' + ((res && res.error) || '保存失败');
      }
      return;
    }

    let ok = 0;
    const errors = [];
    for (const keyword of words) {
      const res = await api('POST', '/filters', { keyword, match_type: match });
      // 用 != null 判断，避免把合法 id 与错误响应混淆；同时要求无 error 字段。
      if (res && res.id != null && res.error == null) ok += 1;
      else errors.push(`${keyword}: ${(res && res.error) || '失败'}`);
    }
    if (ok) {
      document.getElementById('fl-keyword').value = '';
      msgEl.className = 'msg ok';
      msgEl.textContent = errors.length
        ? `✅ 已添加 ${ok} 个，失败 ${errors.length} 个`
        : `✅ 已添加 ${ok} 个过滤词`;
      tg?.HapticFeedback?.notificationOccurred('success');
      resetFlForm();
      await loadFilters();
    } else {
      msgEl.className = 'msg fail';
      msgEl.textContent = '❌ ' + (errors[0] || '添加失败');
    }
  } finally {
    btn.disabled = false;
  }
});

document.getElementById('fl-start-create').addEventListener('click', startCreateFl);
document.getElementById('fl-cancel').addEventListener('click', resetFlForm);
document.getElementById('fl-back').addEventListener('click', resetFlForm);
document.getElementById('fl-search').addEventListener('input', renderFilters);
document.getElementById('fl-filter-match').addEventListener('change', renderFilters);

document.getElementById('fl-export').addEventListener('click', async () => {
  const data = await api('GET', '/filters/export');
  if (data.error) { alert('导出失败：' + data.error); return; }
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = 'filters.json';
  a.click();
  URL.revokeObjectURL(url);
});
document.getElementById('fl-import').addEventListener('click', () => {
  document.getElementById('fl-import-file').click();
});
document.getElementById('fl-import-file').addEventListener('change', async (e) => {
  const file = e.target.files[0];
  e.target.value = '';
  if (!file) return;
  let parsed;
  const text = await file.text();
  try {
    parsed = JSON.parse(text);
  } catch (_) {
    // Plain text: one keyword per line
    parsed = {
      items: text.split(/\r?\n/).map(l => l.trim()).filter(Boolean)
        .map(keyword => ({ keyword, match_type: 'contains' })),
    };
  }
  const res = await api('POST', '/filters/import', parsed);
  if (res.error) { alert('导入失败：' + res.error); return; }
  alert(`导入完成：成功 ${res.imported} 条${res.errors && res.errors.length ? `，失败 ${res.errors.length} 条` : ''}`);
  loadFilters();
});

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
let _bcPollTimer = null;

async function loadBroadcastEstimate() {
  const el = document.getElementById('bc-estimate');
  if (!el) return;
  const data = await api('GET', '/broadcast/estimate');
  if (data.error) {
    el.textContent = '预计触达：—';
    return;
  }
  el.textContent = `预计触达：${data.active_users ?? 0} 位活跃用户`;
}

async function pollBroadcastJob(jobId) {
  const progressEl = document.getElementById('bc-progress');
  const msgEl = document.getElementById('bc-msg');
  show('bc-progress');
  const tick = async () => {
    const job = await api('GET', '/broadcast/' + jobId);
    if (job.error) {
      progressEl.textContent = '无法查询发送进度';
      return;
    }
    const pct = job.total ? Math.round((job.done / job.total) * 100) : 0;
    progressEl.textContent =
      `进度 ${job.done}/${job.total}（${pct}%）· 成功 ${job.success} · 失败 ${job.failed}`
      + (job.status === 'done' ? ' · 已完成' : ' · 发送中…');
    if (job.status === 'done') {
      msgEl.className = 'msg ok';
      msgEl.textContent =
        `✅ 群发完成：成功 ${job.success}，失败 ${job.failed}（共 ${job.total}）`;
      tg?.HapticFeedback?.notificationOccurred('success');
      loadBroadcastEstimate();
      return;
    }
    _bcPollTimer = setTimeout(tick, 1200);
  };
  tick();
}

document.getElementById('bc-send').addEventListener('click', async () => {
  const msgEl = document.getElementById('bc-msg');
  const text  = document.getElementById('bc-text').value.trim();
  const photo = document.getElementById('bc-photo').value.trim();
  const silent = document.getElementById('bc-silent').checked;
  const buttons = _bcBuilder.getText();
  if (!text && !photo) {
    msgEl.className = 'msg fail';
    msgEl.textContent = '请填写消息内容或图片链接 / file_id';
    return;
  }
  if (!window.confirm('确定要向所有活跃用户群发这条消息吗？')) return;
  if (_bcPollTimer) { clearTimeout(_bcPollTimer); _bcPollTimer = null; }
  const btn = document.getElementById('bc-send');
  btn.disabled = true;
  msgEl.className = 'msg';
  msgEl.textContent = '排队中…';
  document.getElementById('bc-progress').textContent = '';
  hide('bc-progress');
  const payload = { text, silent };
  if (photo) payload.photo = photo;
  if (buttons) payload.buttons = buttons;
  const res = await api('POST', '/broadcast', payload);
  btn.disabled = false;
  if (res.ok) {
    msgEl.className = 'msg ok';
    msgEl.textContent = `✅ 已排队发送给 ${res.queued} 位用户`;
    if (res.job_id) pollBroadcastJob(res.job_id);
    else tg?.HapticFeedback?.notificationOccurred('success');
  } else {
    msgEl.className = 'msg fail';
    msgEl.textContent = '❌ ' + (res.error || '发送失败');
  }
});

// ── Banned Users ──────────────────────────────────────────────────────────────

let _bannedUsersCache = [];
let _usersCache = [];

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

function renderUsers() {
  const list = document.getElementById('users-list');
  if (!_usersCache.length) {
    list.innerHTML = '<p class="empty-state">暂无用户，或没有匹配结果。</p>';
    return;
  }
  list.innerHTML = '';
  _usersCache.forEach(u => {
    const div = document.createElement('div');
    div.className = 'ban-item';
    const displayName = u.full_name
      || (u.username ? '@' + u.username : '')
      || String(u.user_id);
    const status = u.is_banned
      ? '<span class="ban-status">已封禁</span>'
      : '<span class="ban-status" style="color:var(--ok,#16a34a)">正常</span>';
    div.innerHTML = `
      <div class="ban-info">
        <div class="ban-name">👤 ${esc(displayName)}</div>
        <small>${u.username ? '@' + esc(u.username) + ' · ' : ''}ID: ${esc(String(u.user_id))}
          ${u.last_seen ? ' · 最近 ' + esc(formatDateTime(u.last_seen)) : ''}</small>
        ${status}
      </div>
      ${u.is_banned
        ? '<button class="btn-unban">✅ 解封</button>'
        : '<button class="btn-ghost btn-sm btn-ban-one">⛔ 封禁</button>'}`;
    if (u.is_banned) {
      div.querySelector('.btn-unban').addEventListener('click', () => unban(u.user_id));
    } else {
      div.querySelector('.btn-ban-one').addEventListener('click', () => banUser(u.user_id));
    }
    list.appendChild(div);
  });
}

async function loadUsers() {
  const list = document.getElementById('users-list');
  list.innerHTML = '<p class="empty-state">加载中…</p>';
  const q = document.getElementById('users-search').value.trim();
  const path = '/users?limit=30' + (q ? '&q=' + encodeURIComponent(q) : '');
  const data = await api('GET', path);
  if (data.error) {
    list.innerHTML = `<p class="msg fail">加载失败：${esc(data.error)}</p>`;
    return;
  }
  _usersCache = Array.isArray(data) ? data : [];
  renderUsers();
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
  loadUsers();
}

async function banUser(uid) {
  if (!window.confirm('确定要封禁用户 ' + uid + ' 吗？')) return;
  const msgEl = document.getElementById('ban-msg') || document.getElementById('banned-msg');
  msgEl.className = 'msg';
  msgEl.textContent = '处理中…';
  const res = await api('POST', '/ban/' + uid);
  if (res.ok) {
    msgEl.className = 'msg ok';
    msgEl.textContent = '✅ 已封禁 ' + uid;
    loadBanned();
  } else {
    msgEl.className = 'msg fail';
    msgEl.textContent = '❌ ' + (res.error || '封禁失败');
  }
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
document.getElementById('ban-submit').addEventListener('click', () => {
  const uid = parseInt(document.getElementById('ban-uid').value, 10);
  if (Number.isNaN(uid) || uid <= 0) {
    const msgEl = document.getElementById('ban-msg');
    msgEl.className = 'msg fail';
    msgEl.textContent = '❌ 请输入有效的用户 ID';
    return;
  }
  banUser(uid);
});
let _usersSearchTimer = null;
document.getElementById('users-search').addEventListener('input', () => {
  if (_usersSearchTimer) clearTimeout(_usersSearchTimer);
  _usersSearchTimer = setTimeout(loadUsers, 300);
});

// ── Intercept Logs ────────────────────────────────────────────────────────────

const _logReasonLabels = {
  antiflood:       '🛡 防刷屏',
  alphabet_latin:  '🔤 英文拦截',
  filter:          '🚫 过滤词',
  block_via_bot:   '🤖 第三方机器人',
};

function renderInterceptLogs(rows) {
  const list = document.getElementById('logs-list');
  if (!rows.length) {
    list.innerHTML = '<p class="empty-state">暂无拦截日志。</p>';
    return;
  }
  list.innerHTML = '';
  rows.forEach(r => {
    const div = document.createElement('div');
    div.className = 'ban-item';
    const who = r.full_name || (r.username ? '@' + r.username : '') || String(r.user_id ?? '—');
    const reasonLabel = _logReasonLabels[r.reason] || r.reason;
    const ruleText = r.rule ? `规则：${esc(r.rule)}　` : '';
    const viaBotText = r.via_bot_id
      ? `来源机器人：${esc(r.via_bot_username ? '@' + r.via_bot_username : String(r.via_bot_id))}　`
      : '';
    const banText = r.auto_banned ? '<span class="ban-status">已自动封禁</span>' : '';
    const banBtn = (r.user_id && !r.auto_banned)
      ? '<button class="btn-ghost btn-sm btn-ban-log">⛔ 封禁</button>'
      : '';
    div.innerHTML = `
      <div class="ban-info">
        <div class="ban-name">${reasonLabel} · 👤 ${esc(who)}</div>
        <small>${ruleText}${viaBotText}${formatDateTime(r.created_at)}</small>
        <div>${esc(summarizeText(r.message_summary))}</div>
        ${banText}
      </div>
      ${banBtn}`;
    const btn = div.querySelector('.btn-ban-log');
    if (btn) btn.addEventListener('click', () => banUser(r.user_id));
    list.appendChild(div);
  });
}

async function loadInterceptLogs() {
  const list = document.getElementById('logs-list');
  document.getElementById('logs-msg').textContent = '';
  document.getElementById('logs-msg').className = 'msg';
  list.innerHTML = '<p class="empty-state">加载中…</p>';
  const reason = document.getElementById('logs-reason').value;
  const qs = '?limit=100' + (reason ? '&reason=' + encodeURIComponent(reason) : '');
  const data = await api('GET', '/intercept_logs' + qs);
  if (data.error) { list.innerHTML = `<p class="msg fail">加载失败：${esc(data.error)}</p>`; return; }
  const items = Array.isArray(data) ? data : (data.items || []);
  const total = Array.isArray(data) ? items.length : (data.total ?? items.length);
  document.getElementById('logs-summary').textContent =
    reason ? `当前筛选共 ${total} 条` : `共 ${total} 条拦截记录`;
  renderInterceptLogs(items);
}

document.getElementById('logs-reason').addEventListener('change', loadInterceptLogs);
document.getElementById('logs-refresh').addEventListener('click', loadInterceptLogs);

// ── Scheduled Messages ──────────────────────────────────────────────────────

let _smBuilder;
let _smEditId = null;
let _smCache = [];
let _smSelected = new Set();

const _smMsgTypeLabels = { text: '文字', photo: '图片', video: '视频', document: '文件' };
const _smTargetTypeLabels = { group: '群组', channel: '频道' };

function showSmListView() {
  show('sm-list-view');
  show('sm-table-card');
  hide('sm-editor-view');
}

function showSmEditorView() {
  hide('sm-table-card');
  show('sm-editor-view');
}

function toggleSmMediaRow() {
  const type = document.getElementById('sm-msg-type').value;
  if (type === 'text') hide('sm-media-row');
  else show('sm-media-row');
}
document.getElementById('sm-msg-type').addEventListener('change', toggleSmMediaRow);

function resetSmForm() {
  _smEditId = null;
  document.getElementById('sm-edit-id').value = '';
  document.getElementById('sm-form-title').textContent = '＋ 新增消息';
  document.getElementById('sm-submit').textContent = '＋ 添加';
  document.getElementById('sm-target-type').value = 'group';
  document.getElementById('sm-target-chat-id').value = '';
  document.getElementById('sm-target-name').value = '';
  document.getElementById('sm-msg-type').value = 'text';
  document.getElementById('sm-content').value = '';
  document.getElementById('sm-media-id').value = '';
  document.getElementById('sm-interval').value = 60;
  document.getElementById('sm-start-at').value = '';
  document.getElementById('sm-repeat').checked = true;
  document.getElementById('sm-delete-previous').checked = false;
  document.getElementById('sm-remark').value = '';
  _smBuilder.loadText('');
  toggleSmMediaRow();
  document.getElementById('sm-form-msg').textContent = '';
  document.getElementById('sm-form-msg').className = 'msg';
}

function startCreateSm() {
  resetSmForm();
  showSmEditorView();
  document.getElementById('sm-editor-view').scrollIntoView({ behavior: 'smooth' });
}

function startEditSm(r) {
  resetSmForm();
  _smEditId = r.id;
  document.getElementById('sm-edit-id').value = r.id;
  document.getElementById('sm-form-title').textContent = '✏️ 编辑消息 #' + r.id;
  document.getElementById('sm-submit').textContent = '💾 保存修改';
  document.getElementById('sm-target-type').value = r.target_type || 'group';
  document.getElementById('sm-target-chat-id').value = r.target_chat_id || '';
  document.getElementById('sm-target-name').value = r.target_name || '';
  document.getElementById('sm-msg-type').value = r.msg_type || 'text';
  document.getElementById('sm-content').value = r.content || '';
  document.getElementById('sm-media-id').value = r.media_id || '';
  document.getElementById('sm-interval').value = r.interval_minutes || 60;
  document.getElementById('sm-start-at').value = r.start_at ? String(r.start_at).replace(' ', 'T').slice(0, 16) : '';
  document.getElementById('sm-repeat').checked = !!r.repeat;
  document.getElementById('sm-delete-previous').checked = !!r.delete_previous;
  document.getElementById('sm-remark').value = r.remark || '';
  _smBuilder.loadText(r.buttons_text || '');
  toggleSmMediaRow();
  showSmEditorView();
  document.getElementById('sm-editor-view').scrollIntoView({ behavior: 'smooth' });
}

function renderScheduledMessages() {
  const tbody = document.getElementById('sm-table-body');
  const query = document.getElementById('sm-search').value.trim().toLowerCase();
  const rows = _smCache.filter(r => !query || String(r.remark || '').toLowerCase().includes(query));

  document.getElementById('sm-select-all').checked = false;
  _smSelected.forEach(id => { if (!rows.some(r => r.id === id)) _smSelected.delete(id); });
  updateSmBulkBar();

  if (!rows.length) {
    tbody.innerHTML = `<tr><td colspan="8" class="empty-state">${
      _smCache.length ? '没有匹配的定时消息。' : '暂无定时消息。'
    }</td></tr>`;
    return;
  }

  tbody.innerHTML = '';
  rows.forEach(r => {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td><input type="checkbox" class="sm-row-check" ${_smSelected.has(r.id) ? 'checked' : ''}></td>
      <td>${r.id}</td>
      <td><span class="sm-badge sm-badge-${esc(r.msg_type)}">${esc(_smMsgTypeLabels[r.msg_type] || r.msg_type)}</span></td>
      <td>
        <span class="sm-target-type">${esc(_smTargetTypeLabels[r.target_type] || r.target_type)}</span>
        <div class="sm-target-name">${esc(r.target_name || r.target_chat_id)}</div>
      </td>
      <td>${r.interval_minutes}分钟</td>
      <td>${r.start_at ? esc(formatDateTime(r.start_at)) : '-'}</td>
      <td><span class="sm-status ${r.enabled ? 'on' : 'off'}">${r.enabled ? '启用' : '停用'}</span></td>
      <td class="sm-actions">
        <button class="btn-icon edit" title="编辑">✏️</button>
        <button class="btn-icon toggle" title="启用/停用">${r.enabled ? '⏸' : '▶️'}</button>
        <button class="btn-icon danger" title="删除">🗑</button>
      </td>`;
    tr.querySelector('.sm-row-check').addEventListener('change', (e) => {
      if (e.target.checked) _smSelected.add(r.id); else _smSelected.delete(r.id);
      updateSmBulkBar();
    });
    tr.querySelector('.btn-icon.edit').addEventListener('click', () => startEditSm(r));
    tr.querySelector('.btn-icon.danger').addEventListener('click', () => deleteSm(r.id));
    tr.querySelector('.btn-icon.toggle').addEventListener('click', () => toggleSm(r.id, !r.enabled));
    tbody.appendChild(tr);
  });
}

function updateSmBulkBar() {
  const bar = document.getElementById('sm-bulk-bar');
  if (_smSelected.size > 0) {
    document.getElementById('sm-selected-count').textContent = `已选 ${_smSelected.size} 项`;
    show('sm-bulk-bar');
  } else {
    hide('sm-bulk-bar');
  }
}

async function loadScheduledMessages() {
  showSmListView();
  const tbody = document.getElementById('sm-table-body');
  tbody.innerHTML = '<tr><td colspan="8" class="empty-state">加载中…</td></tr>';
  const data = await api('GET', '/scheduled_messages');
  if (data.error) {
    tbody.innerHTML = `<tr><td colspan="8" class="msg fail">加载失败：${esc(data.error)}</td></tr>`;
    return;
  }
  _smCache = Array.isArray(data) ? data : [];
  renderScheduledMessages();
}

async function deleteSm(id) {
  if (!window.confirm('确定要删除这条定时消息吗？')) return;
  await api('DELETE', '/scheduled_messages/' + id);
  _smSelected.delete(id);
  if (_smEditId === id) resetSmForm();
  loadScheduledMessages();
}

async function toggleSm(id, enabled) {
  await api('POST', `/scheduled_messages/${id}/toggle`, { enabled });
  loadScheduledMessages();
}

document.getElementById('sm-select-all').addEventListener('change', (e) => {
  document.querySelectorAll('#sm-table-body .sm-row-check').forEach(cb => {
    cb.checked = e.target.checked;
    cb.dispatchEvent(new Event('change'));
  });
});

document.getElementById('sm-bulk-delete').addEventListener('click', async () => {
  if (!_smSelected.size) return;
  if (!window.confirm(`确定要删除已选的 ${_smSelected.size} 条定时消息吗？`)) return;
  await api('POST', '/scheduled_messages/bulk_delete', { ids: [..._smSelected] });
  _smSelected.clear();
  loadScheduledMessages();
});

document.getElementById('sm-search-btn').addEventListener('click', renderScheduledMessages);
document.getElementById('sm-search').addEventListener('input', renderScheduledMessages);
document.getElementById('sm-search-clear').addEventListener('click', () => {
  document.getElementById('sm-search').value = '';
  renderScheduledMessages();
});

document.getElementById('sm-start-create').addEventListener('click', startCreateSm);
document.getElementById('sm-back').addEventListener('click', () => { resetSmForm(); showSmListView(); });
document.getElementById('sm-cancel').addEventListener('click', () => { resetSmForm(); showSmListView(); });

document.getElementById('sm-submit').addEventListener('click', async () => {
  const msgEl = document.getElementById('sm-form-msg');
  const payload = {
    target_type:      document.getElementById('sm-target-type').value,
    target_chat_id:   document.getElementById('sm-target-chat-id').value.trim(),
    target_name:      document.getElementById('sm-target-name').value.trim(),
    msg_type:         document.getElementById('sm-msg-type').value,
    content:          document.getElementById('sm-content').value.trim(),
    media_id:         document.getElementById('sm-media-id').value.trim(),
    buttons_text:     _smBuilder.getText(),
    interval_minutes: parseInt(document.getElementById('sm-interval').value, 10),
    start_at:         document.getElementById('sm-start-at').value,
    repeat:           document.getElementById('sm-repeat').checked,
    delete_previous:  document.getElementById('sm-delete-previous').checked,
    remark:           document.getElementById('sm-remark').value.trim(),
  };
  if (!payload.target_chat_id) {
    msgEl.className = 'msg fail';
    msgEl.textContent = '目标标识不能为空';
    return;
  }
  msgEl.className = 'msg';
  msgEl.textContent = '保存中…';
  const res = _smEditId !== null
    ? await api('PUT', '/scheduled_messages/' + _smEditId, payload)
    : await api('POST', '/scheduled_messages', payload);
  if (res.ok || res.id) {
    msgEl.className = 'msg ok';
    msgEl.textContent = _smEditId !== null ? '✅ 已保存修改' : '✅ 已添加';
    resetSmForm();
    showSmListView();
    loadScheduledMessages();
  } else {
    msgEl.className = 'msg fail';
    msgEl.textContent = '❌ ' + (res.error || '失败');
  }
});

document.getElementById('sm-export').addEventListener('click', async () => {
  const data = await api('GET', '/scheduled_messages/export');
  if (data.error) { alert('导出失败：' + data.error); return; }
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = 'scheduled_messages.json';
  a.click();
  URL.revokeObjectURL(url);
});

document.getElementById('sm-import').addEventListener('click', () => {
  document.getElementById('sm-import-file').click();
});

document.getElementById('sm-import-file').addEventListener('change', async (e) => {
  const file = e.target.files[0];
  e.target.value = '';
  if (!file) return;
  let parsed;
  try {
    parsed = JSON.parse(await file.text());
  } catch (_) {
    alert('导入失败：不是有效的 JSON 文件');
    return;
  }
  const res = await api('POST', '/scheduled_messages/import', parsed);
  if (res.error) { alert('导入失败：' + res.error); return; }
  alert(`导入完成：成功 ${res.imported} 条${res.errors && res.errors.length ? `，失败 ${res.errors.length} 条` : ''}`);
  loadScheduledMessages();
});

// ── Stats ─────────────────────────────────────────────────────────────────────

async function loadStats() {
  const el = document.getElementById('stats-content');
  el.innerHTML = '<p style="color:var(--hint);padding:4px">加载中…</p>';
  const s = await api('GET', '/stats');
  if (s.error) { el.innerHTML = `<p class="msg fail">加载失败：${esc(s.error)}</p>`; return; }
  const reasonMap = s.intercept_by_reason || {};
  const reasonCards = Object.keys(reasonMap).length
    ? `<div class="card" style="margin-top:12px"><h3 class="card-title">近 7 天拦截原因</h3>
        <div class="stats-grid">${
          Object.entries(reasonMap).map(([k, v]) => `
            <div class="stat-card">
              <div class="stat-label">${esc(_logReasonLabels[k] || k)}</div>
              <div class="stat-val">${v}</div>
            </div>`).join('')
        }</div></div>`
    : '';
  el.innerHTML = `<div class="stats-grid">${
    [
      ['👥 总用户',      s.total],
      ['✅ 正常',        s.active],
      ['⛔ 封禁',        s.banned],
      ['🆕 今日新增',    s.new_today],
      ['📅 今日活跃',    s.active_today],
      ['💬 今日私聊',    s.messages_today],
      ['💬 近7天私聊',   s.messages_7d],
      ['📅 近7天活跃',   s.active_7d],
      ['🆕 近7天新增',   s.new_7d],
      ['🛡 今日拦截',    s.intercept_today],
      ['🛡 近7天拦截',   s.intercept_7d],
      ['💬 自动回复数',  s.auto_replies],
      ['🚫 过滤词数',    s.filters],
    ].map(([label, val]) => `
      <div class="stat-card">
        <div class="stat-label">${label}</div>
        <div class="stat-val">${val ?? '—'}</div>
      </div>`).join('')
  }</div>${reasonCards}`;
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
_smBuilder = initButtonBuilder(
  document.getElementById('sm-buttons-builder'),
  'sm-buttons-add-row'
);

initTheme();
initSidebar();
initTabs();
loadSettings();
