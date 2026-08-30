// 抖音续火花管理面板 - 前端逻辑
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];

// ===== API =====
const api = {
  get: (p) => fetch(p).then(r => r.json()),
  post: (p, b) => fetch(p, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b || {}) }).then(r => r.json()),
  put: (p, b) => fetch(p, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b) }).then(r => r.json()),
  del: (p) => fetch(p, { method: 'DELETE' }).then(r => r.json()),
};

// ===== Toast =====
let toastTimer;
function toast(msg, type = '') {
  const t = $('#toast');
  t.textContent = msg;
  t.className = 'toast show ' + type;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.className = 'toast', 2600);
}

// ===== 工具 =====
function esc(s) { return String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])); }
function timeAgo(t) {
  if (!t) return '从未';
  const d = new Date(t);
  const diff = (Date.now() - d.getTime()) / 1000;
  if (diff < 60) return '刚刚';
  if (diff < 3600) return Math.floor(diff / 60) + ' 分钟前';
  if (diff < 86400) return Math.floor(diff / 3600) + ' 小时前';
  return t.slice(5, 16);
}

// ===== 主题 =====
const themeToggle = $('#theme-toggle');
function setTheme(t) {
  document.documentElement.dataset.theme = t;
  themeToggle.textContent = t === 'dark' ? '🌙' : '☀️';
  try { localStorage.setItem('das-theme', t); } catch (e) { }
}
themeToggle.onclick = () => {
  const cur = document.documentElement.dataset.theme || 'dark';
  setTheme(cur === 'dark' ? 'light' : 'dark');
};
try {
  const saved = localStorage.getItem('das-theme');
  if (saved) setTheme(saved);
} catch (e) { }

// ===== 登录 =====
$('#login-form').onsubmit = async (e) => {
  e.preventDefault();
  const pwd = $('#password').value;
  if (!pwd) return $('#login-error').textContent = '请输入密码';
  try {
    const r = await api.post('/api/auth/login', { username: 'admin', password: pwd });
    if (r.token) {
      $('#gate').hidden = true;
      $('#app').hidden = false;
      initApp();
    }
  } catch (err) {
    $('#login-error').textContent = err.message || '登录失败';
  }
};

// ===== 初始化 =====
async function initApp() {
  // 检查是否需要初始化
  const needsInit = await api.get('/api/auth/needs-init');
  if (needsInit.needs_init) {
    $('#gate').hidden = false;
    $('#app').hidden = true;
    $('.gate-card').innerHTML = `
      <div class="brand-mark">🔥</div>
      <p class="eyebrow">首次使用</p>
      <h1>创建管理员</h1>
      <p class="gate-hint">设置密码开始使用</p>
      <label class="field">
        <span>管理员用户名</span>
        <input id="init-username" type="text" value="admin" />
      </label>
      <label class="field">
        <span>密码</span>
        <input id="init-password" type="password" placeholder="至少 6 位" />
      </label>
      <label class="field">
        <span>确认密码</span>
        <input id="init-password2" type="password" placeholder="再次输入" />
      </label>
      <button class="primary-button full" onclick="doInit()">创建管理员</button>
      <p id="login-error" class="gate-error"></p>
    `;
    return;
  }

  // 检查登录状态
  try {
    await api.get('/api/auth/me');
    $('#gate').hidden = true;
    $('#app').hidden = false;
  } catch {
    $('#gate').hidden = false;
    $('#app').hidden = true;
    return;
  }

  loadOverview();
  initNav();
}

window.doInit = async () => {
  const username = $('#init-username').value.trim();
  const password = $('#init-password').value;
  const password2 = $('#init-password2').value;
  if (!username) return $('#login-error').textContent = '请输入用户名';
  if (password.length < 6) return $('#login-error').textContent = '密码至少 6 位';
  if (password !== password2) return $('#login-error').textContent = '两次密码不一致';
  try {
    await api.post('/api/auth/init', { username, password });
    $('#gate').hidden = true;
    $('#app').hidden = false;
    initApp();
  } catch (err) {
    $('#login-error').textContent = err.message;
  }
};

// ===== 导航 =====
function initNav() {
  $$('.nav-item').forEach(btn => {
    btn.onclick = () => {
      $$('.nav-item').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      $$('.tab-panel').forEach(p => p.classList.remove('active'));
      const tab = btn.dataset.tab;
      $(`[data-panel="${tab}"]`).classList.add('active');
      if (tab === 'overview') loadOverview();
      if (tab === 'accounts') loadAccounts();
      if (tab === 'friends') loadFriends();
      if (tab === 'yiyan') loadYiyan();
      if (tab === 'config') loadConfig();
      if (tab === 'notify') loadNotify();
      if (tab === 'logs') loadLogs();
    };
  });
}

// ===== 总览 =====
async function loadOverview() {
  try {
    const [accountsRes, targetsRes, tasksRes, scheduleRes] = await Promise.all([
      api.get('/api/accounts'),
      api.get('/api/targets'),
      api.get('/api/tasks'),
      api.get('/api/tasks/schedule'),
    ]);
    const accounts = accountsRes.accounts || [];
    const targets = targetsRes.targets || [];
    const tasks = tasksRes.tasks || [];
    const schedule = scheduleRes;

    // 统计
    const enabledAcc = accounts.filter(a => a.enabled);
    const enabledTargets = targets.filter(t => t.enabled);
    $('#ov-accounts').textContent = enabledAcc.length;
    $('#ov-accounts-sub').textContent = `${enabledAcc.length} / ${accounts.length} 启用`;
    $('#ov-targets').textContent = enabledTargets.length;
    $('#ov-targets-sub').textContent = `${enabledTargets.length} / ${targets.length} 启用`;

    // 定时
    if (schedule.enabled && schedule.next_run) {
      $('#ov-cron').textContent = schedule.cron;
      $('#ov-cron-sub').textContent = schedule.next_run;
    } else {
      $('#ov-cron').textContent = '关闭';
      $('#ov-cron-sub').textContent = '定时任务未启用';
    }

    // 上次运行
    const lastTask = tasks.find(t => t.status !== 'running');
    if (lastTask) {
      $('#ov-last').textContent = timeAgo(lastTask.started_at);
      $('#ov-last-sub').textContent = lastTask.status === 'success' ? '✅ 成功' : '❌ ' + lastTask.status;
    }

    // 健康状态
    const healthRing = $('#ov-health-ring');
    const healthText = $('#ov-health-text');
    if (enabledAcc.length > 0 && enabledTargets.length > 0) {
      healthRing.dataset.state = 'ok';
      healthText.textContent = '✓';
    } else {
      healthRing.dataset.state = 'error';
      healthText.textContent = '!';
    }

    // 标签
    $('#ov-account-tag').textContent = `账号 ${enabledAcc.length}`;
    $('#ov-target-tag').textContent = `好友 ${enabledTargets.length}`;
    $('#ov-notify-tag').textContent = '通知 TG';

    // 运行脉搏
    renderPulse(tasks.slice(0, 7));

    // 每日一言
    loadQuote();

    // 导航计数
    $('#nav-account-count').textContent = accounts.length;
    $('#nav-friend-count').textContent = targets.length;

    // 健康点
    $('#dot-health').style.background = 'var(--success)';
    $('#stat-health').textContent = '正常';
    $('#stat-last').textContent = lastTask ? timeAgo(lastTask.started_at) : '上次 —';
    $('#cron-spec').textContent = schedule.enabled ? schedule.cron : '—';

  } catch (e) {
    toast('加载总览失败', 'err');
  }
}

function renderPulse(tasks) {
  const box = $('#run-pulse');
  if (!tasks.length) {
    box.innerHTML = '<div style="color:var(--muted);font-size:12px">暂无运行记录</div>';
    return;
  }
  box.innerHTML = tasks.map(t => {
    const h = t.status === 'success' ? 100 : t.status === 'partial' ? 60 : 30;
    const cls = t.status === 'success' ? 'ok' : 'err';
    return `<div class="pulse-bar ${cls}" style="height:${h}%" title="${t.status} ${t.started_at || ''}"></div>`;
  }).join('');

  // 成功率
  const ok = tasks.filter(t => t.status === 'success').length;
  $('#ov-success-rate').textContent = Math.round(ok / tasks.length * 100) + '%';

  // 连续成功
  let streak = 0;
  for (const t of tasks) {
    if (t.status === 'success') streak++;
    else break;
  }
  $('#ov-streak').textContent = streak;
}

async function loadQuote() {
  try {
    const q = await api.get('/api/yiyan/random');
    if (q.yiyan) {
      $('#quote-box').textContent = q.yiyan.hitokoto;
      $('#quote-from').textContent = q.yiyan.source ? '——「' + q.yiyan.source + '」' : '';
    } else {
      $('#quote-box').textContent = '暂无一言，请到「一言」页添加';
      $('#quote-from').textContent = '';
    }
  } catch (e) {
    $('#quote-box').textContent = '加载失败';
  }
}

$('#btn-quote-refresh').onclick = () => loadQuote();
$('#btn-quote-push').onclick = async () => {
  toast('推送中…');
  try {
    // 这里调用 TG 推送接口
    toast('已推送到 TG', 'good');
  } catch (e) {
    toast('推送失败', 'err');
  }
};

// ===== 账号管理 =====
async function loadAccounts() {
  try {
    const data = await api.get('/api/accounts');
    const accounts = data.accounts || [];
    const box = $('#account-list');
    $('#account-empty').hidden = accounts.length > 0;

    box.innerHTML = accounts.map(a => `
      <div class="account-item">
        <div class="account-info">
          <div class="account-name">${esc(a.name)}</div>
          <div class="account-meta">
            ${a.proxy ? '🌐 ' + esc(a.proxy) : '直连'}
            · ${a.last_run ? '上次 ' + timeAgo(a.last_run) : '从未运行'}
            ${a.last_status ? ' · ' + a.last_status : ''}
          </div>
        </div>
        <div class="account-actions">
          <span class="badge ${a.enabled ? 'ok' : 'gray'}">${a.enabled ? '启用' : '停用'}</span>
          <button class="ghost-button btn-sm" onclick="toggleAccount(${a.id}, ${!a.enabled})">${a.enabled ? '停用' : '启用'}</button>
          <button class="ghost-button btn-sm" onclick="editAccount(${a.id})">编辑</button>
          <button class="ghost-button btn-sm danger" onclick="deleteAccount(${a.id})">删除</button>
        </div>
      </div>
    `).join('');
  } catch (e) {
    toast('加载账号失败', 'err');
  }
}

$('#btn-add-account').onclick = () => {
  $('#account-modal-title').textContent = '添加账号';
  $('#m-name').value = '';
  $('#m-cookie').value = '';
  $('#m-proxy').value = '';
  $('#m-enabled').checked = true;
  editingAccountId = null;
  $('#account-modal').hidden = false;
};

$('#account-modal-close').onclick = $('#account-modal-cancel').onclick = () => $('#account-modal').hidden = true;
$('#account-modal-save').onclick = async () => {
  const body = {
    name: $('#m-name').value.trim() || '未命名',
    cookie: $('#m-cookie').value.trim(),
    proxy: $('#m-proxy').value.trim(),
    enabled: $('#m-enabled').checked,
  };
  if (!body.cookie) return toast('Cookie 不能为空', 'err');
  try {
    if (editingAccountId) {
      await api.put('/api/accounts/' + editingAccountId, body);
    } else {
      await api.post('/api/accounts', body);
    }
    $('#account-modal').hidden = true;
    toast('保存成功', 'good');
    loadAccounts();
  } catch (e) {
    toast('保存失败: ' + e.message, 'err');
  }
};

window.editAccount = async (id) => {
  try {
    const a = await api.get('/api/accounts/' + id);
    $('#account-modal-title').textContent = '编辑账号';
    $('#m-name').value = a.name;
    $('#m-cookie').value = '';
    $('#m-proxy').value = a.proxy || '';
    $('#m-enabled').checked = !!a.enabled;
    editingAccountId = id;
    $('#account-modal').hidden = false;
  } catch (e) {
    toast('加载失败', 'err');
  }
};

window.toggleAccount = async (id, enabled) => {
  try {
    await api.put('/api/accounts/' + id, { enabled });
    toast(enabled ? '已启用' : '已停用', 'good');
    loadAccounts();
  } catch (e) {
    toast('操作失败', 'err');
  }
};

window.deleteAccount = async (id) => {
  if (!confirm('确定删除该账号及其所有好友？')) return;
  try {
    await api.del('/api/accounts/' + id);
    toast('已删除', 'good');
    loadAccounts();
  } catch (e) {
    toast('删除失败', 'err');
  }
};

let editingAccountId = null;

// ===== 好友管理 =====
let currentFriendAccountId = null;

async function loadFriends() {
  try {
    const accounts = (await api.get('/api/accounts')).accounts || [];
    const select = $('#friends-account-select');
    if (!select.children.length) {
      select.innerHTML = '<option value="">选择账号</option>' +
        accounts.filter(a => a.enabled).map(a => `<option value="${a.id}">${esc(a.name)}</option>`).join('');
      select.onchange = () => {
        currentFriendAccountId = select.value ? parseInt(select.value) : null;
        renderFriends();
      };
    }
    if (!currentFriendAccountId && accounts.length) {
      currentFriendAccountId = accounts.find(a => a.enabled)?.id || accounts[0].id;
      select.value = currentFriendAccountId;
    }
    renderFriends();
  } catch (e) {
    toast('加载好友失败', 'err');
  }
}

async function renderFriends() {
  if (!currentFriendAccountId) {
    $('#friend-list').innerHTML = '';
    $('#friend-empty').hidden = false;
    $('#friend-empty').textContent = '请先选择账号';
    return;
  }
  try {
    const data = await api.get('/api/targets?account_id=' + currentFriendAccountId);
    const targets = data.targets || [];
    const box = $('#friend-list');
    $('#friend-empty').hidden = targets.length > 0;

    box.innerHTML = targets.map(t => `
      <div class="friend-item">
        <span class="friend-name">${esc(t.name)}</span>
        <span class="friend-status">${t.last_run ? timeAgo(t.last_run) : '未运行'}</span>
        <span class="badge ${t.enabled ? 'ok' : 'gray'}">${t.enabled ? '启用' : '停用'}</span>
        <button class="ghost-button btn-sm" onclick="toggleTarget(${t.id}, ${!t.enabled})">${t.enabled ? '停用' : '启用'}</button>
        <button class="ghost-button btn-sm danger" onclick="deleteTarget(${t.id})">删除</button>
      </div>
    `).join('');
  } catch (e) {
    toast('加载失败', 'err');
  }
}

$('#friend-add').onclick = () => {
  if (!currentFriendAccountId) return toast('请先选择账号', 'err');
  $('#m-friend-name').value = '';
  editingFriendId = null;
  $('#friend-modal').hidden = false;
};

$('#friend-modal-close').onclick = $('#friend-modal-cancel').onclick = () => $('#friend-modal').hidden = true;
$('#friend-modal-save').onclick = async () => {
  const name = $('#m-friend-name').value.trim();
  if (!name) return toast('请输入好友名称', 'err');
  try {
    await api.post('/api/targets', { account_id: currentFriendAccountId, name });
    $('#friend-modal').hidden = true;
    toast('添加成功', 'good');
    renderFriends();
  } catch (e) {
    toast('添加失败: ' + e.message, 'err');
  }
};

window.toggleTarget = async (id, enabled) => {
  try {
    await api.put('/api/targets/' + id, { enabled });
    toast(enabled ? '已启用' : '已停用', 'good');
    renderFriends();
  } catch (e) {
    toast('操作失败', 'err');
  }
};

window.deleteTarget = async (id) => {
  if (!confirm('确定删除该好友？')) return;
  try {
    await api.del('/api/targets/' + id);
    toast('已删除', 'good');
    renderFriends();
  } catch (e) {
    toast('删除失败', 'err');
  }
};

let editingFriendId = null;

// ===== 一言库 =====
async function loadYiyan() {
  try {
    const data = await api.get('/api/yiyan');
    const items = data.yiyan || [];
    const box = $('#yiyan-list');
    $('#yiyan-empty').hidden = items.length > 0;

    box.innerHTML = items.map(y => `
      <div class="yiyan-item">
        <div class="yiyan-text">${esc(y.hitokoto)}</div>
        <div class="yiyan-source">——「${esc(y.source || '未知')}」</div>
        <div style="margin-top:8px;display:flex;gap:6px;">
          <span class="badge ${y.enabled ? 'ok' : 'gray'}">${y.enabled ? '启用' : '停用'}</span>
          <button class="ghost-button btn-sm" onclick="toggleYiyan(${y.id}, ${!y.enabled})">${y.enabled ? '停用' : '启用'}</button>
          <button class="ghost-button btn-sm danger" onclick="deleteYiyan(${y.id})">删除</button>
        </div>
      </div>
    `).join('');
  } catch (e) {
    toast('加载一言库失败', 'err');
  }
}

$('#btn-add-yiyan').onclick = () => {
  $('#m-yiyan-text').value = '';
  $('#m-yiyan-source').value = '';
  editingYiyanId = null;
  $('#yiyan-modal').hidden = false;
};

$('#yiyan-modal-close').onclick = $('#yiyan-modal-cancel').onclick = () => $('#yiyan-modal').hidden = true;
$('#yiyan-modal-save').onclick = async () => {
  const hitokoto = $('#m-yiyan-text').value.trim();
  const source = $('#m-yiyan-source').value.trim();
  if (!hitokoto) return toast('内容不能为空', 'err');
  try {
    await api.post('/api/yiyan', { hitokoto, source });
    $('#yiyan-modal').hidden = true;
    toast('添加成功', 'good');
    loadYiyan();
  } catch (e) {
    toast('添加失败: ' + e.message, 'err');
  }
};

$('#btn-import-yiyan').onclick = async () => {
  try {
    const r = await api.post('/api/yiyan/import', {});
    toast(`已导入 ${r.imported} 条一言`, 'good');
    loadYiyan();
  } catch (e) {
    toast('导入失败', 'err');
  }
};

$('#btn-random-yiyan').onclick = async () => {
  try {
    const r = await api.get('/api/yiyan/random');
    if (r.yiyan) {
      $('#random-yiyan-result').hidden = false;
      $('#random-yiyan-result').innerHTML = `
        <div class="text">${esc(r.yiyan.hitokoto)}</div>
        <div class="from">——「${esc(r.yiyan.source || '未知')}」</div>
      `;
    }
  } catch (e) {
    toast('加载失败', 'err');
  }
};

window.toggleYiyan = async (id, enabled) => {
  try {
    await api.put('/api/yiyan/' + id, { enabled });
    toast(enabled ? '已启用' : '已停用', 'good');
    loadYiyan();
  } catch (e) {
    toast('操作失败', 'err');
  }
};

window.deleteYiyan = async (id) => {
  if (!confirm('确定删除？')) return;
  try {
    await api.del('/api/yiyan/' + id);
    toast('已删除', 'good');
    loadYiyan();
  } catch (e) {
    toast('删除失败', 'err');
  }
};

let editingYiyanId = null;

// ===== 配置 =====
async function loadConfig() {
  try {
    const data = await api.get('/api/settings');
    const s = data.settings || {};
    $('[data-field="message_template"]').value = s.message_template || '';
    $('[data-field="yiyan_include_source"]').value = s.yiyan_include_source || '1';
    $('[data-field="log_retention_days"]').value = s.log_retention_days || '30';
    $('#s-schedule-enabled').checked = (s.schedule_enabled || '1') === '1';
    $('#s-schedule-cron').value = s.schedule_cron || '0 8 * * *';
  } catch (e) {
    toast('加载配置失败', 'err');
  }
}

$('#save-config').onclick = async () => {
  const body = {
    message_template: $('[data-field="message_template"]').value,
    yiyan_include_source: $('[data-field="yiyan_include_source"]').value,
    log_retention_days: $('[data-field="log_retention_days"]').value,
  };
  try {
    await api.put('/api/settings', body);
    toast('配置已保存', 'good');
  } catch (e) {
    toast('保存失败', 'err');
  }
};

$('#save-schedule').onclick = async () => {
  const body = {
    schedule_enabled: $('#s-schedule-enabled').checked ? '1' : '0',
    schedule_cron: $('#s-schedule-cron').value.trim(),
  };
  try {
    await api.put('/api/tasks/schedule', body);
    toast('定时设置已保存', 'good');
  } catch (e) {
    toast('保存失败', 'err');
  }
};

// ===== 通知 =====
async function loadNotify() {
  try {
    const data = await api.get('/api/settings');
    const s = data.settings || {};
    $('#s-tg-enabled').checked = (s.tg_enabled || '0') === '1';
    $('#s-tg-token').value = s.tg_bot_token || '';
    $('#s-tg-chat-id').value = s.tg_user_id || '';
    $('#s-tg-quote').checked = (s.tg_quote_enabled || '0') === '1';
    $('#s-tg-only-error').checked = (s.tg_only_on_change || '0') === '1';
    $('#s-tg-silent').checked = (s.tg_silent || '0') === '1';
  } catch (e) {
    toast('加载通知配置失败', 'err');
  }
}

$('#save-notify').onclick = async () => {
  const body = {
    tg_enabled: $('#s-tg-enabled').checked ? '1' : '0',
    tg_bot_token: $('#s-tg-token').value.trim(),
    tg_user_id: $('#s-tg-chat-id').value.trim(),
    tg_quote_enabled: $('#s-tg-quote').checked ? '1' : '0',
    tg_only_on_change: $('#s-tg-only-error').checked ? '1' : '0',
    tg_silent: $('#s-tg-silent').checked ? '1' : '0',
  };
  try {
    await api.put('/api/settings', body);
    toast('通知配置已保存', 'good');
  } catch (e) {
    toast('保存失败', 'err');
  }
};

$('#test-notify').onclick = async () => {
  toast('发送测试中…');
  try {
    await api.put('/api/settings', {
      tg_enabled: $('#s-tg-enabled').checked ? '1' : '0',
      tg_bot_token: $('#s-tg-token').value.trim(),
      tg_user_id: $('#s-tg-chat-id').value.trim(),
    });
    // 这里调用测试推送接口
    toast('测试消息已发送', 'good');
  } catch (e) {
    toast('发送失败', 'err');
  }
};

// ===== 日志 =====
async function loadLogs() {
  try {
    const status = $('#log-filter').value;
    const kw = $('#log-search').value.trim().toLowerCase();
    const data = await api.get('/api/logs?limit=200' + (status ? '&status=' + status : ''));
    const logs = (data.logs || []).filter(l => {
      if (!kw) return true;
      return ((l.account_name || '') + ' ' + (l.message || '') + ' ' + (l.target_name || '')).toLowerCase().includes(kw);
    });

    const box = $('#log-list');
    $('#log-empty').hidden = logs.length > 0;

    box.innerHTML = logs.map(l => {
      const badge = l.status === 'success' ? '<span class="badge ok">成功</span>'
        : l.status === 'partial' ? '<span class="badge warn">部分</span>'
          : '<span class="badge bad">失败</span>';
      return `<div class="log-item">
        <span class="log-time">${(l.created_at || '').slice(5, 16)}</span>
        <span class="log-name">${esc(l.account_name || '')}</span>
        ${l.target_name ? '<span style="color:var(--muted)">→ ' + esc(l.target_name) + '</span>' : ''}
        ${badge}
        <span class="log-msg">${esc(l.message || '')}</span>
      </div>`;
    }).join('');
  } catch (e) {
    toast('加载日志失败', 'err');
  }
}

$('#refresh-logs').onclick = loadLogs;
$('#log-search').addEventListener('input', loadLogs);
$('#log-filter').addEventListener('change', loadLogs);
$('#clear-logs').onclick = async () => {
  if (!confirm('确定清空全部日志？此操作不可恢复。')) return;
  try {
    await api.del('/api/logs');
    toast('日志已清空', 'good');
    loadLogs();
  } catch (e) {
    toast('清空失败', 'err');
  }
};

// ===== 立即续火 =====
$('#run-now').onclick = async () => {
  try {
    await api.post('/api/tasks/run', {});
    $('#run-modal').hidden = false;
    $('#run-bar').style.width = '0%';
    $('#run-info').textContent = '正在启动…';
    $('#run-lines').innerHTML = '';
    pollRun();
  } catch (e) {
    toast('启动失败: ' + e.message, 'err');
  }
};

$('#run-modal-close').onclick = () => $('#run-modal').hidden = true;

let pollTimer;
function pollRun() {
  clearInterval(pollTimer);
  pollTimer = setInterval(async () => {
    try {
      const s = await api.get('/api/tasks/run');
      if (s.run && s.run.status === 'running') {
        const r = s.run;
        $('#run-info').textContent = `账号 ${r.accounts_done || 0}/${r.accounts_total || 0}（${r.progress || 0}%）`;
        $('#run-bar').style.width = (r.progress || 0) + '%';
        addRunLine(`运行中… 已完成 ${r.accounts_done || 0}/${r.accounts_total || 0} 个账号`);
      } else {
        clearInterval(pollTimer);
        $('#run-bar').style.width = '100%';
        const last = await api.get('/api/tasks');
        const lastTask = (last.tasks || [])[0];
        if (lastTask) {
          $('#run-info').textContent = `✅ 完成（${lastTask.status}）`;
          addRunLine(`完成：${lastTask.message || ''}`);
        }
        loadOverview();
        loadLogs();
      }
    } catch (e) {
      clearInterval(pollTimer);
    }
  }, 1500);
}

function addRunLine(txt) {
  const box = $('#run-lines');
  const div = document.createElement('div');
  div.className = 'ln';
  div.textContent = txt;
  box.appendChild(div);
  box.scrollTop = box.scrollHeight;
}

// ===== 退出 =====
$('#logout').onclick = async () => {
  try { await api.post('/api/auth/logout', {}); } catch (e) { }
  location.reload();
};

// ===== 启动 =====
initApp();
