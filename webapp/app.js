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
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
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
  function createEntry(text = '', url = '') {
    const entry = document.createElement('div');
    entry.className = 'btn-entry';
    const txtInput = document.createElement('input');
    txtInput.type = 'text';
    txtInput.placeholder = '按钮文字';
    txtInput.value = text;
    const urlInput = document.createElement('input');
    urlInput.type = 'text';
    urlInput.placeholder = 'https://链接';
    urlInput.value = url;
    const delBtn = document.createElement('button');
    delBtn.className = 'btn-icon danger';
    delBtn.title = '删除此按钮';
    delBtn.textContent = '✕';
    entry.append(txtInput, urlInput, delBtn);
    delBtn.addEventListener('click', () => {
      const row = entry.parentElement;
      entry.remove();
      if (!row.querySelectorAll('.btn-entry').length) row.remove();
    });
    return entry;
  }

  function createRow(initialEntries = [['', '']]) {
    const row = document.createElement('div');
    row.className = 'btn-row';
    row.innerHTML = `
      <div class="btn-row-header">
        <span>一行按钮</span>
      </div>
      <div class="btn-row-actions">
        <button class="btn-ghost btn-sm add-btn-in-row">＋ 添加按钮</button>
        <button class="btn-icon danger remove-row" title="删除此行">✕ 删除行</button>
      </div>`;
    // Insert entries before actions
    const actions = row.querySelector('.btn-row-actions');
    initialEntries.forEach(([t, u]) => {
      row.insertBefore(createEntry(t, u), actions);
    });
    row.querySelector('.add-btn-in-row').addEventListener('click', () => {
      row.insertBefore(createEntry(), actions);
    });
    row.querySelector('.remove-row').addEventListener('click', () => row.remove());
    return row;
  }

  document.getElementById(addRowBtnId).addEventListener('click', () => {
    containerEl.appendChild(createRow());
  });

  function getText() {
    const lines = [];
    containerEl.querySelectorAll('.btn-row').forEach(row => {
      const parts = [];
      row.querySelectorAll('.btn-entry').forEach(entry => {
        const [txtEl, urlEl] = entry.querySelectorAll('input');
        const t = txtEl.value.trim();
        const u = urlEl.value.trim();
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
  document.getElementById('force-sub-channels').value = data.force_sub_text || '';
  document.getElementById('antiflood').checked      = !!data.antiflood;
  document.getElementById('alphabet-latin').checked = !!data.alphabet_latin;
  document.getElementById('force-sub-on').checked   = !!data.force_sub_on;
  if (data.bot_name) {
    document.getElementById('bot-name').textContent = '🤖 ' + data.bot_name;
  }
  hide('loading');
  show('main');
}

document.getElementById('save-settings').addEventListener('click', async () => {
  const msgEl = document.getElementById('settings-msg');
  msgEl.className = 'msg';
  msgEl.textContent = '保存中…';
  const res = await api('POST', '/settings', {
    welcome_text:      document.getElementById('welcome-text').value,
    welcome_btns_text: _welcomeBuilder.getText(),
    force_sub_text:    document.getElementById('force-sub-channels').value,
    antiflood:         document.getElementById('antiflood').checked,
    alphabet_latin:    document.getElementById('alphabet-latin').checked,
    force_sub_on:      document.getElementById('force-sub-on').checked,
  });
  if (res.ok) {
    msgEl.className = 'msg ok';
    msgEl.textContent = '✅ 保存成功';
    tg?.HapticFeedback?.notificationOccurred('success');
  } else {
    msgEl.className = 'msg fail';
    msgEl.textContent = '❌ 保存失败：' + (res.error || '未知错误');
  }
});

// ── Auto Replies ──────────────────────────────────────────────────────────────

let _arBuilder;
let _arEditId = null;

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
  document.getElementById('ar-form').scrollIntoView({ behavior: 'smooth' });
}

async function loadAutoReplies() {
  const list = document.getElementById('ar-list');
  list.innerHTML = '<p style="color:var(--hint);padding:4px">加载中…</p>';
  const data = await api('GET', '/auto_replies');
  if (data.error) { list.innerHTML = `<p class="msg fail">加载失败：${esc(data.error)}</p>`; return; }
  if (!data.length) { list.innerHTML = '<p style="color:var(--hint);padding:4px">暂无自动回复规则。</p>'; return; }
  list.innerHTML = '';
  data.forEach(r => {
    const div = document.createElement('div');
    div.className = 'ar-item';
    const buttons = (r.buttons_text || '').trim();
    div.innerHTML = `
      <div class="ar-text">
        <div class="ar-kw">🔑 ${esc(r.keyword)}</div>
        <div class="ar-reply-preview">💬 ${esc(r.reply)}</div>
        <div class="ar-meta">${esc(matchLabel(r.match_type))}${buttons ? '　🔘 有按钮' : ''}</div>
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

// ── Broadcast ─────────────────────────────────────────────────────────────────

document.getElementById('bc-send').addEventListener('click', async () => {
  const msgEl = document.getElementById('bc-msg');
  const text  = document.getElementById('bc-text').value.trim();
  if (!text) {
    msgEl.className = 'msg fail';
    msgEl.textContent = '消息内容不能为空';
    return;
  }
  if (!window.confirm('确定要向所有活跃用户群发这条消息吗？')) return;
  const btn = document.getElementById('bc-send');
  btn.disabled = true;
  msgEl.className = 'msg';
  msgEl.textContent = '发送中，请稍候…';
  const res = await api('POST', '/broadcast', { text });
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

async function loadBanned() {
  const list = document.getElementById('banned-list');
  list.innerHTML = '<p style="color:var(--hint);padding:4px">加载中…</p>';
  const data = await api('GET', '/banned');
  if (data.error) { list.innerHTML = `<p class="msg fail">加载失败：${esc(data.error)}</p>`; return; }
  if (!data.length) { list.innerHTML = '<p style="color:var(--hint);padding:4px">暂无封禁用户。</p>'; return; }
  list.innerHTML = '';
  data.forEach(u => {
    const div  = document.createElement('div');
    div.className = 'ban-item';
    const name = u.full_name
      || (u.username ? '@' + u.username : '')
      || String(u.user_id);
    div.innerHTML = `
      <div class="ban-info">👤 ${esc(name)}<small>${u.user_id}</small></div>
      <button class="btn-unban">✅ 解封</button>`;
    div.querySelector('.btn-unban').addEventListener('click', () => unban(u.user_id));
    list.appendChild(div);
  });
}

async function unban(uid) {
  await api('POST', '/unban/' + uid);
  loadBanned();
}

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

initSidebar();
initTabs();
loadSettings();
