/* ===== 抖音续火花管理面板 - 前端逻辑 ===== */
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];

async function handleResp(r) {
  if (r.status === 401) {
    location.href = '/login.html';
    throw new Error('登录已失效');
  }
  if (!r.ok) {
    let message = `请求失败 (${r.status})`;
    try {
      const data = await r.json();
      message = data.detail || data.message || message;
    } catch (e) { }
    throw new Error(message);
  }
  if (r.status === 204) return {};
  try { return await r.json(); }
  catch (e) { return {}; }
}

const api = {
  get: (p) => fetch(p, { credentials: 'same-origin' }).then(handleResp),
  post: (p, b) => fetch(p, { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b || {}) }).then(handleResp),
  put: (p, b) => fetch(p, { method: 'PUT', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b || {}) }).then(handleResp),
  del: (p) => fetch(p, { method: 'DELETE', credentials: 'same-origin' }).then(handleResp),
};

function asArray(value, key) {
  if (Array.isArray(value)) return value;
  if (value && Array.isArray(value[key])) return value[key];
  return [];
}

function setLoading(el, text = '加载中…') {
  if (el) el.innerHTML = `<div class="empty-state loading-state">${esc(text)}</div>`;
}

function setError(el, message, retry) {
  if (!el) return;
  el.innerHTML = `<div class="empty-state error-state"><strong>加载失败</strong><span>${esc(message || '请稍后重试')}</span>${retry ? '<button class="btn btn-ghost btn-sm" type="button">重试</button>' : ''}</div>`;
  if (retry) el.querySelector('button').onclick = retry;
}

/* ===== Toast ===== */
let toastTimer;
function toast(msg, type = '') {
  const t = $('#toast');
  t.textContent = msg;
  t.className = 'toast show ' + type;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.className = 'toast', 2600);
}

/* ===== 工具 ===== */
function esc(s) { return String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])); }
function flagEmoji(code) {
  if (!code || code.length !== 2) return '🌐';
  const base = 0x1F1E6;
  const chars = [...code.toUpperCase()].map(c => String.fromCodePoint(base + c.charCodeAt(0) - 65));
  return chars.join('');
}
function timeAgo(t) {
  if (!t) return '从未';
  const d = new Date(t);
  const diff = (Date.now() - d.getTime()) / 1000;
  if (diff < 60) return '刚刚';
  if (diff < 3600) return Math.floor(diff / 60) + ' 分钟前';
  if (diff < 86400) return Math.floor(diff / 3600) + ' 小时前';
  return t.slice(5, 16);
}

/* ===== 主题 ===== */
const themeSel = $('#theme');
themeSel.value = document.documentElement.dataset.theme || 'system';
themeSel.onchange = () => {
  const t = themeSel.value;
  document.documentElement.dataset.theme = t;
  try { localStorage.setItem('das-theme', t); } catch (e) { }
};

/* ===== 导航 ===== */
const VIEW_TITLES = { dashboard: '仪表盘', accounts: '账号管理', proxies: '代理', friends: '好友管理', logs: '续火日志', settings: '设置' };
$$('.nav-item').forEach(btn => {
  btn.onclick = () => {
    $$('.nav-item').forEach(b => {
      b.classList.remove('active');
      b.removeAttribute('aria-current');
    });
    btn.classList.add('active');
    btn.setAttribute('aria-current', 'page');
    $$('.view').forEach(v => v.hidden = true);
    $('#view-' + btn.dataset.view).hidden = false;
    $('#view-title').textContent = VIEW_TITLES[btn.dataset.view];
    if (btn.dataset.view === 'dashboard') loadDashboard();
    if (btn.dataset.view === 'accounts') loadAccounts();
    if (btn.dataset.view === 'proxies') loadProxies();
    if (btn.dataset.view === 'friends') loadFriends();
    if (btn.dataset.view === 'logs') loadLogs();
    if (btn.dataset.view === 'settings') loadSettings();
  };
});

/* ===== 仪表盘 ===== */
async function loadDashboard() {
  try {
    const [statsRes, scheduleRes] = await Promise.all([
      api.get('/api/stats').catch(() => null),
      api.get('/api/tasks/schedule').catch(() => ({enabled: false})),
    ]);
    const stats = statsRes || {};
    const schedule = scheduleRes;

    const acc = stats.accounts || {total: 0, enabled: 0};
    const tgt = stats.targets || {total: 0, enabled: 0};
    const runs = stats.runs || {total: 0, success: 0, partial: 0, failed: 0, success_rate: '—'};
    const msgs = stats.messages || {total: 0, ok: 0, fail: 0};

    const todayStr = new Date().toISOString().slice(0, 10);
    const tasks = (await api.get('/api/tasks').catch(() => ({tasks: []}))).tasks || [];
    const todaySuccess = tasks.filter(t => t.status === 'success' && t.started_at && t.started_at.startsWith(todayStr)).length;
    const todayFail = tasks.filter(t => (t.status === 'failed' || t.status === 'partial') && t.started_at && t.started_at.startsWith(todayStr)).length;

    $('#statGrid').innerHTML = [
      card('账号', `${acc.enabled}/${acc.total}`, 'acc', '个'),
      card('续火好友', `${tgt.enabled}/${tgt.total}`, '', '个'),
      card('总任务', runs.total, 'blue', '次'),
      card('成功率', runs.success_rate, 'green', ''),
      card('今日成功', todaySuccess, 'ok', '次'),
      card('今日失败', todayFail, todayFail > 0 ? 'bad' : '', '次'),
      card('总消息', msgs.total, 'purple', '条'),
      card('活跃账号', stats.active_accounts || 0, 'orange', '个'),
    ].join('');

    const strip = $('#schedStrip');
    if (schedule.enabled && schedule.next_run) {
      strip.hidden = false;
      $('#schedText').textContent = `下次定时续火：${schedule.next_run}（cron ${schedule.cron}）`;
    } else {
      strip.hidden = false;
      $('#schedText').textContent = '定时续火已关闭（可到设置里开启）';
    }

    // 账号列表
    const accountsRes = await api.get('/api/accounts').catch(() => ({accounts: []}));
    const accounts = accountsRes.accounts || [];

    loadTrend(tasks);
    loadQuote();
    renderRecentTasks(tasks.slice(0, 6));
    renderDashAccounts(accounts);
  } catch (e) {
    console.error('仪表盘加载失败:', e);
    toast('加载仪表盘失败: ' + e.message, 'err');
  }
}

function card(lbl, num, cls, suffix = '') {
  const clsMap = { ok: 'ok', bad: 'bad', green: 'ok', blue: 'blue', purple: 'purple', orange: 'orange', acc: 'acc' };
  const statCls = clsMap[cls] || '';
  return `<div class="stat ${statCls}"><div class="num">${esc(num)}<span style="font-size:14px">${esc(suffix)}</span></div><div class="lbl">${esc(lbl)}</div></div>`;
}

function renderRecentTasks(tasks) {
  const tb = $('#recentTasks tbody');
  tb.innerHTML = tasks.length ? tasks.map(t => `
    <tr>
      <td><code>${t.task_id}</code></td>
      <td>${t.trigger_type === 'schedule' ? '⏰ 定时' : '👆 手动'}</td>
      <td>${statusBadge(t.status)}</td>
      <td>${t.started_at || ''}</td>
      <td>${t.finished_at || '—'}</td>
    </tr>`).join('') : '<tr><td colspan="5" style="color:var(--muted)">暂无任务记录</td></tr>';
}

function renderDashAccounts(accounts) {
  const tb = $('#dashAccounts tbody');
  tb.innerHTML = accounts.length ? accounts.map(a => `
    <tr>
      <td>${esc(a.name)}</td>
      <td>${statusBadge(a.last_status)}</td>
      <td>${a.last_run || '从未'}</td>
      <td style="white-space:normal;color:var(--muted)">${a.last_message || ''}</td>
    </tr>`).join('') : '<tr><td colspan="4" style="color:var(--muted)">暂无账号</td></tr>';
}

function statusBadge(s) {
  const map = { success: ['ok', '✅'], partial: ['warn', '⚠️'], failed: ['bad', '❌'], running: ['acc', '🔄'], unknown: ['gray', '未知'] };
  const [cls, lab] = map[s] || map.unknown;
  return `<span class="badge ${cls}">${lab} ${s === 'success' ? '成功' : s === 'partial' ? '部分' : s === 'failed' ? '失败' : s === 'running' ? '运行中' : '未知'}</span>`;
}

function loadTrend(tasks) {
  const box = $('#trendChart');
  if (!box) return;
  try {
    const days = {};
    tasks.forEach(t => {
      if (!t.started_at) return;
      const day = t.started_at.slice(0, 10);
      if (!days[day]) days[day] = { success: 0, fail: 0 };
      if (t.status === 'success') days[day].success++;
      else if (t.status === 'failed' || t.status === 'partial') days[day].fail++;
    });
    const labels = Object.keys(days).sort().slice(-7);
    const max = Math.max(1, ...labels.map(d => days[d].success + days[d].fail));
    box.innerHTML = labels.map(d => {
      const totalH = Math.round((days[d].success + days[d].fail) / max * 100);
      const okH = (days[d].success + days[d].fail) ? Math.round(days[d].success / (days[d].success + days[d].fail) * totalH) : 0;
      const failH = Math.max(0, totalH - okH);
      return `<div class="trend-col" title="${d}：成功 ${days[d].success}，失败 ${days[d].fail}">
        <div class="trend-bars"><i class="tb-fail" style="height:${failH}%"></i><i class="tb-ok" style="height:${okH}%"></i></div>
        <span class="trend-lbl">${d.slice(5)}</span>
      </div>`;
    }).join('');
    const sum = labels.reduce((a, d) => a + days[d].success, 0);
    $('#trendHint').textContent = `近 ${labels.length} 天成功 ${sum} 次`;
  } catch (e) { box.innerHTML = '<div class="hint">趋势加载失败</div>'; }
}

/* ===== 每日一言（hitokoto.cn API） ===== */
async function loadQuote() {
  const box = $('#quoteBox');
  if (!box) return;
  try {
    const q = await api.get('/api/yiyan/random');
    box.textContent = q.yiyan ? q.yiyan.hitokoto : '暂无一言';
    $('#quoteFrom').textContent = q.yiyan && (q.yiyan.source || q.yiyan.from_who) ? '——「' + (q.yiyan.from_who || q.yiyan.source) + '」' : '';
  } catch (e) { box.textContent = '每日一言加载失败'; }
}

$('#btn-quote-refresh').onclick = () => loadQuote(true);
$('#btn-quote-push').onclick = async () => {
  toast('推送中…');
  try {
    await api.post('/api/yiyan/push', {});
    toast('已推送到 TG', 'good');
  } catch (e) { toast('推送失败', 'err'); }
};

/* ===== 账号管理 ===== */
let editingAccId = null;
async function loadAccounts() {
  const tb = $('#accTable tbody');
  if (tb) tb.innerHTML = '<tr><td colspan="7"><div class="empty-state loading-state">加载账号中…</div></td></tr>';
  try {
    const data = await api.get('/api/accounts');
    const accounts = asArray(data, 'accounts');
    window.__accounts = accounts;
    tb.innerHTML = accounts.length ? accounts.map(a => `
      <tr data-id="${a.id}">
        <td><input type="checkbox" class="acc-check" data-id="${a.id}" /></td>
        <td>${esc(a.name)}</td>
        <td>${a.enabled ? '<span class="badge ok">启用</span>' : '<span class="badge gray">停用</span>'} · ${statusBadge(a.last_status)}</td>
        <td>${a.proxy ? '<span class="badge">SOCKS5 代理</span>' : '<span class="badge gray">直连</span>'}</td>
        <td>${a.last_run || '从未'}</td>
        <td class="acc-verify-status">${a.last_verify_status === 'valid'
            ? '<span class="badge ok">✅ 有效</span>'
            : a.last_verify_status === 'invalid'
              ? '<span class="badge bad" title="' + esc(a.last_verify_message || '') + '">❌ 失效</span>'
              : '<span class="badge gray">未验证</span>'}</td>
        <td>
          <button class="btn btn-ghost btn-sm" data-act="verify" onclick="verifyAcc(${a.id})">验证</button>
          <button class="btn btn-ghost btn-sm" onclick="toggleAccEnabled(${a.id})">${a.enabled ? '停用' : '启用'}</button>
          <button class="btn btn-ghost btn-sm" onclick="openAccModal(${a.id})">编辑</button>
          <button class="btn btn-danger btn-sm" onclick="delAcc(${a.id})">删除</button>
        </td>
      </tr>`).join('') : '<tr><td colspan="7" style="color:var(--muted)">暂无账号</td></tr>';
    $('#accCheckAll').checked = false;
    updateSelCount();
    $('#btn-spark-selected').disabled = true;
  } catch (e) {
    if (tb) tb.innerHTML = `<tr><td colspan="7"><div class="empty-state error-state">${esc(e.message || '账号加载失败')}</div></td></tr>`;
    toast('加载账号失败', 'err');
  }
}

function getSelectedIds() { return Array.from(document.querySelectorAll('.acc-check:checked')).map(c => +c.dataset.id); }
function updateSelCount() {
  const n = getSelectedIds().length;
  $('#batchBar').hidden = n === 0;
  $('#selCount').textContent = n;
  $('#btn-spark-selected').disabled = n === 0;
  const cbs = document.querySelectorAll('.acc-check');
  if (cbs.length) $('#accCheckAll').checked = cbs.length === Array.from(cbs).filter(c => c.checked).length;
}
$('#accCheckAll').addEventListener('change', e => { document.querySelectorAll('.acc-check').forEach(c => { if (!c.disabled) c.checked = e.target.checked; }); updateSelCount(); });
document.addEventListener('change', e => { if (e.target.classList && e.target.classList.contains('acc-check')) updateSelCount(); });
$('#btn-sel-clear').onclick = () => { document.querySelectorAll('.acc-check').forEach(c => c.checked = false); updateSelCount(); };
$('#btn-sel-enable').onclick = () => batchSetEnabled(true);
$('#btn-sel-disable').onclick = () => batchSetEnabled(false);
$('#btn-spark-selected').onclick = async () => {
  const ids = getSelectedIds();
  if (!ids.length) return toast('请先勾选账号', 'err');
  try { await api.post('/api/tasks/run', { account_ids: ids }); toast('已启动续火', 'good'); loadDashboard(); }
  catch (e) { toast('启动失败', 'err'); }
};

function batchSetEnabled(enabled) {
  const ids = getSelectedIds();
  if (!ids.length) return;
  Promise.all(ids.map(id => api.put('/api/accounts/' + id, { enabled }))).then(() => {
    toast((enabled ? '已启用' : '已停用') + ' ' + ids.length + ' 个账号', 'good'); loadAccounts();
  }).catch(() => toast('批量操作失败', 'err'));
}

async function verifyAcc(id) {
  const row = document.querySelector(`#accTable tr[data-id="${id}"]`);
  const btn = row && row.querySelector('button[data-act="verify"]');
  const statusCell = row && row.querySelector('.acc-verify-status');
  if (btn) {
    btn.disabled = true;
    btn.dataset.origText = btn.dataset.origText || btn.textContent;
    btn.innerHTML = '<span class="spinner"></span> 验证中…';
  }
  if (statusCell) {
    statusCell.dataset.origHtml = statusCell.dataset.origHtml ?? statusCell.innerHTML;
    statusCell.innerHTML = '<span class="badge warn"><span class="spinner"></span> 验证中</span>';
  }
  try {
    const r = await api.post('/api/accounts/' + id + '/verify', {});
    const msg = r.valid ? '✅ Cookie 有效' : '❌ ' + (r.message || '失败');
    if (statusCell) {
      statusCell.innerHTML = r.valid
        ? '<span class="badge ok">✅ 有效</span>'
        : '<span class="badge bad" title="' + esc(r.message || '') + '">❌ 失效</span>';
    }
    toast(msg, r.valid ? 'good' : 'err');
  } catch (e) {
    if (statusCell) {
      statusCell.innerHTML = '<span class="badge bad" title="' + esc(e.message || '') + '">❌ 错误</span>';
    }
    toast('验证失败：' + (e.message || e), 'err');
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = btn.dataset.origText || '验证';
    }
  }
}

async function toggleAccEnabled(id) {
  const a = (window.__accounts || []).find(x => x.id === id);
  if (!a) return;
  try { await api.put('/api/accounts/' + id, { enabled: !a.enabled }); toast(a.enabled ? '已停用' : '已启用', 'good'); loadAccounts(); }
  catch (e) { toast('操作失败', 'err'); }
}

async function populateProxySelect(sel, selectedValue = '') {
  let proxies = [];
  try {
    const list = await api.get('/api/proxies');
    proxies = asArray(list, 'proxies').filter(p => p.enabled !== false);
  } catch (e) {}
  // 前端发送 proxy_id，服务端查表后返回真 url；
  // 仍然接受原始 url（向后兼容）。
  const opt = (v, t) => `<option value="${esc(v)}"${String(v) === String(selectedValue) ? ' selected' : ''}>${esc(t)}</option>`;
  sel.innerHTML = opt('', '自动 / 直连') + proxies.map(p => opt(p.proxy_id, p.label || p.ip)).join('');
}

/* ===== Cookie 编辑器 ===== */
let __cookieFields = [];
let __cookieSource = '';  // 'text' | 'rows' | 'json'

function openAccModal(id = null) {
  editingAccId = id;
  $('#accModalTitle').textContent = id ? '编辑账号' : '添加账号';
  $('#m-name').value = '';
  resetCookieEditor();
  populateProxySelect($('#m-proxy'), '');
  if (id) {
    api.get('/api/accounts/' + id).then(a => {
      $('#m-name').value = a.name;
      populateProxySelect($('#m-proxy'), a.proxy_id != null ? a.proxy_id : '');
      $('#m-enabled').checked = !!a.enabled;
      const initial = parseCookieString(a.cookie);
      // 先填好文本框，再切 Tab — 避免 switchCookieTab 的联动重-parse 把字段清空
      $('#m-cookie').value = a.cookie && !a.cookie.startsWith('[') ? a.cookie : '';
      if (initial.length) {
        setCookieFields(initial, 'rows');
        switchCookieTab('rows');
      } else {
        setCookieFields([], 'text');
        switchCookieTab('text');
      }
      updateCookieJson();
    });
  } else {
    switchCookieTab('text');
  }
  $('#accModal').hidden = false;
}
$('#btn-add-acc').onclick = () => openAccModal();
$('#accModalClose').onclick = $('#accModalCancel').onclick = () => $('#accModal').hidden = true;

$('#accModalVerify').onclick = async () => {
  // 验证时使用当前最新的 JSON
  updateCookieJson();
  const cookie = $('#m-cookie-json').value.trim();
  const proxy = $('#m-proxy').value.trim();
  if (!cookie) return toast('请先输入 Cookie', 'err');
  toast('验证中…');
  try {
    const r = await api.post('/api/accounts/verify', { cookie, proxy });
    toast(r.valid ? '✅ Cookie 有效' : '❌ ' + r.message, r.valid ? 'good' : 'err');
  } catch (e) { toast('验证失败：' + e.message, 'err'); }
};

$('#accModalSave').onclick = async () => {
  updateCookieJson();
  const json = $('#m-cookie-json').value.trim();
  const body = {
    name: $('#m-name').value.trim() || '未命名账号',
    cookie: json,
    proxy: $('#m-proxy').value.trim(),
    enabled: $('#m-enabled').checked,
  };
  if (!body.cookie) return toast('Cookie 不能为空', 'err');
  try {
    if (editingAccId) await api.put('/api/accounts/' + editingAccId, body);
    else await api.post('/api/accounts', body);
    toast('保存成功', 'good');
    $('#accModal').hidden = true;
    loadAccounts(); loadDashboard();
  } catch (e) { toast('保存失败：' + e.message, 'err'); }
};

async function delAcc(id) {
  if (!confirm('确定删除该账号及其所有好友？')) return;
  try { await api.del('/api/accounts/' + id); toast('已删除', 'good'); loadAccounts(); loadDashboard(); }
  catch (e) { toast('删除失败', 'err'); }
}

/* ===== Cookie 编辑器（3 Tab 联动） ===== */
function resetCookieEditor() {
  __cookieFields = [];
  __cookieSource = 'text';
  $('#m-cookie').value = '';
  $('#m-cookie-json').value = '';
  renderCookieRows();
  updateCookieJson();
  setCookieStatus('parse', '准备就绪。粘贴后点“解析”。', 'ok');
  setCookieStatus('edit', '还没字段，点上面“粘贴文本”或“添加字段”。', '');
  setCookieStatus('json', '', '');
  switchCookieTab('text');
}

function setCookieStatus(pane, text, kind) {
  const el = document.getElementById(pane === 'parse' ? 'cookieParseStatus' : pane === 'edit' ? 'cookieEditStatus' : 'cookieJsonStatus');
  if (!el) return;
  el.textContent = text || '';
  el.classList.remove('cookie-status-ok', 'cookie-status-warn', 'cookie-status-bad');
  if (kind === 'ok') el.classList.add('cookie-status-ok');
  else if (kind === 'warn') el.classList.add('cookie-status-warn');
  else if (kind === 'bad') el.classList.add('cookie-status-bad');
}

function switchCookieTab(name) {
  document.querySelectorAll('.cookie-tab').forEach(t => {
    const active = t.dataset.tab === name;
    t.classList.toggle('active', active);
    t.setAttribute('aria-selected', active ? 'true' : 'false');
  });
  document.querySelectorAll('.cookie-pane').forEach(p => {
    p.classList.toggle('active', p.dataset.pane === name);
  });
  // 切换 Tab 时同步字段/JSON 状态
  if (name === 'rows' && __cookieSource !== 'rows') {
    // 从 text 跳到 rows，把当前文本重新解析一次
    const fields = parseCookieString($('#m-cookie').value);
    setCookieFields(fields, 'rows');
  } else if (name === 'json') {
    updateCookieJson();
  }
}

function setCookieFields(fields, source) {
  __cookieFields = fields.map(f => normalizeCookieField(f));
  __cookieSource = source;
  renderCookieRows();
  updateCookieJson();
  updateCookieCountBadge();
}

function updateCookieCountBadge() {
  const valid = __cookieFields.filter(f => f.name && f.value).length;
  const total = __cookieFields.length;
  const badge = $('#cookieCountBadge');
  if (badge) badge.textContent = String(valid);
  const edit = $('#cookieEditStatus');
  if (edit) {
    if (total === 0) edit.textContent = '还没字段，点上面“粘贴文本”或“添加字段”。';
    else if (valid === total) edit.textContent = `✅ 共 ${total} 个有效字段。`;
    else edit.textContent = `共 ${total} 个字段，${valid} 个有效。`;
  }
}

function renderCookieRows() {
  const box = $('#cookieEditorRows');
  if (!box) return;
  if (!__cookieFields.length) { box.innerHTML = ''; return; }
  box.innerHTML = __cookieFields.map((f, i) => renderCookieRow(f, i)).join('');
  box.querySelectorAll('.cookie-row').forEach((row, i) => bindCookieRow(row, i));
}

function renderCookieRow(f, i) {
  return `<div class="cookie-row${f.name && !f.value ? ' invalid' : ''}" data-idx="${i}">
    <input type="text" class="cookie-name" placeholder="name" value="${esc(f.name)}" />
    <input type="text" class="cookie-value" placeholder="value" value="${esc(f.value)}" />
    <input type="text" class="cookie-domain" placeholder="domain" value="${esc(f.domain)}" list="cookie-domain-list" />
    <div class="cookie-flags">
      <select class="cookie-same-site" title="SameSite">
        <option value="">none</option>
        <option value="Strict">Strict</option>
        <option value="Lax" selected>Lax</option>
        <option value="None">None</option>
      </select>
      <label class="cookie-flag" title="secure"><input type="checkbox" class="cookie-secure" ${f.secure ? 'checked' : ''} />sec</label>
      <label class="cookie-flag" title="httpOnly"><input type="checkbox" class="cookie-httponly" ${f.httpOnly ? 'checked' : ''} />http</label>
    </div>
    <button type="button" class="btn btn-ghost btn-sm cookie-row-del" title="删除该字段">×</button>
  </div>`;
}

function bindCookieRow(row, idx) {
  const onChange = () => {
    const f = readCookieRow(row);
    __cookieFields[idx] = f;
    updateCookieJson();
    updateCookieCountBadge();
  };
  row.querySelectorAll('input,select').forEach(el => {
    el.addEventListener('input', onChange);
    el.addEventListener('change', onChange);
  });
  row.querySelector('.cookie-row-del').onclick = () => {
    __cookieFields.splice(idx, 1);
    renderCookieRows();
    updateCookieJson();
    updateCookieCountBadge();
  };
}

function readCookieRow(row) {
  return normalizeCookieField({
    name: row.querySelector('.cookie-name').value,
    value: row.querySelector('.cookie-value').value,
    domain: row.querySelector('.cookie-domain').value,
    secure: row.querySelector('.cookie-secure').checked,
    httpOnly: row.querySelector('.cookie-httponly').checked,
    sameSite: row.querySelector('.cookie-same-site').value || 'Lax',
  });
}

function normalizeCookieField(f) {
  return {
    name: (f.name || '').trim(),
    value: f.value || '',
    domain: (f.domain || '').trim() || '.douyin.com',
    path: f.path || '/',
    secure: !!f.secure,
    httpOnly: !!f.httpOnly,
    sameSite: f.sameSite || 'Lax',
    expires: f.expires != null ? Number(f.expires) : -1,
  };
}

function updateCookieJson() {
  const json = $('#m-cookie-json');
  if (!json) return;
  const valid = __cookieFields.filter(f => f.name && f.value);
  if (!valid.length) {
    json.value = '';
    setCookieStatus('json', '等待字段输入。', '');
    return;
  }
  const cookies = valid.map(f => ({
    name: f.name,
    value: f.value,
    domain: f.domain,
    path: f.path || '/',
    expires: f.expires != null ? Number(f.expires) : -1,
    httpOnly: !!f.httpOnly,
    secure: !!f.secure,
    sameSite: f.sameSite || 'Lax',
  }));
  json.value = JSON.stringify(cookies, null, 2);
  setCookieStatus('json', `已输出 ${cookies.length} 个字段。`, 'ok');
}

/* === 粘贴文本解析 === */
function parseCookieString(text) {
  if (!text) return [];
  text = String(text).trim();
  if (!text) return [];

  // 1) JSON 数组
  if (text.startsWith('[')) {
    try {
      const arr = JSON.parse(text);
      if (Array.isArray(arr)) {
        return arr.map(normalizeCookieField).filter(f => f.name);
      }
    } catch (e) { /* fall through */ }
  }

  // 2) 标准 Netscape / Set-Cookie
  // 按行 / 按 Set-Cookie 块分割
  const lines = text.split(/\r?\n/).map(l => l.trim()).filter(Boolean);
  // 如果每行都是 Set-Cookie 完整格式（包含 Domain=/Path=/Expires=），按行处理
  const looksLikeSetCookie = lines.some(l => /Domain=|Path=|Expires=/.test(l));
  if (looksLikeSetCookie) {
    const out = [];
    for (const line of lines) {
      const parsed = parseSetCookieLine(line);
      if (parsed) out.push(parsed);
    }
    return out;
  }

  // 3) Netscape 单行/多行格式：name=value; name=value; ...
  const out = [];
  for (const part of text.split(/[;\n]+/)) {
    const seg = part.trim();
    if (!seg) continue;
    const eq = seg.indexOf('=');
    if (eq < 1) continue;
    const name = seg.slice(0, eq).trim();
    const value = seg.slice(eq + 1).trim();
    if (!name) continue;
    out.push({ name, value });
  }
  return out;
}

function parseSetCookieLine(line) {
  // 抹掉可能的前缀 "Set-Cookie:"
  let s = line.replace(/^Set-Cookie:\s*/i, '').trim();
  if (!s) return null;
  const parts = s.split(';').map(p => p.trim()).filter(Boolean);
  if (!parts.length) return null;
  const first = parts.shift();
  const eq = first.indexOf('=');
  if (eq < 1) return null;
  const out = {
    name: first.slice(0, eq).trim(),
    value: first.slice(eq + 1).trim(),
    domain: '.douyin.com',
    path: '/',
    secure: false,
    httpOnly: false,
    sameSite: 'Lax',
    expires: -1,
  };
  for (const attr of parts) {
    const idx = attr.indexOf('=');
    if (idx < 0) {
      const lower = attr.toLowerCase();
      if (lower === 'secure') out.secure = true;
      else if (lower === 'httponly') out.httpOnly = true;
      continue;
    }
    const k = attr.slice(0, idx).trim().toLowerCase();
    const v = attr.slice(idx + 1).trim();
    if (k === 'domain') out.domain = v.startsWith('.') ? v : (v ? '.' + v : '.douyin.com');
    else if (k === 'path') out.path = v || '/';
    else if (k === 'expires') {
      const t = Date.parse(v);
      if (!Number.isNaN(t)) out.expires = Math.floor(t / 1000);
    } else if (k === 'max-age') {
      const n = parseInt(v, 10);
      if (!Number.isNaN(n)) out.expires = Math.floor(Date.now() / 1000) + n;
    } else if (k === 'samesite') {
      const low = v.toLowerCase();
      if (low === 'strict') out.sameSite = 'Strict';
      else if (low === 'lax') out.sameSite = 'Lax';
      else if (low === 'none') out.sameSite = 'None';
    } else if (k === 'secure') {
      out.secure = true;
    } else if (k === 'httponly') {
      out.httpOnly = true;
    }
  }
  return out;
}

/* === Tab 联动 === */
document.querySelectorAll('.cookie-tab').forEach(btn => {
  btn.addEventListener('click', () => switchCookieTab(btn.dataset.tab));
});

// 文本框输入时实时轻量提示；点击「解析」才落库
let __parseDebounce;
$('#m-cookie').addEventListener('input', () => {
  clearTimeout(__parseDebounce);
  const text = $('#m-cookie').value;
  __parseDebounce = setTimeout(() => {
    if (!text.trim()) {
      setCookieStatus('parse', '支持 Netscape、Set-Cookie、JSON 数组。', 'ok');
      return;
    }
    const fields = parseCookieString(text);
    if (fields.length) {
      setCookieStatus('parse', `识别到 ${fields.length} 个字段，点「解析」应用。`, 'ok');
    } else {
      setCookieStatus('parse', '未能识别任何字段。检查格式。', 'bad');
    }
  }, 200);
});

$('#btn-cookie-parse').onclick = () => {
  const text = $('#m-cookie').value;
  const fields = parseCookieString(text);
  if (!fields.length) {
    setCookieStatus('parse', '未能识别任何字段。', 'bad');
    return;
  }
  setCookieFields(fields, 'rows');
  setCookieStatus('edit', `已导入 ${fields.length} 个字段。`, 'ok');
  switchCookieTab('rows');
};

$('#btn-add-cookie-row').onclick = () => {
  __cookieFields.push(normalizeCookieField({}));
  renderCookieRows();
  updateCookieJson();
  updateCookieCountBadge();
  // 聚焦新行
  setTimeout(() => {
    const rows = $$('#cookieEditorRows .cookie-row');
    const last = rows[rows.length - 1];
    if (last) last.querySelector('.cookie-name').focus();
  }, 0);
};

$('#btn-cookie-dedupe').onclick = () => {
  const seen = new Set();
  const before = __cookieFields.length;
  __cookieFields = __cookieFields.filter(f => {
    const key = `${f.domain}::${f.path}::${f.name}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
  renderCookieRows();
  updateCookieJson();
  updateCookieCountBadge();
  setCookieStatus('edit', `已去重：移除 ${before - __cookieFields.length} 条。`, 'ok');
};

$('#btn-cookie-replace-dupe').onclick = () => {
  // 保留最后一个同名同域的字段
  const map = new Map();
  for (const f of __cookieFields) {
    map.set(`${f.domain}::${f.path}::${f.name}`, f);
  }
  __cookieFields = Array.from(map.values());
  renderCookieRows();
  updateCookieJson();
  updateCookieCountBadge();
  setCookieStatus('edit', `已合并：现 ${__cookieFields.length} 条。`, 'ok');
};

$('#btn-cookie-rebuild').onclick = () => {
  // 从 JSON 文本重建字段
  const text = $('#m-cookie-json').value;
  const fields = parseCookieString(text);
  if (!fields.length) {
    setCookieStatus('json', 'JSON 不可解析或为空。', 'bad');
    return;
  }
  setCookieFields(fields, 'rows');
  setCookieStatus('json', `从 JSON 重建 ${fields.length} 个字段。`, 'ok');
  switchCookieTab('rows');
};

$('#btn-cookie-format').onclick = () => {
  try {
    const obj = JSON.parse($('#m-cookie-json').value || '[]');
    $('#m-cookie-json').value = JSON.stringify(obj, null, 2);
    setCookieStatus('json', '已格式化。', 'ok');
  } catch (e) {
    setCookieStatus('json', 'JSON 解析失败：' + e.message, 'bad');
  }
};

// 手动修改 JSON 时（粘贴新 JSON 进来），尝试回填字段
$('#m-cookie-json').addEventListener('input', () => {
  // 不打断用户手输；只在值变化时刷新状态，不强制重建字段。
  setCookieStatus('json', '检测到 JSON 编辑。保存时会用此处内容。', 'warn');
});

/* ===== 代理管理 ===== */
let editingProxyId = null;
async function loadProxies() {
  setLoading($('#proxyList'), '加载代理节点中…');
  try {
    const list = asArray(await api.get('/api/proxies'), 'proxies');
    $('#proxyListHint').textContent = list.length ? '' : '添加后，账号管理里可为每个账号指定对应代理（不同节点并行续火）。';
    const box = $('#proxyList');
    if (!list.length) {
      box.innerHTML = '<div style="color:var(--muted);padding:16px;text-align:center">尚未添加代理节点，点击「＋ 添加代理」</div>';
      return;
    }
    box.innerHTML = list.map(p => {
      const flag = flagEmoji(p.geo_country_code);
      const host = p.ip || '已配置';
      const has = p.ip || (p.url || '').includes('socks5');
      const geoParts = [p.geo_country, p.geo_region, p.geo_city].filter(Boolean);
      const geoHtml = geoParts.length ? `<div class="proxy-geo-line">${flag} ${esc(geoParts.join(' · '))}${p.geo_ip ? ' · ' + esc(p.geo_ip) : ''}</div>` : (has ? '<div class="proxy-geo-line"><span class="badge gray">归属地未识别</span></div>' : '');
      const testHtml = proxyTestHtml(p);
      return `<div class="proxy-card ${p.enabled === false ? 'proxy-disabled' : ''}">
        <div class="proxy-top">
          <div class="proxy-flag">${flag}</div>
          <div class="proxy-main">
            <div class="proxy-name">${esc(p.label || (p.geo_country ? p.geo_country + ' ' + p.geo_region : host))} ${p.enabled === false ? '<span class="badge gray">停用</span>' : ''}</div>
            <div class="proxy-meta">${has ? 'SOCKS5 节点' : '请编辑补全'}${p.port ? ' · 端口 ' + esc(p.port) : ''}</div>
          </div>
          <div class="proxy-actions">
            <button class="btn btn-ghost btn-sm" onclick="testProxy(${p.id})">测试</button>
            <button class="btn btn-ghost btn-sm" onclick="openProxyModal(${p.id})">编辑</button>
            <button class="btn btn-danger btn-sm" onclick="delProxy(${p.id})">删除</button>
          </div>
        </div>
        ${geoHtml}
        <div class="proxy-test" id="ptest-${p.id}">${testHtml}</div>
      </div>`;
    }).join('');
  } catch (e) { setError($('#proxyList'), e.message, loadProxies); toast('加载代理失败', 'err'); }
}

function proxyTestHtml(p) {
  if (!p.last_test) return '<span class="ptest-idle">尚未测速</span>';
  const cls = p.last_test === 'ok' ? 't-ok' : 't-bad';
  const latency = Number(p.last_latency_ms || 0);
  const detail = p.last_test_message || (p.last_test === 'ok' ? '测试成功' : '测试失败');
  const tested = p.last_test_at ? ` · ${esc(p.last_test_at.slice(5, 16))}` : '';
  return `<span class="${cls}">${cls === 't-ok' ? '●' : '●'} ${esc(detail)}${latency && !detail.includes('ms') ? ` · ${latency} ms` : ''}${tested}</span>`;
}

$('#btn-add-proxy').onclick = () => openProxyModal();
$('#proxyModalClose').onclick = $('#proxyModalCancel').onclick = () => $('#proxyModal').hidden = true;

$('#p-url').oninput = () => {
  const url = $('#p-url').value.trim();
  if (!url.includes('socks5://')) return;
  const m = url.match(/socks5:\/\/(?:([^:@\/]+):([^@\/]*))?@?([^:\/\s]+):(\d+)/);
  if (m) {
    $('#p-ip').value = m[3]; $('#p-port').value = m[4];
    if (m[1]) $('#p-user').value = decodeURIComponent(m[1]);
    if (m[2]) $('#p-pwd').value = decodeURIComponent(m[2]);
    $('#p-geo-status').textContent = '已解析，点「识别归属地」…';
  }
};

$('#btn-p-detect').onclick = async () => {
  const st = $('#p-geo-status');
  const body = {};
  const pw = $('#p-pwd').value.trim();
  if (editingProxyId && !pw) { body.proxy_id = editingProxyId; }
  else {
    const url = buildProxyUrlFromForm() || $('#p-url').value.trim();
    if (!url) { toast('请填写 IP 或链接', 'err'); return; }
    body.url = url;
  }
  st.textContent = '识别中…';
  try {
    const r = await api.post('/api/proxies/detect', body);
    if (r.ok) { $('#p-geo').innerHTML = `<div class="geo-preview-item">🌐 ${esc(r.country || '')} ${esc(r.region || '')}（${esc(r.ip || '')}）</div>`; st.textContent = '✅ 识别成功'; }
    else { $('#p-geo').innerHTML = ''; st.textContent = '❌ ' + (r.message || '识别失败'); }
  } catch (e) { st.textContent = '❌ ' + e.message; }
};

function buildProxyUrlFromForm() {
  const ip = $('#p-ip').value.trim(), port = $('#p-port').value.trim();
  if (!ip || !port) return '';
  const u = $('#p-user').value.trim(), pw = $('#p-pwd').value.trim();
  return 'socks5://' + (u ? encodeURIComponent(u) + (pw ? ':' + encodeURIComponent(pw) : '') + '@' : '') + ip + ':' + port;
}

$('#proxyModalSave').onclick = async () => {
  const ip = $('#p-ip').value.trim(), port = $('#p-port').value.trim();
  const pw = $('#p-pwd').value.trim();
  const pasted = $('#p-url').value.trim();
  const body = { label: $('#p-label').value.trim() };
  if (editingProxyId && !pw && !pasted) {
    if (ip) body.ip = ip;
    if (port) body.port = +port;
    const u = $('#p-user').value.trim();
    if (u) body.username = u;
  } else {
    const url = buildProxyUrlFromForm() || pasted;
    if (!url) { toast('请填写 IP/端口 或 完整链接', 'err'); return; }
    body.url = url;
  }
  try {
    if (editingProxyId) await api.put('/api/proxies/' + editingProxyId, body);
    else await api.post('/api/proxies', body);
    $('#proxyModal').hidden = true;
    toast('保存成功', 'good');
    loadProxies();
  } catch (e) { toast('保存失败：' + e.message, 'err'); }
};

function openProxyModal(id = null) {
  editingProxyId = id;
  $('#proxyModalTitle').textContent = id ? '编辑代理' : '添加代理';
  ['p-url', 'p-ip', 'p-port', 'p-user', 'p-pwd', 'p-label'].forEach(i => $('#' + i).value = '');
  $('#p-geo').innerHTML = ''; $('#p-geo-status').textContent = '';
  $('#p-pwd').placeholder = id ? '留空表示不修改' : '';
  if (id) {
    api.get('/api/proxies').then(data => {
      const list = asArray(data, 'proxies');
      const p = list.find(x => x.id === id);
      if (!p) return;
      if (p.ip) $('#p-ip').value = p.ip;
      if (p.port) $('#p-port').value = p.port;
      if (p.username) $('#p-user').value = p.username;
      if (p.label) $('#p-label').value = p.label;
      $('#p-geo').innerHTML = p.geo_country ? `<div class="geo-preview-item">🌐 ${esc(p.geo_country)} ${esc(p.geo_region || '')}</div>` : '';
    });
  }
  $('#proxyModal').hidden = false;
}

window.testProxy = async (id) => {
  const el = $('#ptest-' + id);
  const btn = document.querySelector(`button[onclick="testProxy(${id})"]`);
  if (el) el.innerHTML = '<span class="ptest-running"><i></i> 正在测速…</span>';
  if (btn) { btn.disabled = true; btn.textContent = '测速中'; }
  try {
    const r = await api.post('/api/proxies/' + id + '/test', {});
    if (el) el.innerHTML = `<span class="${r.ok ? 't-ok' : 't-bad'}">${r.ok ? '●' : '●'} ${esc(r.message)} · 已保存</span>`;
  } catch (e) { if (el) el.innerHTML = `<span class="t-bad">● 测试失败：${esc(e.message || '网络错误')}</span>`; }
  finally { if (btn) { btn.disabled = false; btn.textContent = '测试'; } }
};

window.delProxy = async (id) => {
  if (!confirm('确定删除该代理？')) return;
  try { await api.del('/api/proxies/' + id); toast('已删除', 'good'); loadProxies(); }
  catch (e) { toast('删除失败', 'err'); }
};

$('#btn-proxy-test-all').onclick = async () => {
  const btn = $('#btn-proxy-test-all');
  try {
    const list = asArray(await api.get('/api/proxies'), 'proxies');
    btn.disabled = true; btn.textContent = `测速中 0/${list.length}`;
    for (let i = 0; i < list.length; i++) { btn.textContent = `测速中 ${i + 1}/${list.length}`; await testProxy(list[i].id); }
    btn.textContent = '🧪 测试全部'; btn.disabled = false;
  } catch (e) { btn.textContent = '🧪 测试全部'; btn.disabled = false; toast('批量测速失败', 'err'); }
};

/* ===== 好友管理 ===== */
let currentFriendAccountId = null;
let editingFriendId = null;

async function loadFriends() {
  try {
    const accounts = asArray(await api.get('/api/accounts'), 'accounts');
    const select = $('#friends-account-select');
    select.innerHTML = '<option value="">选择账号</option>' +
      accounts.filter(a => a.enabled).map(a => `<option value="${a.id}">${esc(a.name)}</option>`).join('');
    select.onchange = () => { currentFriendAccountId = select.value ? parseInt(select.value) : null; renderFriends(); };
    if (!currentFriendAccountId && accounts.length) {
      currentFriendAccountId = accounts.find(a => a.enabled)?.id || accounts[0].id;
      select.value = currentFriendAccountId;
    }
    renderFriends();
  } catch (e) { toast('加载好友失败', 'err'); }
}

async function renderFriends() {
  if (!currentFriendAccountId) { $('#friendsTable tbody').innerHTML = '<tr><td colspan="4" style="color:var(--muted)">请先选择账号</td></tr>'; return; }
  try {
    const data = await api.get('/api/targets?account_id=' + currentFriendAccountId);
    const targets = asArray(data, 'targets');
    const tb = $('#friendsTable tbody');
    tb.innerHTML = targets.length ? targets.map(t => `
      <tr>
        <td>${esc(t.name)}</td>
        <td>${t.enabled ? '<span class="badge ok">启用</span>' : '<span class="badge gray">停用</span>'}</td>
        <td>${t.last_run || '未运行'}</td>
        <td>
          <button class="btn btn-ghost btn-sm" onclick="toggleFriend(${t.id}, ${!t.enabled})">${t.enabled ? '停用' : '启用'}</button>
          <button class="btn btn-danger btn-sm" onclick="deleteFriend(${t.id})">删除</button>
        </td>
      </tr>`).join('') : '<tr><td colspan="4" style="color:var(--muted)">暂无好友</td></tr>';
  } catch (e) { toast('加载失败', 'err'); }
}

$('#btn-add-friend').onclick = () => {
  if (!currentFriendAccountId) return toast('请先选择账号', 'err');
  $('#m-friend-name').value = ''; editingFriendId = null; $('#friendModal').hidden = false;
};

$('#btn-fetch-friends').onclick = () => {
  if (!currentFriendAccountId) return toast('请先选择账号', 'err');
  openFetchFriendsModal(currentFriendAccountId);
};

$('#friendModalClose').onclick = $('#friendModalCancel').onclick = () => $('#friendModal').hidden = true;
$('#friendModalSave').onclick = async () => {
  const name = $('#m-friend-name').value.trim();
  if (!name) return toast('请输入好友名称', 'err');
  try { await api.post('/api/targets', { account_id: currentFriendAccountId, name }); $('#friendModal').hidden = true; toast('添加成功', 'good'); renderFriends(); }
  catch (e) { toast('添加失败', 'err'); }
};

window.toggleFriend = async (id, enabled) => {
  try { await api.put('/api/targets/' + id, { enabled }); toast(enabled ? '已启用' : '已停用', 'good'); renderFriends(); }
  catch (e) { toast('操作失败', 'err'); }
};

window.deleteFriend = async (id) => {
  if (!confirm('确定删除该好友？')) return;
  try { await api.del('/api/targets/' + id); toast('已删除', 'good'); renderFriends(); }
  catch (e) { toast('删除失败', 'err'); }
};

/* ===== 自动获取好友列表 ===== */
function openFetchFriendsModal(accountId) {
  $('#fetchFriendsModal').hidden = false;
  $('#fetch-friends-status').textContent = '正在获取好友列表…';
  $('#fetch-friends-list').innerHTML = '';
  $('#fetchFriendsModalSave').disabled = true;
  api.get('/api/accounts/' + accountId + '/friends').then(r => {
    const friends = r.friends || [];
    if (!friends.length) {
      const msg = r.message || '未获取到好友列表';
      const hint = r.reason === 'login_page' ? '（请重新登录后重试）' : r.reason === 'empty' ? '（请稍后重试或检查网络）' : '';
      $('#fetch-friends-status').textContent = `${msg}${hint}`;
      return;
    }
    $('#fetch-friends-status').textContent = `共获取到 ${friends.length} 位好友，勾选后点击添加`;
    $('#fetch-friends-list').innerHTML = friends.map((f) => `
      <label class="friend-pick-item">
        <input type="checkbox" class="friend-pick-check" value="${esc(f)}" />
        <span>${esc(f)}</span>
      </label>
    `).join('');
    $('#fetchFriendsModalSave').disabled = false;
  }).catch(e => { $('#fetch-friends-status').textContent = '获取失败: ' + e.message; });
}

$('#fetchFriendsModalClose').onclick = $('#fetchFriendsModalCancel').onclick = () => $('#fetchFriendsModal').hidden = true;
$('#fetchFriendsModalSave').onclick = async () => {
  const checked = $$('.friend-pick-check:checked');
  if (!checked.length) return toast('请先勾选好友', 'err');
  const names = checked.map(c => c.value);
  try {
    for (const name of names) { await api.post('/api/targets', { account_id: currentFriendAccountId, name }); }
    $('#fetchFriendsModal').hidden = true;
    toast(`已添加 ${names.length} 位好友`, 'good');
    renderFriends();
  } catch (e) { toast('添加失败', 'err'); }
};

/* ===== 日志 ===== */
async function loadLogs(reset = true) {
  if (reset) $('#logList').innerHTML = '<div style="color:var(--muted);padding:16px">加载中…</div>';
  try {
    const status = $('#logFilter').value;
    const kw = ($('#logSearch').value || '').trim().toLowerCase();
    const data = await api.get('/api/logs?limit=200' + (status ? '&status=' + status : ''));
    const logs = asArray(data, 'logs').filter(l => {
      if (!kw) return true;
      return ((l.account_name || '') + ' ' + (l.message || '') + ' ' + (l.target_name || '')).toLowerCase().includes(kw);
    });
    const list = $('#logList');
    const countBox = $('#logCount');
    if (!logs.length) { list.innerHTML = '<div style="color:var(--muted);padding:20px">暂无日志</div>'; countBox.textContent = '共 0 条'; return; }
    list.innerHTML = logs.map(l => {
      const t = (l.created_at || '').slice(5, 16);
      const badge = l.status === 'success' ? '<span class="badge ok">成功</span>'
        : l.status === 'partial' ? '<span class="badge warn">部分</span>'
          : '<span class="badge bad">失败</span>';
      return `<div class="log-simple">
        <span class="log-simple-time">${esc(t)}</span>
        <span class="log-simple-name">${esc(l.account_name || '')}</span>
        ${l.target_name ? '<span style="color:var(--muted)">→ ' + esc(l.target_name) + '</span>' : ''}
        ${badge}
        <span class="log-msg">${esc(l.message || '')}</span>
      </div>`;
    }).join('');
    countBox.textContent = `共 ${logs.length} 条`;
  } catch (e) {
    setError($('#logList'), e.message, () => loadLogs(true));
    $('#logCount').textContent = '';
    toast('加载日志失败', 'err');
  }
}
$('#btn-refresh-logs').onclick = loadLogs;
$('#logSearch').addEventListener('input', () => loadLogs(false));
$('#logFilter').addEventListener('change', () => loadLogs(true));
$('#btn-clear-logs').onclick = async () => {
  if (!confirm('确定清空全部日志？此操作不可恢复。')) return;
  try { await api.del('/api/logs'); toast('已清空日志', 'good'); loadLogs(); loadDashboard(); }
  catch (e) { toast('清空失败', 'err'); }
};

/* ===== 设置 ===== */
async function loadSettings() {
  try {
    const data = await api.get('/api/settings');
    const s = data.settings || {};
    $('#s-tg_enabled').checked = (s.tg_enabled || '0') === '1';
    $('#s-tg_bot_token').value = '';
    $('#s-tg_bot_token').placeholder = s.tg_bot_token ? '已配置，留空表示不修改' : '请输入 Bot Token';
    $('#s-tg_user_id').value = s.tg_user_id || '';
    $('#s-tg_quote_enabled').checked = (s.tg_quote_enabled || '0') === '1';
    $('#s-tg_only_on_change').checked = (s.tg_only_on_change || '0') === '1';
    $('#s-tg_silent').checked = (s.tg_silent || '0') === '1';
    $('#s-schedule_enabled').checked = (s.schedule_enabled || '1') === '1';
    $('#s-schedule_cron').value = s.schedule_cron || '0 8 * * *';
    $('#s-anti_ban_enabled').checked = (s.anti_ban_enabled || '1') === '1';
    $('#s-anti_ban_wait_min').value = s.anti_ban_wait_min || '120';
    $('#s-anti_ban_wait_max').value = s.anti_ban_wait_max || '300';
    $('#s-anti_ban_window_hour').value = s.anti_ban_window_hour || '7';
    $('#s-proxy_force').checked = (s.proxy_force || '0') === '1';
    $('#s-proxy_fallback').checked = (s.proxy_fallback || '1') === '1';
    $('#s-spark_delay_min').value = s.spark_delay_min || '3';
    $('#s-spark_delay_max').value = s.spark_delay_max || '8';
    $('#s-message_template').value = s.message_template || '';
    $('#s-yiyan_include_source').value = s.yiyan_include_source || '1';
    $('#s-log_retention_days').value = s.log_retention_days || '30';
  } catch (e) { toast('加载设置失败', 'err'); }
}

function collectSettings() {
  const val = (id, dflt = '') => { const el = $('#' + id); return el ? el.value : dflt; };
  const chk = (id) => { const el = $('#' + id); return el && el.checked ? '1' : '0'; };
  const settings = {
    tg_enabled: chk('s-tg_enabled'),
    tg_user_id: val('s-tg_user_id').trim(),
    tg_quote_enabled: chk('s-tg_quote_enabled'),
    tg_only_on_change: chk('s-tg_only_on_change'),
    tg_silent: chk('s-tg_silent'),
    schedule_enabled: chk('s-schedule_enabled'),
    schedule_cron: val('s-schedule_cron').trim(),
    anti_ban_enabled: chk('s-anti_ban_enabled'),
    anti_ban_wait_min: val('s-anti_ban_wait_min'),
    anti_ban_wait_max: val('s-anti_ban_wait_max'),
    anti_ban_window_hour: val('s-anti_ban_window_hour'),
    proxy_force: chk('s-proxy_force'),
    proxy_fallback: chk('s-proxy_fallback'),
    spark_delay_min: val('s-spark_delay_min'),
    spark_delay_max: val('s-spark_delay_max'),
    message_template: val('s-message_template'),
    yiyan_include_source: val('s-yiyan_include_source'),
    log_retention_days: val('s-log_retention_days', '30'),
  };
  const token = val('s-tg_bot_token').trim();
  if (token) settings.tg_bot_token = token;
  return settings;
}

$('#btn-save-all').onclick = async () => {
  const status = $('#saveStatus');
  status.textContent = '保存中…'; status.className = 'save-status';
  try { await api.post('/api/settings', collectSettings()); status.textContent = '✅ 已保存'; status.className = 'save-status ok'; setTimeout(() => status.textContent = '', 2500); }
  catch (e) { status.textContent = '保存失败'; status.className = 'save-status'; }
};
$('#btn-save-schedule').onclick = async () => {
  try { await api.post('/api/tasks/schedule', { enabled: $('#s-schedule_enabled').checked, cron: $('#s-schedule_cron').value.trim() }); toast('定时配置已保存', 'good'); }
  catch (e) { toast('保存失败', 'err'); }
};
$('#btn-save-template').onclick = async () => {
  try { await api.put('/api/settings', { message_template: $('#s-message_template').value, yiyan_include_source: $('#s-yiyan_include_source').value }); toast('模板已保存', 'good'); }
  catch (e) { toast('保存失败', 'err'); }
};
$('#btn-test-tg').onclick = async () => {
  toast('发送测试中…');
  try {
    const r = await api.post('/api/settings/test-tg', {});
    if (r.ok) toast('测试消息已发送', 'good');
    else toast('发送失败: ' + (r.message || ''), 'err');
  } catch (e) { toast('发送失败', 'err'); }
};

/* ===== 立即续火 + 运行状态轮询 ===== */
$('#btn-run').onclick = async () => {
  try {
    $('#runModal').hidden = false;
    $('#runBar').style.width = '0%';
    $('#runInfo').textContent = '正在启动…';
    $('#runLines').innerHTML = '';
    const r = await api.post('/api/tasks/run', {});
    if (r && r.status === 'skipped') {
      $('#runInfo').textContent = '⚠️ 已有续火任务在运行，请等待当前任务完成';
      addRunLine('本次点击被跳过：上一个任务仍在运行中');
      loadDashboard();
      return;
    }
    pollRun();
  } catch (e) {
    toast('启动失败：' + (e.message || e), 'err');
    $('#runModal').hidden = true;
  }
};
$('#runModalClose').onclick = () => $('#runModal').hidden = true;

async function pollRun() {
  if (pollTimer) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
  // 如果 3 秒内还没有任何 poll 返回 running 状态，在 “正在启动…” 后追加等待计时
  let firstRunningSeen = false;
  const waitingFromAt = Date.now();
  const waitingTip = setInterval(() => {
    if (firstRunningSeen) {
      clearInterval(waitingTip);
      return;
    }
    const sec = Math.floor((Date.now() - waitingFromAt) / 1000);
    if (sec >= 3) {
      $('#runInfo').textContent = `正在启动…已等 ${sec}s（首次访问页加载中）`;
    }
  }, 1000);

  pollTimer = setInterval(async () => {
    try {
      const s = await api.get('/api/tasks/run');
      if (s.run && s.run.status === 'running') {
        firstRunningSeen = true;
        clearInterval(waitingTip);
        const r = s.run;
        const subMsg = r.message || `账号 ${r.current_account || ''}`;
        $('#runInfo').textContent = `账号 ${r.accounts_done || 0}/${r.accounts_total || 0}（${r.progress || 0}%）· ${subMsg}`;
        $('#runBar').style.width = (r.progress || 0) + '%';
        const acct = r.current_account ? ` · 正在处理 ${r.current_account}` : '';
        addRunLine(`运行中… 已完成 ${r.accounts_done || 0}/${r.accounts_total || 0} 个账号${acct}`);
        // 实时刷新日志页（如果用户当前在日志页）
        const activeNav = document.querySelector('.nav button.active');
        if (activeNav && activeNav.dataset && activeNav.dataset.view === 'logs' && typeof loadLogs === 'function') {
          loadLogs(false);
        }
      } else {
        clearInterval(pollTimer);
        pollTimer = null;
        clearInterval(waitingTip);
        $('#runBar').style.width = '100%';
        const last = await api.get('/api/tasks');
        const lastTask = (last.tasks || [])[0];
        if (lastTask) {
          $('#runInfo').textContent = `✅ 完成（${lastTask.status}）`;
          addRunLine(`完成：${lastTask.message || ''}`);
        } else {
          $('#runInfo').textContent = '✅ 完成（无历史任务）';
          addRunLine('完成：未找到本次任务记录');
        }
        loadDashboard(); loadAccounts(); loadLogs();
      }
    } catch (e) {
      clearInterval(pollTimer);
      pollTimer = null;
      clearInterval(waitingTip);
      $('#runInfo').textContent = '运行状态获取失败';
      addRunLine(e.message || '网络请求失败');
    }
  }, 1500);
}

function addRunLine(txt) {
  const box = $('#runLines');
  const div = document.createElement('div');
  div.className = 'ln';
  div.textContent = txt;
  box.appendChild(div);
  box.scrollTop = box.scrollHeight;
}

/* ===== 版本 ===== */
async function loadVersion() {
  try { const h = await api.get('/api/health'); const el = document.getElementById('app-version'); if (el && h && h.version) el.textContent = 'v' + h.version; } catch (e) { }
}

/* ===== 健康检查 ===== */
$('#btn-health').onclick = async () => {
  try { const h = await api.get('/api/health'); toast(`服务正常 · v${h.version} · 上次续火 ${h.time}`, 'good'); }
  catch (e) { toast('服务异常', 'err'); }
};

/* ===== 账户：当前用户 / 退出 / 改密 ===== */
async function loadMe() {
  try { const me = await api.get('/api/auth/me'); $('#btn-user').textContent = '👤 ' + (me.user?.username || ''); } catch (e) { }
}
$('#btn-logout').onclick = async () => {
  try { await api.post('/api/auth/logout', {}); } catch (e) { }
  location.href = '/login.html';
};
$('#btn-change-pwd').onclick = async () => {
  const oldP = $('#p-old').value, newP = $('#p-new').value;
  const st = $('#pwd-status');
  if (!oldP || !newP) { st.textContent = '请填写原密码和新密码'; return; }
  if (newP.length < 6) { st.textContent = '新密码至少 6 位'; return; }
  st.textContent = '提交中…';
  try {
    const r = await api.post('/api/auth/change-password', { old_password: oldP, new_password: newP });
    st.textContent = '✅ ' + (r.message || '已修改');
    setTimeout(() => location.href = '/login.html', 1200);
  } catch (e) { st.textContent = e.message || '修改失败'; }
};

/* ===== 实时续火状态条 ===== */
let _liveRun = null;
let _liveRunTimer = null;

async function _pollLiveRun() {
  try {
    const s = await api.get('/api/tasks/run');
    _liveRun = s.run || null;
  } catch (e) {
    _liveRun = null;
  }
  _renderLiveRunBar();
}

function _renderLiveRunBar() {
  const bar = $('#liveRunBar');
  if (!bar) return;
  if (_liveRun && _liveRun.status === 'running') {
    const r = _liveRun;
    const subMsg = r.message || (r.current_account ? `正在处理 ${r.current_account}` : '');
    bar.hidden = false;
    bar.classList.add('live');
    bar.innerHTML = `
      <div class="live-run-row">
        <span class="spinner"></span>
        <span class="live-run-text">续火进行中 · 账号 ${r.accounts_done || 0}/${r.accounts_total || 0}（${r.progress || 0}%）</span>
        <span class="live-run-sub">${subMsg}</span>
        <button class="btn btn-sm" onclick="document.querySelector('button[data-view=&quot;logs&quot;]')?.click(); document.getElementById('runModal')?.removeAttribute('hidden')">查看详情</button>
      </div>
    `;
  } else {
    bar.hidden = true;
    bar.classList.remove('live');
    bar.innerHTML = '';
  }
}

function startLiveRunPolling() {
  if (_liveRunTimer) return;
  _pollLiveRun();
  _liveRunTimer = setInterval(_pollLiveRun, 3000);
}

/* ===== 初始化 ===== */
loadVersion();
loadMe();
loadDashboard();
setInterval(() => { if (!$('#view-dashboard').hidden) loadDashboard(); }, 30000);
startLiveRunPolling();
