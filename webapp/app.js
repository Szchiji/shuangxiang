'use strict';

/* globals window, document, location, fetch */

const tg = window.Telegram?.WebApp;
const _params = new URLSearchParams(location.search);
const tenantId = _params.get('tenant_id') || '0';
const initData = tg?.initData || '';

const BASE    = `/api/${tenantId}`;
const HEADERS = { 'Content-Type': 'application/json', 'X-Init-Data': initData };

function elRef(idOrEl) {
  if (!idOrEl) return null;
  return typeof idOrEl === 'string' ? document.getElementById(idOrEl) : idOrEl;
}

function show(idOrEl) {
  const el = elRef(idOrEl);
  if (!el) return;
  el.classList.remove('is-hidden');
  el.hidden = false;
  // removeProperty restores stylesheet display (block/flex/etc.)
  el.style.removeProperty('display');
  // Fallback if element was only hidden via inline style / CSS and has no visible display
  if (getComputedStyle(el).display === 'none') {
    const tag = el.tagName;
    el.style.display = (tag === 'BUTTON' || tag === 'SPAN' || tag === 'A') ? 'inline-flex' : 'block';
  }
}
function hide(idOrEl) {
  const el = elRef(idOrEl);
  if (!el) return;
  el.classList.add('is-hidden');
  el.hidden = true;
  el.style.display = 'none';
}

/** Force a panel into view (Telegram Mini App scroll is unreliable). */
function revealPanel(idOrEl) {
  const el = elRef(idOrEl);
  if (!el) return null;
  show(el);
  try {
    el.scrollIntoView({ behavior: 'smooth', block: 'start' });
  } catch (_) {
    try { el.scrollIntoView(true); } catch (__) {}
  }
  // Nudge window scroll for Mini App webviews that ignore element scrollIntoView
  try {
    const top = el.getBoundingClientRect().top + (window.pageYOffset || 0) - 12;
    window.scrollTo({ top: Math.max(0, top), behavior: 'smooth' });
  } catch (_) {}
  return el;
}

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

function isMobileLayout() {
  return window.matchMedia && window.matchMedia('(max-width: 720px)').matches;
}

function initSidebar() {
  const sidebar = document.getElementById('sidebar');
  if (!sidebar) return;

  const toggleBtn = document.getElementById('sidebar-toggle');
  const hideBtn = document.getElementById('sidebar-hide');
  const reopenBtn = document.getElementById('sidebar-reopen');
  let backdrop = document.getElementById('sidebar-backdrop');
  if (!backdrop) {
    backdrop = document.createElement('button');
    backdrop.type = 'button';
    backdrop.id = 'sidebar-backdrop';
    backdrop.className = 'sidebar-backdrop';
    backdrop.setAttribute('aria-label', '关闭侧栏');
    backdrop.hidden = true;
    sidebar.insertAdjacentElement('afterend', backdrop);
  }

  const KEY = 'bh_sidebar_mode'; // '', 'collapsed', 'hidden'
  // Remember preferred desktop mode separately so mobile hide doesn't wipe collapse pref
  const KEY_DESKTOP = 'bh_sidebar_mode_desktop';

  function setReopenVisible(visible) {
    if (!reopenBtn) return;
    if (visible) {
      reopenBtn.hidden = false;
      reopenBtn.classList.remove('is-hidden');
      reopenBtn.style.display = 'inline-flex';
      reopenBtn.setAttribute('aria-hidden', 'false');
    } else {
      reopenBtn.hidden = true;
      reopenBtn.classList.add('is-hidden');
      reopenBtn.style.display = 'none';
      reopenBtn.setAttribute('aria-hidden', 'true');
    }
  }

  function setBackdrop(visible) {
    if (!backdrop) return;
    backdrop.hidden = !visible;
    backdrop.classList.toggle('show', !!visible);
    document.body.classList.toggle('sidebar-open', !!visible);
  }

  function updateChrome(effective, mobile) {
    if (toggleBtn) {
      // Mobile: collapse toggle is redundant with ✕ close — hide it entirely.
      if (mobile) {
        toggleBtn.hidden = true;
        toggleBtn.style.display = 'none';
        toggleBtn.setAttribute('aria-hidden', 'true');
      } else {
        toggleBtn.hidden = false;
        toggleBtn.style.display = '';
        toggleBtn.setAttribute('aria-hidden', 'false');
        const collapsed = effective === 'collapsed';
        toggleBtn.setAttribute('aria-label', collapsed ? '展开侧栏' : '折叠侧栏');
        toggleBtn.title = collapsed ? '展开侧栏（显示文字）' : '折叠侧栏（仅图标）';
      }
    }
    if (hideBtn) {
      // Close control: always available while sidebar is visible (mobile + desktop).
      const closed = effective === 'hidden';
      hideBtn.hidden = closed;
      hideBtn.style.display = closed ? 'none' : '';
      hideBtn.setAttribute('aria-label', '关闭侧栏');
      hideBtn.title = '关闭侧栏';
    }
    document.documentElement.setAttribute('data-sidebar', effective || 'expanded');
  }

  function applyMode(mode, { persist = true, asDrawer = false } = {}) {
    const mobile = isMobileLayout();
    // Compact icon-rail is awkward on very narrow screens — keep labels visible.
    let effective = mode || '';
    if (mobile && effective === 'collapsed') effective = '';

    sidebar.classList.remove('collapsed', 'hidden', 'drawer-open');

    if (effective === 'collapsed') {
      sidebar.classList.add('collapsed');
      setBackdrop(false);
      setReopenVisible(false);
    } else if (effective === 'hidden') {
      sidebar.classList.add('hidden');
      setBackdrop(false);
      setReopenVisible(true);
    } else {
      // expanded
      if (mobile && asDrawer) {
        sidebar.classList.add('drawer-open');
        setBackdrop(true);
        setReopenVisible(false);
      } else {
        setBackdrop(false);
        setReopenVisible(false);
      }
    }

    updateChrome(effective, mobile);

    if (persist) {
      try {
        if (!mobile) {
          localStorage.setItem(KEY_DESKTOP, effective === 'collapsed' || effective === 'hidden' ? effective : '');
        }
        localStorage.setItem(
          KEY,
          effective === 'collapsed' || effective === 'hidden' ? effective : ''
        );
      } catch (_) {}
    }
  }

  function currentMode() {
    if (sidebar.classList.contains('hidden')) return 'hidden';
    if (sidebar.classList.contains('collapsed')) return 'collapsed';
    return '';
  }

  const saved = (() => {
    try {
      const v = localStorage.getItem(KEY) || '';
      return (v === 'collapsed' || v === 'hidden') ? v : '';
    } catch (_) { return ''; }
  })();
  applyMode(saved, { persist: false });

  // Desktop only: ☰ toggles icon-rail collapse. Mobile uses ✕ / floating reopen.
  toggleBtn?.addEventListener('click', (e) => {
    e.preventDefault();
    e.stopPropagation();
    if (isMobileLayout()) {
      // Safety: if CSS hide fails, still act as close rather than a second close twin.
      if (sidebar.classList.contains('hidden')) {
        applyMode('', { asDrawer: true });
      } else {
        applyMode('hidden');
      }
      return;
    }
    if (sidebar.classList.contains('hidden')) {
      applyMode('');
      return;
    }
    applyMode(sidebar.classList.contains('collapsed') ? '' : 'collapsed');
  });
  hideBtn?.addEventListener('click', (e) => {
    e.preventDefault();
    e.stopPropagation();
    applyMode('hidden');
  });
  reopenBtn?.addEventListener('click', (e) => {
    e.preventDefault();
    e.stopPropagation();
    applyMode('', { asDrawer: isMobileLayout() });
  });
  backdrop?.addEventListener('click', (e) => {
    e.preventDefault();
    applyMode('hidden');
  });

  // Close mobile drawer after navigating
  sidebar.querySelectorAll('.nav-item').forEach(item => {
    item.addEventListener('click', () => {
      if (isMobileLayout() && sidebar.classList.contains('drawer-open')) {
        applyMode('hidden');
      }
    });
  });

  window.addEventListener('resize', () => {
    const mobile = isMobileLayout();
    let mode = currentMode();
    if (!mobile) {
      try {
        const desk = localStorage.getItem(KEY_DESKTOP);
        if (desk === 'collapsed' || desk === 'hidden' || desk === '') mode = desk || '';
      } catch (_) {}
    } else if (mode === 'collapsed') {
      mode = '';
    }
    // Drop drawer overlay when rotating to desktop
    applyMode(mode, { persist: false, asDrawer: false });
  });

  // Collapsible nav groups
  const gkey = 'bh_nav_groups';
  let collapsedGroups = {};
  try { collapsedGroups = JSON.parse(localStorage.getItem(gkey) || '{}') || {}; } catch (_) { collapsedGroups = {}; }

  document.querySelectorAll('.nav-group').forEach(group => {
    const name = group.dataset.group;
    const toggle = group.querySelector('.nav-group-toggle');
    if (collapsedGroups[name]) group.classList.add('collapsed');
    toggle?.addEventListener('click', (e) => {
      e.preventDefault();
      e.stopPropagation();
      group.classList.toggle('collapsed');
      collapsedGroups[name] = group.classList.contains('collapsed');
      try { localStorage.setItem(gkey, JSON.stringify(collapsedGroups)); } catch (_) {}
      toggle.setAttribute('aria-expanded', group.classList.contains('collapsed') ? 'false' : 'true');
    });
    if (toggle) {
      toggle.setAttribute('aria-expanded', group.classList.contains('collapsed') ? 'false' : 'true');
    }
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
      if (btn.dataset.tab === 'stats')         loadStats();
      if (btn.dataset.tab === 'banned')        loadBanned();
      if (btn.dataset.tab === 'auto-reply')    loadAutoReplies();
      if (btn.dataset.tab === 'filters')       loadFilters();
      if (btn.dataset.tab === 'force-sub')     loadForceSub();
      if (btn.dataset.tab === 'logs')          loadInterceptLogs();
      if (btn.dataset.tab === 'scheduled')     loadScheduledMessages();
      if (btn.dataset.tab === 'broadcast')     loadBroadcastEstimate();
      if (btn.dataset.tab === 'users')         loadOpsUsers();
      if (btn.dataset.tab === 'quick-replies') loadQuickReplies();
      if (btn.dataset.tab === 'staff')         { loadStaff(); loadAuditLogs(); }
    });
  });
}

// ── Interactive button builder ────────────────────────────────────────────────

/**
 * Initialise an interactive button-row builder inside `containerEl`.
 * `addRowBtnId` is the id of the "add row" button below the builder.
 * Returns { getText, loadText } — serialises to "text - url && text - url\ntext - url" format.
 */
function initButtonBuilder(containerEl, addRowBtnId) {
  if (!containerEl) {
    return { getText: () => '', loadText: () => {} };
  }

  /**
   * Each button is stored as { text, url } on the pill element.
   * Clicking "＋ 添加按钮" / a pill opens a clear inline editor panel.
   * Event delegation keeps handlers alive after loadText() re-renders rows.
   */

  function closeInlineForm(row) {
    row?.querySelector('.btn-inline-form')?.remove();
  }

  function closeAllForms() {
    containerEl.querySelectorAll('.btn-inline-form').forEach(f => f.remove());
  }

  function createPill(text, url) {
    const pill = document.createElement('button');
    pill.type = 'button';
    pill.className = 'btn-pill';
    pill.dataset.btnText = text;
    pill.dataset.btnUrl = url;
    pill.title = url || '点击编辑';
    pill.innerHTML = `<span class="pill-label">${esc(text)}</span><span class="pill-edit-hint">✏️</span>`;
    return pill;
  }

  function showInlineForm(row, pillEl) {
    if (!row) return;
    closeAllForms();

    const pillsArea = row.querySelector('.btn-pills-area');
    if (!pillsArea) return;

    const isEdit = !!pillEl;
    const initText = isEdit ? (pillEl.dataset.btnText || '') : '';
    const initUrl = isEdit ? (pillEl.dataset.btnUrl || '') : '';

    const form = document.createElement('div');
    form.className = 'btn-inline-form open';
    form.setAttribute('role', 'dialog');
    form.setAttribute('aria-label', isEdit ? '编辑按钮' : '添加按钮');
    form.innerHTML = `
      <div class="btn-inline-title">${isEdit ? '✏️ 编辑按钮' : '➕ 添加按钮'}</div>
      <p class="btn-inline-hint">填写按钮显示文字和点击后打开的链接</p>
      <label class="btn-inline-field">按钮文字
        <input class="btn-inline-txt" type="text" placeholder="例如：官方频道" value="${esc(initText)}" maxlength="64" autocomplete="off">
      </label>
      <label class="btn-inline-field">链接 URL
        <input class="btn-inline-url" type="url" placeholder="https://t.me/..." value="${esc(initUrl)}" autocomplete="off">
      </label>
      <div class="btn-inline-actions">
        <button type="button" class="btn-primary btn-sm btn-inline-save">💾 保存</button>
        <button type="button" class="btn-ghost btn-sm btn-inline-cancel">取消</button>
        ${isEdit ? '<button type="button" class="btn-icon danger btn-inline-del" title="删除此按钮">🗑</button>' : ''}
      </div>`;

    // Place editor after pills so it is always visible under the row content
    const actions = row.querySelector('.btn-row-actions');
    if (actions) row.insertBefore(form, actions);
    else row.appendChild(form);

    const txtInput = form.querySelector('.btn-inline-txt');
    const urlInput = form.querySelector('.btn-inline-url');

    const save = () => {
      const t = txtInput.value.trim();
      const u = urlInput.value.trim();
      txtInput.classList.toggle('invalid', !t);
      urlInput.classList.toggle('invalid', !u);
      if (!t || !u) {
        (!t ? txtInput : urlInput).focus();
        return;
      }
      if (isEdit && pillEl.isConnected) {
        pillEl.dataset.btnText = t;
        pillEl.dataset.btnUrl = u;
        const label = pillEl.querySelector('.pill-label');
        if (label) label.textContent = t;
        pillEl.title = u;
      } else {
        pillsArea.appendChild(createPill(t, u));
      }
      closeInlineForm(row);
      tg?.HapticFeedback?.impactOccurred?.('light');
    };

    form.querySelector('.btn-inline-save')?.addEventListener('click', (e) => {
      e.preventDefault();
      e.stopPropagation();
      save();
    });
    form.querySelector('.btn-inline-cancel')?.addEventListener('click', (e) => {
      e.preventDefault();
      e.stopPropagation();
      closeInlineForm(row);
      if (!row.querySelector('.btn-pill')) row.remove();
    });
    form.querySelector('.btn-inline-del')?.addEventListener('click', (e) => {
      e.preventDefault();
      e.stopPropagation();
      pillEl?.remove();
      closeInlineForm(row);
      if (!row.querySelector('.btn-pill')) row.remove();
    });

    // Enter in either field saves
    [txtInput, urlInput].forEach(input => {
      input?.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
          e.preventDefault();
          save();
        } else if (e.key === 'Escape') {
          e.preventDefault();
          form.querySelector('.btn-inline-cancel')?.click();
        }
      });
    });

    // Ensure the editor is on-screen (critical in Telegram Mini App)
    try {
      form.scrollIntoView({ behavior: 'smooth', block: 'center' });
    } catch (_) {
      try { form.scrollIntoView(true); } catch (__) {}
    }
    setTimeout(() => {
      try { txtInput?.focus(); } catch (_) {}
    }, 50);
  }

  function createRow(initialEntries = []) {
    const row = document.createElement('div');
    row.className = 'btn-row';

    const header = document.createElement('div');
    header.className = 'btn-row-header';
    header.innerHTML = '<span>一行按钮</span>';

    const removeRowBtn = document.createElement('button');
    removeRowBtn.type = 'button';
    removeRowBtn.className = 'btn-icon danger remove-row';
    removeRowBtn.title = '删除此行';
    removeRowBtn.setAttribute('aria-label', '删除此行');
    removeRowBtn.textContent = '✕';
    header.appendChild(removeRowBtn);

    const pillsArea = document.createElement('div');
    pillsArea.className = 'btn-pills-area';

    const actions = document.createElement('div');
    actions.className = 'btn-row-actions';
    const addBtnInRow = document.createElement('button');
    addBtnInRow.type = 'button';
    addBtnInRow.className = 'btn-ghost btn-sm add-btn-in-row';
    addBtnInRow.textContent = '＋ 添加按钮';
    actions.appendChild(addBtnInRow);

    row.append(header, pillsArea, actions);

    (initialEntries || []).forEach(([t, u]) => {
      if (t && u) pillsArea.appendChild(createPill(t, u));
    });

    return row;
  }

  // Event delegation — survives loadText() re-renders
  containerEl.addEventListener('click', (e) => {
    const target = e.target;
    if (!(target instanceof Element)) return;

    const removeRow = target.closest('.remove-row');
    if (removeRow && containerEl.contains(removeRow)) {
      e.preventDefault();
      e.stopPropagation();
      removeRow.closest('.btn-row')?.remove();
      return;
    }

    const addInRow = target.closest('.add-btn-in-row');
    if (addInRow && containerEl.contains(addInRow)) {
      e.preventDefault();
      e.stopPropagation();
      const row = addInRow.closest('.btn-row');
      showInlineForm(row, null);
      return;
    }

    const pill = target.closest('.btn-pill');
    if (pill && containerEl.contains(pill)) {
      e.preventDefault();
      e.stopPropagation();
      showInlineForm(pill.closest('.btn-row'), pill);
    }
  });

  const addRowBtn = document.getElementById(addRowBtnId);
  if (addRowBtn) {
    addRowBtn.type = 'button';
    addRowBtn.addEventListener('click', (e) => {
      e.preventDefault();
      e.stopPropagation();
      const row = createRow();
      containerEl.appendChild(row);
      showInlineForm(row, null);
    });
  }

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
    if (!raw || !String(raw).trim()) return;
    String(raw).trim().split('\n').forEach(line => {
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
  document.getElementById('away-on').checked = !!data.away_on;
  document.getElementById('away-msg').value = data.away_msg || '';
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
    const nameEl = document.getElementById('bot-name');
    nameEl.textContent = '🤖 ' + data.bot_name;
    nameEl.title = data.bot_name;
  }
  hide('loading');
  show('main');
}

document.getElementById('save-welcome-text')?.addEventListener('click', async () => {
  await saveSettingsPartial({
    welcome_text:      document.getElementById('welcome-text').value,
  }, 'welcome-text-msg', '✅ 欢迎语已保存');
});

document.getElementById('save-welcome-buttons')?.addEventListener('click', async () => {
  await saveSettingsPartial({
    welcome_btns_text: _welcomeBuilder.getText(),
  }, 'welcome-buttons-msg', '✅ 欢迎按钮已保存');
});

document.getElementById('save-welcome-media')?.addEventListener('click', async () => {
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

document.getElementById('clear-welcome-media')?.addEventListener('click', async () => {
  document.getElementById('welcome-media-type').value = '';
  document.getElementById('welcome-media-id').value = '';
  await saveSettingsPartial({
    welcome_media_type: '',
    welcome_media_id: '',
  }, 'welcome-media-msg', '✅ 已清除封面');
});

document.getElementById('save-security-settings')?.addEventListener('click', async () => {
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

document.getElementById('save-away-settings')?.addEventListener('click', async () => {
  await saveSettingsPartial({
    away_on:  document.getElementById('away-on').checked,
    away_msg: document.getElementById('away-msg').value,
  }, 'away-msg-status', '✅ 离开设置已保存');
});

// ── Auto Replies ──────────────────────────────────────────────────────────────

let _arBuilder;
let _arEditId = null;
let _autoRepliesCache = [];

function showArListView() {
  show('ar-hero');
  show('ar-search-card');
  show('ar-list-view');
  hide('ar-editor-view');
}

function showArEditorView() {
  hide('ar-list-view');
  hide('ar-search-card');
  show('ar-hero');
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

document.getElementById('ar-submit')?.addEventListener('click', async () => {
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

document.getElementById('ar-cancel')?.addEventListener('click', resetArForm);
document.getElementById('ar-back')?.addEventListener('click', resetArForm);
document.getElementById('ar-start-create')?.addEventListener('click', startCreateAr);
document.getElementById('ar-search')?.addEventListener('input', renderAutoReplies);
document.getElementById('ar-filter-match')?.addEventListener('change', renderAutoReplies);

document.getElementById('ar-export')?.addEventListener('click', async () => {
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
document.getElementById('ar-import')?.addEventListener('click', () => {
  document.getElementById('ar-import-file').click();
});
document.getElementById('ar-import-file')?.addEventListener('change', async (e) => {
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
  show('fl-hero');
  show('fl-search-card');
  show('fl-list-card');
  hide('fl-editor-card');
  const tab = document.getElementById('tab-filters');
  if (tab) tab.classList.remove('is-editing');
}

function showFlEditorView() {
  // Keep hero actions visible (same pattern as scheduled messages)
  show('fl-hero');
  hide('fl-search-card');
  hide('fl-list-card');
  revealPanel('fl-editor-card');
  const tab = document.getElementById('tab-filters');
  if (tab) tab.classList.add('is-editing');
}

function resetFlFormFields() {
  _flEditId = null;
  const editId = document.getElementById('fl-edit-id');
  if (editId) editId.value = '';
  const title = document.getElementById('fl-form-title');
  if (title) title.textContent = '➕ 添加过滤词';
  const hint = document.getElementById('fl-form-hint');
  if (hint) {
    hint.textContent = '支持包含匹配或正则表达式。可一次粘贴多个词，每行一个。';
  }
  const submit = document.getElementById('fl-submit');
  if (submit) submit.textContent = '➕ 添加';
  const kw = document.getElementById('fl-keyword');
  if (kw) {
    kw.value = '';
    kw.rows = 3;
  }
  const match = document.getElementById('fl-match');
  if (match) match.value = 'contains';
  const msg = document.getElementById('fl-msg');
  if (msg) {
    msg.textContent = '';
    msg.className = 'msg';
  }
}

function resetFlForm() {
  resetFlFormFields();
  showFlListView();
}

function startCreateFl() {
  // Ensure filters tab is active so the editor is not display:none via .tab
  const tabBtn = document.querySelector('.nav-item[data-tab="filters"]');
  const tab = document.getElementById('tab-filters');
  if (tab && !tab.classList.contains('active')) {
    document.querySelectorAll('.nav-item').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    tabBtn?.classList.add('active');
    tab.classList.add('active');
  }
  resetFlFormFields();
  showFlEditorView();
  setTimeout(() => {
    try { document.getElementById('fl-keyword')?.focus(); } catch (_) {}
  }, 60);
  tg?.HapticFeedback?.impactOccurred?.('light');
}

function startEditFl(r) {
  _flEditId = r.id;
  const editId = document.getElementById('fl-edit-id');
  if (editId) editId.value = r.id;
  const title = document.getElementById('fl-form-title');
  if (title) title.textContent = '✏️ 编辑过滤词';
  const hint = document.getElementById('fl-form-hint');
  if (hint) {
    hint.textContent = '修改关键词或匹配方式后保存。编辑时一次只能改一条。';
  }
  const submit = document.getElementById('fl-submit');
  if (submit) submit.textContent = '💾 保存修改';
  const kw = document.getElementById('fl-keyword');
  if (kw) {
    kw.value = r.keyword || '';
    kw.rows = 2;
  }
  const match = document.getElementById('fl-match');
  if (match) match.value = r.match_type || 'contains';
  const msg = document.getElementById('fl-msg');
  if (msg) {
    msg.textContent = '';
    msg.className = 'msg';
  }
  showFlEditorView();
  setTimeout(() => {
    try { document.getElementById('fl-keyword')?.focus(); } catch (_) {}
  }, 60);
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

async function loadFilters({ keepEditor = false } = {}) {
  const list = document.getElementById('fl-list');
  const tab = document.getElementById('tab-filters');
  const editing = !!(tab && tab.classList.contains('is-editing'));
  if (!(keepEditor && editing)) {
    showFlListView();
  }
  if (list) list.innerHTML = '<p class="empty-state">加载中…</p>';
  const data = await api('GET', '/filters');
  // A concurrent "add" click may have opened the editor while we were fetching.
  const stillEditing = !!(tab && tab.classList.contains('is-editing'));
  if (data && data.error) {
    if (list && !stillEditing) {
      list.innerHTML = `<p class="msg fail">加载失败：${esc(data.error)}</p>`;
    }
    return;
  }
  _filtersCache = Array.isArray(data) ? data : [];
  if (stillEditing) return; // don't yank the open editor closed
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

async function submitFilterForm() {
  const msgEl = document.getElementById('fl-msg');
  const btn = document.getElementById('fl-submit');
  if (!msgEl || !btn) return;
  const raw = document.getElementById('fl-keyword')?.value || '';
  const match = document.getElementById('fl-match')?.value || 'contains';
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
      const kw = document.getElementById('fl-keyword');
      if (kw) kw.value = '';
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
}

async function exportFilters() {
  const data = await api('GET', '/filters/export');
  if (data.error) { alert('导出失败：' + data.error); return; }
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = 'filters.json';
  a.click();
  URL.revokeObjectURL(url);
}

async function importFiltersFile(file) {
  if (!file) return;
  let parsed;
  const text = await file.text();
  try {
    parsed = JSON.parse(text);
  } catch (_) {
    parsed = {
      items: text.split(/\r?\n/).map(l => l.trim()).filter(Boolean)
        .map(keyword => ({ keyword, match_type: 'contains' })),
    };
  }
  const res = await api('POST', '/filters/import', parsed);
  if (res.error) { alert('导入失败：' + res.error); return; }
  alert(`导入完成：成功 ${res.imported} 条${res.errors && res.errors.length ? `，失败 ${res.errors.length} 条` : ''}`);
  loadFilters();
}

function bindFilterUi() {
  document.getElementById('fl-submit')?.addEventListener('click', (e) => {
    e.preventDefault();
    submitFilterForm();
  });
  document.getElementById('fl-start-create')?.addEventListener('click', (e) => {
    e.preventDefault();
    e.stopPropagation();
    startCreateFl();
  });
  document.getElementById('fl-cancel')?.addEventListener('click', (e) => {
    e.preventDefault();
    resetFlForm();
  });
  document.getElementById('fl-back')?.addEventListener('click', (e) => {
    e.preventDefault();
    resetFlForm();
  });
  document.getElementById('fl-search')?.addEventListener('input', renderFilters);
  document.getElementById('fl-filter-match')?.addEventListener('change', renderFilters);
  document.getElementById('fl-export')?.addEventListener('click', (e) => {
    e.preventDefault();
    exportFilters();
  });
  document.getElementById('fl-import')?.addEventListener('click', (e) => {
    e.preventDefault();
    document.getElementById('fl-import-file')?.click();
  });
  document.getElementById('fl-import-file')?.addEventListener('change', async (e) => {
    const file = e.target.files?.[0];
    e.target.value = '';
    await importFiltersFile(file);
  });
}

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

document.getElementById('fsub-save-btn')?.addEventListener('click', async () => {
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

document.getElementById('fsub-save-settings')?.addEventListener('click', async () => {
  await saveSettingsPartial({
    force_sub_on: document.getElementById('force-sub-on').checked,
    force_sub_msg: document.getElementById('fsub-msg-text').value,
  }, 'fsub-save-msg-result', '✅ 规则设置已保存');
});

document.getElementById('fsub-start-add')?.addEventListener('click', startCreateFsub);
document.getElementById('fsub-open-settings')?.addEventListener('click', () => showFsubView('fsub-settings-view'));
document.getElementById('fsub-back-from-editor')?.addEventListener('click', resetFsubEditor);
document.getElementById('fsub-cancel-btn')?.addEventListener('click', resetFsubEditor);
document.getElementById('fsub-back-from-settings')?.addEventListener('click', () => showFsubView('fsub-list-view'));

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

document.getElementById('bc-send')?.addEventListener('click', async () => {
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
  _usersCache = Array.isArray(data) ? data : (data.items || []);
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

document.getElementById('banned-search')?.addEventListener('input', renderBanned);
document.getElementById('ban-submit')?.addEventListener('click', () => {
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
document.getElementById('users-search')?.addEventListener('input', () => {
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

document.getElementById('logs-reason')?.addEventListener('change', loadInterceptLogs);
document.getElementById('logs-refresh')?.addEventListener('click', loadInterceptLogs);

// ── Scheduled Messages ──────────────────────────────────────────────────────

let _smBuilder;
let _smEditId = null;
let _smCache = [];
let _smSelected = new Set();

const _smMsgTypeLabels = { text: '文字', photo: '图片', video: '视频', document: '文件' };
const _smTargetTypeLabels = { group: '群组', channel: '频道' };

function showSmListView() {
  show('sm-list-view');
  show('sm-search-card');
  show('sm-table-card');
  hide('sm-editor-view');
}

function showSmEditorView() {
  show('sm-list-view');
  hide('sm-search-card');
  hide('sm-table-card');
  show('sm-editor-view');
}

function toggleSmMediaRow() {
  const type = document.getElementById('sm-msg-type').value;
  if (type === 'text') hide('sm-media-row');
  else show('sm-media-row');
}
document.getElementById('sm-msg-type')?.addEventListener('change', toggleSmMediaRow);

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

document.getElementById('sm-select-all')?.addEventListener('change', (e) => {
  document.querySelectorAll('#sm-table-body .sm-row-check').forEach(cb => {
    cb.checked = e.target.checked;
    cb.dispatchEvent(new Event('change'));
  });
});

document.getElementById('sm-bulk-delete')?.addEventListener('click', async () => {
  if (!_smSelected.size) return;
  if (!window.confirm(`确定要删除已选的 ${_smSelected.size} 条定时消息吗？`)) return;
  await api('POST', '/scheduled_messages/bulk_delete', { ids: [..._smSelected] });
  _smSelected.clear();
  loadScheduledMessages();
});

document.getElementById('sm-search-btn')?.addEventListener('click', renderScheduledMessages);
document.getElementById('sm-search')?.addEventListener('input', renderScheduledMessages);
document.getElementById('sm-search-clear')?.addEventListener('click', () => {
  document.getElementById('sm-search').value = '';
  renderScheduledMessages();
});

document.getElementById('sm-start-create')?.addEventListener('click', startCreateSm);
document.getElementById('sm-back')?.addEventListener('click', () => { resetSmForm(); showSmListView(); });
document.getElementById('sm-cancel')?.addEventListener('click', () => { resetSmForm(); showSmListView(); });

document.getElementById('sm-submit')?.addEventListener('click', async () => {
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

document.getElementById('sm-export')?.addEventListener('click', async () => {
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

document.getElementById('sm-import')?.addEventListener('click', () => {
  document.getElementById('sm-import-file').click();
});

document.getElementById('sm-import-file')?.addEventListener('change', async (e) => {
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

// ── Users ops (notes / tags / session) ────────────────────────────────────────

const _sessionLabels = { open: '未处理', pending: '处理中', resolved: '已解决' };
let _opsUsersCache = [];
let _opsEditUid = null;
let _opsSearchTimer = null;

function renderOpsUsers() {
  const list = document.getElementById('ops-users-list');
  if (!_opsUsersCache.length) {
    list.innerHTML = '<p class="empty-state">暂无用户或无匹配结果。</p>';
    return;
  }
  list.innerHTML = '';
  _opsUsersCache.forEach(u => {
    const div = document.createElement('div');
    div.className = 'ban-item';
    const name = u.full_name || (u.username ? '@' + u.username : String(u.user_id));
    const tags = u.tags ? `<small>🏷 ${esc(u.tags)}</small>` : '';
    const notes = u.notes ? `<div>${esc(summarizeText(u.notes, 60))}</div>` : '';
    div.innerHTML = `
      <div class="ban-info">
        <div class="ban-name">👤 ${esc(name)} · ${_sessionLabels[u.session_status] || u.session_status || 'open'}</div>
        <small>ID: ${esc(String(u.user_id))}${u.last_seen ? ' · ' + esc(formatDateTime(u.last_seen)) : ''}</small>
        ${tags}${notes}
      </div>
      <button class="btn-ghost btn-sm ops-edit">编辑</button>`;
    div.querySelector('.ops-edit').addEventListener('click', () => openOpsEditor(u));
    list.appendChild(div);
  });
}

function openOpsEditor(u) {
  _opsEditUid = u.user_id;
  document.getElementById('ops-edit-uid').textContent = '#' + u.user_id;
  document.getElementById('ops-notes').value = u.notes || '';
  document.getElementById('ops-tags').value = u.tags || '';
  document.getElementById('ops-session-status').value = u.session_status || 'open';
  document.getElementById('ops-edit-msg').textContent = '';
  show('ops-user-editor');
}

async function loadOpsUsers() {
  const list = document.getElementById('ops-users-list');
  list.innerHTML = '<p class="empty-state">加载中…</p>';
  const q = document.getElementById('ops-users-search').value.trim();
  const st = document.getElementById('ops-session-filter').value;
  let path = '/users?limit=50';
  if (q) path += '&q=' + encodeURIComponent(q);
  if (st) path += '&session_status=' + encodeURIComponent(st);
  const data = await api('GET', path);
  if (data.error) {
    list.innerHTML = `<p class="msg fail">加载失败：${esc(data.error)}</p>`;
    return;
  }
  _opsUsersCache = Array.isArray(data) ? data : (data.items || []);
  const total = Array.isArray(data) ? _opsUsersCache.length : (data.total ?? _opsUsersCache.length);
  document.getElementById('ops-users-summary').textContent = `共 ${total} 位用户`;
  renderOpsUsers();
}

document.getElementById('ops-users-refresh')?.addEventListener('click', loadOpsUsers);
document.getElementById('ops-session-filter')?.addEventListener('change', loadOpsUsers);
document.getElementById('ops-users-search')?.addEventListener('input', () => {
  if (_opsSearchTimer) clearTimeout(_opsSearchTimer);
  _opsSearchTimer = setTimeout(loadOpsUsers, 300);
});
document.getElementById('ops-close-editor')?.addEventListener('click', () => {
  hide('ops-user-editor');
  _opsEditUid = null;
});
document.getElementById('ops-save-user')?.addEventListener('click', async () => {
  if (!_opsEditUid) return;
  const msgEl = document.getElementById('ops-edit-msg');
  msgEl.className = 'msg';
  msgEl.textContent = '保存中…';
  const res = await api('PATCH', '/users/' + _opsEditUid, {
    notes: document.getElementById('ops-notes').value,
    tags: document.getElementById('ops-tags').value,
    session_status: document.getElementById('ops-session-status').value,
  });
  if (res.ok) {
    msgEl.className = 'msg ok';
    msgEl.textContent = '✅ 已保存';
    loadOpsUsers();
  } else {
    msgEl.className = 'msg fail';
    msgEl.textContent = '❌ ' + (res.error || '保存失败');
  }
});

// ── Quick replies ─────────────────────────────────────────────────────────────

let _qrEditId = null;
let _quickRepliesCache = [];

function showQrListView() {
  show('qr-hero');
  show('qr-list-card');
  hide('qr-editor-card');
  const tab = document.getElementById('tab-quick-replies');
  if (tab) tab.classList.remove('is-editing');
}

function showQrEditorView() {
  show('qr-hero');
  hide('qr-list-card');
  revealPanel('qr-editor-card');
  const tab = document.getElementById('tab-quick-replies');
  if (tab) tab.classList.add('is-editing');
}

function resetQrFormFields() {
  _qrEditId = null;
  const editId = document.getElementById('qr-edit-id');
  if (editId) editId.value = '';
  const title = document.getElementById('qr-title');
  const content = document.getElementById('qr-content');
  const formTitle = document.getElementById('qr-form-title');
  const submit = document.getElementById('qr-submit');
  const msg = document.getElementById('qr-msg');
  if (title) title.value = '';
  if (content) content.value = '';
  if (formTitle) formTitle.textContent = '➕ 添加话术模板';
  if (submit) submit.textContent = '＋ 添加模板';
  if (msg) {
    msg.textContent = '';
    msg.className = 'msg';
  }
}

function resetQrForm() {
  resetQrFormFields();
  showQrListView();
}

function startCreateQr() {
  const tabBtn = document.querySelector('.nav-item[data-tab="quick-replies"]');
  const tab = document.getElementById('tab-quick-replies');
  if (tab && !tab.classList.contains('active')) {
    document.querySelectorAll('.nav-item').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    tabBtn?.classList.add('active');
    tab.classList.add('active');
  }
  resetQrFormFields();
  showQrEditorView();
  setTimeout(() => {
    try { document.getElementById('qr-title')?.focus(); } catch (_) {}
  }, 60);
  tg?.HapticFeedback?.impactOccurred?.('light');
}

function startEditQr(r) {
  if (!r) return;
  _qrEditId = r.id;
  const editId = document.getElementById('qr-edit-id');
  if (editId) editId.value = r.id;
  const formTitle = document.getElementById('qr-form-title');
  if (formTitle) formTitle.textContent = '✏️ 编辑话术模板';
  const submit = document.getElementById('qr-submit');
  if (submit) submit.textContent = '💾 保存修改';
  const title = document.getElementById('qr-title');
  const content = document.getElementById('qr-content');
  if (title) title.value = r.title || '';
  if (content) content.value = r.content || '';
  const msg = document.getElementById('qr-msg');
  if (msg) {
    msg.textContent = '';
    msg.className = 'msg';
  }
  showQrEditorView();
  setTimeout(() => {
    try { document.getElementById('qr-title')?.focus(); } catch (_) {}
  }, 60);
}

function renderQuickReplies() {
  const list = document.getElementById('qr-list');
  if (!list) return;
  const rows = _quickRepliesCache;
  if (!rows.length) {
    list.innerHTML = '<p class="empty-state">暂无快捷回复模板。点上方「＋ 新增话术」添加。</p>';
    return;
  }
  list.innerHTML = '';
  const count = document.createElement('div');
  count.className = 'list-count';
  count.textContent = `共 ${rows.length} 条话术`;
  list.appendChild(count);
  rows.forEach(r => {
    const div = document.createElement('div');
    div.className = 'ban-item';
    div.innerHTML = `
      <div class="ban-info">
        <div class="ban-name">⚡ ${esc(r.title)}</div>
        <div>${esc(summarizeText(r.content, 80))}</div>
      </div>
      <div class="fl-actions">
        <button type="button" class="btn-icon edit qr-edit" title="编辑">✏️</button>
        <button type="button" class="btn-ghost btn-sm qr-del" title="删除">🗑</button>
      </div>`;
    div.querySelector('.qr-edit')?.addEventListener('click', () => startEditQr(r));
    div.querySelector('.qr-del')?.addEventListener('click', async () => {
      if (!window.confirm('删除该模板？')) return;
      const res = await api('DELETE', '/quick_replies/' + r.id);
      if (res && res.error) {
        window.alert('删除失败：' + res.error);
        return;
      }
      if (_qrEditId === r.id) resetQrForm();
      loadQuickReplies();
    });
    list.appendChild(div);
  });
}

async function loadQuickReplies({ keepEditor = false } = {}) {
  const list = document.getElementById('qr-list');
  if (!list) return;
  const tab = document.getElementById('tab-quick-replies');
  const editing = !!(tab && tab.classList.contains('is-editing'));
  if (!(keepEditor && editing)) {
    showQrListView();
  }
  list.innerHTML = '<p class="empty-state">加载中…</p>';
  const data = await api('GET', '/quick_replies');
  const stillEditing = !!(tab && tab.classList.contains('is-editing'));
  if (data.error) {
    if (!stillEditing) {
      list.innerHTML = `<p class="msg fail">加载失败：${esc(data.error)}</p>`;
    }
    return;
  }
  _quickRepliesCache = Array.isArray(data) ? data : [];
  if (stillEditing) return;
  renderQuickReplies();
}

async function submitQrForm() {
  const msgEl = document.getElementById('qr-msg');
  const btn = document.getElementById('qr-submit');
  if (!msgEl || !btn) return;
  const title = document.getElementById('qr-title')?.value.trim() || '';
  const content = document.getElementById('qr-content')?.value.trim() || '';
  if (!title || !content) {
    msgEl.className = 'msg fail';
    msgEl.textContent = '❌ 标题与内容不能为空';
    return;
  }
  btn.disabled = true;
  msgEl.className = 'msg';
  msgEl.textContent = _qrEditId != null ? '保存中…' : '添加中…';
  try {
    let res;
    if (_qrEditId != null) {
      res = await api('PUT', '/quick_replies/' + _qrEditId, { title, content });
    } else {
      res = await api('POST', '/quick_replies', { title, content });
    }
    if ((res && res.ok) || (res && res.id != null && res.error == null)) {
      msgEl.className = 'msg ok';
      msgEl.textContent = _qrEditId != null ? '✅ 已保存修改' : '✅ 已添加';
      tg?.HapticFeedback?.notificationOccurred('success');
      resetQrForm();
      await loadQuickReplies();
    } else {
      msgEl.className = 'msg fail';
      msgEl.textContent = '❌ ' + ((res && res.error) || '失败');
    }
  } finally {
    btn.disabled = false;
  }
}

function bindQrUi() {
  document.getElementById('qr-start-create')?.addEventListener('click', (e) => {
    e.preventDefault();
    e.stopPropagation();
    startCreateQr();
  });
  document.getElementById('qr-submit')?.addEventListener('click', (e) => {
    e.preventDefault();
    submitQrForm();
  });
  document.getElementById('qr-cancel')?.addEventListener('click', (e) => {
    e.preventDefault();
    resetQrForm();
  });
  document.getElementById('qr-back')?.addEventListener('click', (e) => {
    e.preventDefault();
    resetQrForm();
  });
}

// ── Staff + audit ─────────────────────────────────────────────────────────────

function showStaffListView() {
  show('staff-hero');
  show('staff-list-card');
  show('staff-audit-card');
  hide('staff-editor-card');
  const tab = document.getElementById('tab-staff');
  if (tab) tab.classList.remove('is-editing');
}

function showStaffEditorView() {
  show('staff-hero');
  hide('staff-list-card');
  hide('staff-audit-card');
  revealPanel('staff-editor-card');
  const tab = document.getElementById('tab-staff');
  if (tab) tab.classList.add('is-editing');
}

function resetStaffFormFields() {
  const uid = document.getElementById('staff-uid');
  const role = document.getElementById('staff-role');
  const msg = document.getElementById('staff-msg');
  const formTitle = document.querySelector('#staff-editor-card .card-title');
  const addBtn = document.getElementById('staff-add');
  if (uid) {
    uid.value = '';
    uid.disabled = false;
  }
  if (role) role.value = 'support';
  if (formTitle) formTitle.textContent = '➕ 添加协作成员';
  if (addBtn) addBtn.textContent = '＋ 添加成员';
  if (msg) {
    msg.textContent = '';
    msg.className = 'msg';
  }
}

function resetStaffForm() {
  resetStaffFormFields();
  showStaffListView();
}

function startCreateStaff() {
  const tabBtn = document.querySelector('.nav-item[data-tab="staff"]');
  const tab = document.getElementById('tab-staff');
  if (tab && !tab.classList.contains('active')) {
    document.querySelectorAll('.nav-item').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    tabBtn?.classList.add('active');
    tab.classList.add('active');
  }
  resetStaffFormFields();
  const formTitle = document.querySelector('#staff-editor-card .card-title');
  if (formTitle) formTitle.textContent = '➕ 添加协作成员';
  const addBtn = document.getElementById('staff-add');
  if (addBtn) addBtn.textContent = '＋ 添加成员';
  const uid = document.getElementById('staff-uid');
  if (uid) uid.disabled = false;
  showStaffEditorView();
  setTimeout(() => {
    try { document.getElementById('staff-uid')?.focus(); } catch (_) {}
  }, 60);
  tg?.HapticFeedback?.impactOccurred?.('light');
}

function startEditStaff(s) {
  if (!s || s.is_owner) return;
  const tabBtn = document.querySelector('.nav-item[data-tab="staff"]');
  const tab = document.getElementById('tab-staff');
  if (tab && !tab.classList.contains('active')) {
    document.querySelectorAll('.nav-item').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    tabBtn?.classList.add('active');
    tab.classList.add('active');
  }
  resetStaffFormFields();
  const formTitle = document.querySelector('#staff-editor-card .card-title');
  if (formTitle) formTitle.textContent = '✏️ 修改成员角色';
  const addBtn = document.getElementById('staff-add');
  if (addBtn) addBtn.textContent = '💾 保存角色';
  const uid = document.getElementById('staff-uid');
  if (uid) {
    uid.value = s.user_id;
    uid.disabled = true;
  }
  const role = document.getElementById('staff-role');
  if (role) role.value = (s.role === 'admin' || s.role === 'support') ? s.role : 'support';
  showStaffEditorView();
  setTimeout(() => {
    try { document.getElementById('staff-role')?.focus(); } catch (_) {}
  }, 60);
}

async function loadStaff({ keepEditor = false } = {}) {
  const list = document.getElementById('staff-list');
  if (!list) return;
  const tab = document.getElementById('tab-staff');
  const editing = !!(tab && tab.classList.contains('is-editing'));
  if (!(keepEditor && editing)) {
    showStaffListView();
  }
  list.innerHTML = '<p class="empty-state">加载中…</p>';
  const data = await api('GET', '/staff');
  const stillEditing = !!(tab && tab.classList.contains('is-editing'));
  if (stillEditing) return; // keep the open add-member panel visible
  if (data.error) {
    list.innerHTML = `<p class="msg fail">加载失败：${esc(data.error)}</p>`;
    return;
  }
  const items = data.items || [];
  if (!items.length) {
    list.innerHTML = '<p class="empty-state">暂无协作成员。点上方「＋ 添加成员」邀请管理员或客服。</p>';
    return;
  }
  list.innerHTML = '';
  const count = document.createElement('div');
  count.className = 'list-count';
  count.textContent = `共 ${items.length} 位成员`;
  list.appendChild(count);
  items.forEach(s => {
    const div = document.createElement('div');
    div.className = 'ban-item';
    const label = s.full_name || s.username || String(s.user_id);
    const roleLabel = s.is_owner ? 'owner' : (s.role || 'support');
    div.innerHTML = `
      <div class="ban-info">
        <div class="ban-name">${esc(label)} · <code>${esc(roleLabel)}</code></div>
        <small>ID: ${esc(String(s.user_id))}${s.is_owner ? ' · 拥有者' : ''}</small>
      </div>
      ${s.is_owner ? '' : `<div class="fl-actions">
        <button type="button" class="btn-icon edit staff-edit" title="改角色">✏️</button>
        <button type="button" class="btn-ghost btn-sm staff-del" title="移除">移除</button>
      </div>`}`;
    const editBtn = div.querySelector('.staff-edit');
    if (editBtn) {
      editBtn.addEventListener('click', () => startEditStaff(s));
    }
    const btn = div.querySelector('.staff-del');
    if (btn) {
      btn.addEventListener('click', async () => {
        if (!window.confirm('移除该成员？')) return;
        const res = await api('DELETE', '/staff/' + s.user_id);
        if (res.error) alert(res.error);
        loadStaff();
      });
    }
    list.appendChild(div);
  });
}

async function submitStaffForm() {
  const msgEl = document.getElementById('staff-msg');
  if (!msgEl) return;
  const uidEl = document.getElementById('staff-uid');
  const uid = parseInt(uidEl?.value, 10);
  const role = document.getElementById('staff-role')?.value || 'support';
  const editing = !!(uidEl && uidEl.disabled);
  if (Number.isNaN(uid) || uid <= 0) {
    msgEl.className = 'msg fail';
    msgEl.textContent = '❌ 请输入有效用户 ID';
    try { uidEl?.focus(); } catch (_) {}
    return;
  }
  msgEl.className = 'msg';
  msgEl.textContent = '保存中…';
  const res = await api('POST', '/staff', { user_id: uid, role });
  if (res && res.ok && res.error == null) {
    msgEl.className = 'msg ok';
    msgEl.textContent = editing ? '✅ 角色已更新' : '✅ 已添加';
    tg?.HapticFeedback?.notificationOccurred('success');
    if (uidEl) uidEl.disabled = false;
    resetStaffFormFields();
    await loadStaff();
  } else {
    msgEl.className = 'msg fail';
    msgEl.textContent = '❌ ' + ((res && res.error) || '失败（需 owner 权限）');
  }
}

function bindStaffUi() {
  document.getElementById('staff-start-create')?.addEventListener('click', (e) => {
    e.preventDefault();
    e.stopPropagation();
    startCreateStaff();
  });
  document.getElementById('staff-add')?.addEventListener('click', (e) => {
    e.preventDefault();
    submitStaffForm();
  });
  document.getElementById('staff-cancel')?.addEventListener('click', (e) => {
    e.preventDefault();
    resetStaffForm();
  });
  document.getElementById('staff-back')?.addEventListener('click', (e) => {
    e.preventDefault();
    resetStaffForm();
  });
}

async function loadAuditLogs() {
  const list = document.getElementById('audit-list');
  list.innerHTML = '<p class="empty-state">加载中…</p>';
  const data = await api('GET', '/audit_logs?limit=30');
  if (data.error) {
    list.innerHTML = `<p class="msg fail">${esc(data.error)}</p>`;
    return;
  }
  const items = data.items || [];
  if (!items.length) {
    list.innerHTML = '<p class="empty-state">暂无审计记录。</p>';
    return;
  }
  list.innerHTML = items.map(r => `
    <div class="ban-item"><div class="ban-info">
      <div class="ban-name">${esc(r.action)}</div>
      <small>操作者 ${esc(String(r.actor_id || '—'))} · ${esc(formatDateTime(r.created_at))}</small>
      <div>${esc(r.detail || '')}</div>
    </div></div>`).join('');
}

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

/**
 * Global click delegation for critical "open add UI" actions.
 * Survives partial binding failures and works even if a direct listener was missed.
 * Capture phase so it still fires if a bubbling handler throws.
 */
function bindGlobalActions() {
  if (bindGlobalActions._bound) return;
  bindGlobalActions._bound = true;
  const handler = (e) => {
    const target = e.target;
    if (!(target instanceof Element)) return;
    const actionEl = target.closest('[data-action]');
    if (!actionEl) return;
    const action = actionEl.getAttribute('data-action');
    if (!action) return;
    if (action === 'fl-start-create') {
      e.preventDefault();
      e.stopPropagation();
      try { startCreateFl(); } catch (err) { console.warn('startCreateFl', err); }
      return;
    }
    if (action === 'staff-start-create') {
      e.preventDefault();
      e.stopPropagation();
      try { startCreateStaff(); } catch (err) { console.warn('startCreateStaff', err); }
      return;
    }
    if (action === 'qr-start-create') {
      e.preventDefault();
      e.stopPropagation();
      try { startCreateQr(); } catch (err) { console.warn('startCreateQr', err); }
    }
  };
  document.addEventListener('click', handler, true);
}

function bootApp() {
  if (bootApp._booted) return;
  bootApp._booted = true;

  try { tg?.ready(); } catch (_) {}
  try { tg?.expand(); } catch (_) {}

  // Theme + sidebar first so chrome works even if a builder fails
  try { initTheme(); } catch (err) { console.warn('initTheme', err); }
  try { initSidebar(); } catch (err) { console.warn('initSidebar', err); }
  try { initTabs(); } catch (err) { console.warn('initTabs', err); }
  // Critical add-panel actions first (capture + direct)
  try { bindGlobalActions(); } catch (err) { console.warn('bindGlobalActions', err); }
  try { bindFilterUi(); } catch (err) { console.warn('bindFilterUi', err); }
  try { bindStaffUi(); } catch (err) { console.warn('bindStaffUi', err); }
  try { bindQrUi(); } catch (err) { console.warn('bindQrUi', err); }

  try {
    _welcomeBuilder = initButtonBuilder(
      document.getElementById('welcome-buttons-builder'),
      'welcome-buttons-add-row'
    );
  } catch (err) {
    console.warn('welcome builder', err);
    _welcomeBuilder = { getText: () => '', loadText: () => {} };
  }
  try {
    _arBuilder = initButtonBuilder(
      document.getElementById('ar-buttons-builder'),
      'ar-buttons-add-row'
    );
  } catch (err) {
    console.warn('ar builder', err);
    _arBuilder = { getText: () => '', loadText: () => {} };
  }
  try {
    _bcBuilder = initButtonBuilder(
      document.getElementById('bc-buttons-builder'),
      'bc-buttons-add-row'
    );
  } catch (err) {
    console.warn('bc builder', err);
    _bcBuilder = { getText: () => '', loadText: () => {} };
  }
  try {
    _smBuilder = initButtonBuilder(
      document.getElementById('sm-buttons-builder'),
      'sm-buttons-add-row'
    );
  } catch (err) {
    console.warn('sm builder', err);
    _smBuilder = { getText: () => '', loadText: () => {} };
  }

  try { loadSettings(); } catch (err) { console.warn('loadSettings', err); }
}

// Always schedule boot even if earlier top-level listeners threw.
// Those listeners run as the parser evaluates the file; a throw above this
// line would skip boot — keep this block minimal and last.
try {
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', bootApp);
  } else {
    bootApp();
  }
} catch (err) {
  console.warn('bootApp schedule failed', err);
  try { setTimeout(bootApp, 0); } catch (_) {}
}
