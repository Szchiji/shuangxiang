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
  const res = await fetch(BASE + path, opts);
  return res.json();
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

// ── Tabs ──────────────────────────────────────────────────────────────────────

function initTabs() {
  document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
      document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
      btn.classList.add('active');
      document.getElementById('tab-' + btn.dataset.tab).classList.add('active');
      if (btn.dataset.tab === 'stats')      loadStats();
      if (btn.dataset.tab === 'banned')     loadBanned();
      if (btn.dataset.tab === 'auto-reply') loadAutoReplies();
    });
  });
}

// ── Settings ──────────────────────────────────────────────────────────────────

async function loadSettings() {
  const data = await api('GET', '/settings');
  if (data.error) { showError('无法加载设置：' + data.error); return; }
  document.getElementById('welcome-text').value = data.welcome_text || '';
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
  msgEl.textContent = '保存中...';
  const res = await api('POST', '/settings', {
    welcome_text:   document.getElementById('welcome-text').value,
    antiflood:      document.getElementById('antiflood').checked,
    alphabet_latin: document.getElementById('alphabet-latin').checked,
    force_sub_on:   document.getElementById('force-sub-on').checked,
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

async function loadAutoReplies() {
  const list = document.getElementById('ar-list');
  list.textContent = '加载中...';
  const data = await api('GET', '/auto_replies');
  if (data.error) { list.textContent = '加载失败：' + data.error; return; }
  if (!data.length) { list.textContent = '暂无自动回复规则。'; return; }
  list.innerHTML = '';
  data.forEach(r => {
    const div = document.createElement('div');
    div.className = 'ar-item';
    div.innerHTML = `
      <div class="ar-text">
        <div class="ar-kw">🔑 ${esc(r.keyword)}</div>
        <div>💬 ${esc(r.reply)}</div>
        <div style="font-size:11px;color:#888">${esc(r.match_type)}</div>
      </div>
      <button class="ar-del" title="删除">🗑</button>`;
    div.querySelector('.ar-del').addEventListener('click', () => deleteAR(r.id));
    list.appendChild(div);
  });
}

async function deleteAR(id) {
  await api('DELETE', '/auto_replies/' + id);
  loadAutoReplies();
}

document.getElementById('ar-add').addEventListener('click', async () => {
  const msgEl  = document.getElementById('ar-msg');
  const keyword = document.getElementById('ar-keyword').value.trim();
  const reply   = document.getElementById('ar-reply').value.trim();
  const match   = document.getElementById('ar-match').value;
  if (!keyword || !reply) {
    msgEl.className = 'msg fail';
    msgEl.textContent = '关键词和回复内容不能为空';
    return;
  }
  const res = await api('POST', '/auto_replies', { keyword, reply, match_type: match });
  if (res.id) {
    msgEl.className = 'msg ok';
    msgEl.textContent = '✅ 已添加';
    document.getElementById('ar-keyword').value = '';
    document.getElementById('ar-reply').value   = '';
    loadAutoReplies();
  } else {
    msgEl.className = 'msg fail';
    msgEl.textContent = '❌ ' + (res.error || '失败');
  }
});

// ── Banned Users ──────────────────────────────────────────────────────────────

async function loadBanned() {
  const list = document.getElementById('banned-list');
  list.textContent = '加载中...';
  const data = await api('GET', '/banned');
  if (data.error) { list.textContent = '加载失败：' + data.error; return; }
  if (!data.length) { list.textContent = '暂无封禁用户。'; return; }
  list.innerHTML = '';
  data.forEach(u => {
    const div  = document.createElement('div');
    div.className = 'ban-item';
    const name = u.full_name
      || (u.username ? '@' + u.username : '')
      || String(u.user_id);
    div.innerHTML = `
      <div class="ban-info">👤 ${esc(name)}
        <span style="color:#888">${u.user_id}</span></div>
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
  el.textContent = '加载中...';
  const s = await api('GET', '/stats');
  if (s.error) { el.textContent = '加载失败：' + s.error; return; }
  el.innerHTML = [
    ['👥 总用户',    s.total],
    ['✅ 正常',      s.active],
    ['⛔ 封禁',      s.banned],
    ['📅 近7天活跃', s.active_7d],
    ['🆕 近7天新增', s.new_7d],
  ].map(([label, val]) => `
    <div class="stat-card">
      <span>${label}</span>
      <span class="stat-val">${val}</span>
    </div>`).join('');
}

// ── Init ──────────────────────────────────────────────────────────────────────

tg?.ready();
tg?.expand();
initTabs();
loadSettings();
