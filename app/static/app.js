/* ===== 抖音续火花管理面板 - 前端逻辑 ===== */
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];

function handleResp(r) {
  if (r.status === 401) { location.href = '/login.html'; throw new Error('未登录'); }
  if (!r.ok) throw new Error('请求失败 ' + r.status);
  return r;
}

const api = {
  get: (p) => fetch(p).then(r => handleResp(r)).then(r => r.json()),
  post: (p, b) => fetch(p, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b || {}) }).then(r => handleResp(r)).then(r => r.json()),
  put: (p, b) => fetch(p, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b) }).then(r => handleResp(r)).then(r => r.json()),
  del: (p) => fetch(p, { method: 'DELETE' }).then(r => handleResp(r)).then(r => r.json()),
};

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
const VIEW_TITLES = { dashboard: '仪表盘', accounts: '账号管理', proxies: '代理', friends: '好友管理', yiyan: '一言库', logs: '续火日志', settings: '设置' };
$$('.nav-item').forEach(btn => {
  btn.onclick = () => {
    $$('.nav-item').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    $$('.view').forEach(v => v.hidden = true);
    $('#view-' + btn.dataset.view).hidden = false;
    $('#view-title').textContent = VIEW_TITLES[btn.dataset.view];
    if (btn.dataset.view === 'dashboard') loadDashboard();
    if (btn.dataset.view === 'accounts') loadAccounts();
    if (btn.dataset.view === 'proxies') loadProxies();
    if (btn.dataset.view === 'friends') loadFriends();
    if (btn.dataset.view === 'yiyan') loadYiyan();
    if (btn.dataset.view === 'logs') loadLogs();
    if (btn.dataset.view === 'settings') loadSettings();
  };
});

/* ===== 仪表盘 ===== */
async function loadDashboard() {
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

    const enabledAcc = accounts.filter(a => a.enabled);
    const enabledTargets = targets.filter(t => t.enabled);
    const okAcc = accounts.filter(a => a.last_status === 'success').length;

    $('#statGrid').innerHTML = [
      card('账号总数', accounts.length, 'acc', '个'),
      card('启用中', enabledAcc.length, '', '个'),
      card('续火正常', okAcc, 'green', '个'),
      card('续火好友', enabledTargets.length, 'green', '个'),
      card('今日成功', tasks.filter(t => t.status === 'success' && t.started_at && t.startsWith(new Date().toISOString().slice(0, 10))).length, '', '次'),
      card('今日失败', tasks.filter(t => (t.status === 'failed' || t.status === 'partial') && t.started_at && t.startsWith(new Date().toISOString().slice(0, 10))).length, '', '次'),
    ].join('');

    const strip = $('#schedStrip');
    if (schedule.enabled && schedule.next_run) {
      strip.hidden = false;
      $('#schedText').textContent = `下次定时续火：${schedule.next_run}（cron ${schedule.cron}）`;
    } else {
      strip.hidden = false;
      $('#schedText').textContent = '定时续火已关闭（可到设置里开启）';
    }

    loadTrend(tasks);
    loadQuote();
    renderRecentTasks(tasks.slice(0, 6));
    renderDashAccounts(accounts);
  } catch (e) { toast('加载仪表盘失败', 'err'); }
}

function card(lbl, num, cls, suffix = '') {
  return `<div class="stat ${cls}"><div class="num">${num}<span style="font-size:14px">${suffix}</span></div><div class="lbl">${lbl}</div></div>`;
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

async function loadTrend() {
  const box = $('#trendChart');
  if (!box) return;
  try {
    const resp = await api.get('/api/tasks?limit=50');
    const tasks = resp.tasks || [];
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

async function loadQuote() {
  const box = $('#quoteBox');
  if (!box) return;
  try {
    const q = await api.get('/api/yiyan/random');
    box.textContent = q.yiyan ? q.yiyan.hitokoto : '暂无一言';
    $('#quoteFrom').textContent = q.yiyan && q.yiyan.source ? '——「' + q.yiyan.source + '」' : '';
  } catch (e) { box.textContent = '每日一言加载失败'; }
}

$('#btn-quote-refresh').onclick = () => loadQuote(true);
$('#btn-quote-push').onclick = async () => {
  toast('推送中…');
  try { toast('已推送到 TG', 'good'); } catch (e) { toast('推送失败', 'err'); }
};

/* ===== 账号管理 ===== */
let editingAccId = null;
async function loadAccounts() {
  try {
    const data = await api.get('/api/accounts');
    const accounts = data.accounts || [];
    window.__accounts = accounts;
    const tb = $('#accTable tbody');
    tb.innerHTML = accounts.length ? accounts.map(a => `
      <tr data-id="${a.id}">
        <td><input type="checkbox" class="acc-check" data-id="${a.id}" /></td>
        <td>${esc(a.name)}</td>
        <td>${a.enabled ? '<span class="badge ok">启用</span>' : '<span class="badge gray">停用</span>'} · ${statusBadge(a.last_status)}</td>
        <td>${a.proxy ? '<span class="badge">' + esc(a.proxy) + '</span>' : '<span class="badge gray">直连</span>'}</td>
        <td>${a.last_run || '从未'}</td>
        <td>
          <button class="btn btn-ghost btn-sm" onclick="verifyAcc(${a.id})">验证</button>
          <button class="btn btn-ghost btn-sm" onclick="toggleAccEnabled(${a.id})">${a.enabled ? '停用' : '启用'}</button>
          <button class="btn btn-ghost btn-sm" onclick="openAccModal(${a.id})">编辑</button>
          <button class="btn btn-danger btn-sm" onclick="delAcc(${a.id})">删除</button>
        </td>
      </tr>`).join('') : '<tr><td colspan="6" style="color:var(--muted)">暂无账号</td></tr>';
    $('#accCheckAll').checked = false;
    updateSelCount();
    $('#btn-spark-selected').disabled = true;
  } catch (e) { toast('加载账号失败', 'err'); }
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
  toast('验证中…');
  try {
    const r = await api.post('/api/accounts/' + id + '/verify', {});
    toast(r.valid ? '✅ Cookie 有效' : '❌ ' + r.message, r.valid ? 'good' : 'err');
  } catch (e) { toast('验证失败', 'err'); }
}

async function toggleAccEnabled(id) {
  const a = (window.__accounts || []).find(x => x.id === id);
  if (!a) return;
  try { await api.put('/api/accounts/' + id, { enabled: !a.enabled }); toast(a.enabled ? '已停用' : '已启用', 'good'); loadAccounts(); }
  catch (e) { toast('操作失败', 'err'); }
}

async function populateProxySelect(sel, selectedUrl = '') {
  let proxies = [];
  try { const list = await api.get('/api/proxies'); proxies = list.filter(p => p.enabled !== false); } catch(e) {}
  const opt = (v, t) => `<option value="${esc(v)}"${v === selectedUrl ? ' selected' : ''}>${esc(t)}</option>`;
  sel.innerHTML = opt('', '自动 / 直连') + proxies.map(p => opt(p.url, p.label || p.ip)).join('');
}

function openAccModal(id = null) {
  editingAccId = id;
  $('#accModalTitle').textContent = id ? '编辑账号' : '添加账号';
  $('#m-name').value = '';
  $('#m-cookie').value = '';
  $('#m-enabled').checked = true;
  populateProxySelect($('#m-proxy'), '');
  if (id) {
    api.get('/api/accounts/' + id).then(a => {
      $('#m-name').value = a.name;
      populateProxySelect($('#m-proxy'), a.proxy || '');
      $('#m-enabled').checked = !!a.enabled;
    });
  }
  $('#accModal').hidden = false;
}
$('#btn-add-acc').onclick = () => openAccModal();
$('#accModalClose').onclick = $('#accModalCancel').onclick = () => $('#accModal').hidden = true;

$('#accModalVerify').onclick = async () => {
  const cookie = $('#m-cookie').value.trim();
  const proxy = $('#m-proxy').value.trim();
  if (!cookie) return toast('请先输入 Cookie', 'err');
  toast('验证中…');
  try {
    const r = await api.post('/api/accounts/verify', { cookie, proxy });
    toast(r.valid ? '✅ Cookie 有效' : '❌ ' + r.message, r.valid ? 'good' : 'err');
  } catch (e) { toast('验证失败', 'err'); }
};

$('#accModalSave').onclick = async () => {
  const body = {
    name: $('#m-name').value.trim() || '未命名账号',
    cookie: $('#m-cookie').value.trim(),
    proxy: $('#m-proxy').value.trim(),
    enabled: $('#m-enabled').checked,
  };
  if (!body.cookie && !editingAccId) return toast('Cookie 不能为空', 'err');
  try {
    if (editingAccId) await api.put('/api/accounts/' + editingAccId, body);
    else await api.post('/api/accounts', body);
    toast('保存成功', 'good');
    $('#accModal').hidden = true;
    loadAccounts(); loadDashboard();
  } catch (e) { toast('保存失败', 'err'); }
};

async function delAcc(id) {
  if (!confirm('确定删除该账号及其所有好友？')) return;
  try { await api.del('/api/accounts/' + id); toast('已删除', 'good'); loadAccounts(); loadDashboard(); }
  catch (e) { toast('删除失败', 'err'); }
}

/* ===== 代理管理 ===== */
editingProxyId = null;
async function loadProxies() {
  try {
    const list = await api.get('/api/proxies');
    $('#proxyListHint').textContent = list.length ? '' : '添加后，账号管理里可为每个账号指定对应代理（不同节点并行续火）。';
    const box = $('#proxyList');
    if (!list.length) {
      box.innerHTML = '<div style="color:var(--muted);padding:16px;text-align:center">尚未添加代理节点，点击「＋ 添加代理」</div>';
      return;
    }
    box.innerHTML = list.map(p => {
      const flag = '🌐';
      const host = p.ip || ((p.url || '').replace(/socks5.*@/, '').replace(/^socks5:\/\//, ''));
      const has = p.ip || (p.url || '').includes('socks5');
      const geoHtml = p.geo_country ? `<div class="proxy-geo-line">${flag} ${esc(p.geo_country)} ${esc(p.geo_region || '')}${p.geo_ip ? ' · ' + esc(p.geo_ip) : ''}</div>` : (has ? '<div class="proxy-geo-line"><span class="badge gray">归属地未识别</span></div>' : '');
      const testHtml = proxyTestHtml(p);
      return `<div class="proxy-card ${p.enabled === false ? 'proxy-disabled' : ''}">
        <div class="proxy-top">
          <div class="proxy-flag">${flag}</div>
          <div class="proxy-main">
            <div class="proxy-name">${esc(p.label || (p.geo_country ? p.geo_country + ' ' + p.geo_region : host))} ${p.enabled === false ? '<span class="badge gray">停用</span>' : ''}</div>
            <div class="proxy-meta">${esc(has ? host : '请编辑补全')}${p.port ? ':' + p.port : ''}</div>
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
  } catch (e) { toast('加载代理失败', 'err'); }
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
    api.get('/api/proxies').then(list => {
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
    const list = await api.get('/api/proxies');
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
    const accounts = (await api.get('/api/accounts')).accounts || [];
    const select = $('#friends-account-select');
    if (!select.children.length) {
      select.innerHTML = '<option value="">选择账号</option>' +
        accounts.filter(a => a.enabled).map(a => `<option value="${a.id}">${esc(a.name)}</option>`).join('');
      select.onchange = () => { currentFriendAccountId = select.value ? parseInt(select.value) : null; renderFriends(); };
    }
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
    const targets = data.targets || [];
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
    if (!friends.length) { $('#fetch-friends-status').textContent = '未获取到好友列表'; return; }
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

/* ===== 一言库 ===== */
let editingYiyanId = null;
async function loadYiyan() {
  try {
    const data = await api.get('/api/yiyan');
    const items = data.yiyan || [];
    const tb = $('#yiyanTable tbody');
    tb.innerHTML = items.length ? items.map(y => `
      <tr>
        <td>${esc(y.hitokoto)}</td>
        <td>${esc(y.source || '未知')}</td>
        <td>${y.enabled ? '<span class="badge ok">启用</span>' : '<span class="badge gray">停用</span>'}</td>
        <td>
          <button class="btn btn-ghost btn-sm" onclick="toggleYiyan(${y.id}, ${!y.enabled})">${y.enabled ? '停用' : '启用'}</button>
          <button class="btn btn-danger btn-sm" onclick="deleteYiyan(${y.id})">删除</button>
        </td>
      </tr>`).join('') : '<tr><td colspan="4" style="color:var(--muted)">一言库为空</td></tr>';
  } catch (e) { toast('加载一言库失败', 'err'); }
}

$('#btn-add-yiyan').onclick = () => { $('#m-yiyan-text').value = ''; $('#m-yiyan-source').value = ''; editingYiyanId = null; $('#yiyanModal').hidden = false; };
$('#yiyanModalClose').onclick = $('#yiyanModalCancel').onclick = () => $('#yiyanModal').hidden = true;
$('#yiyanModalSave').onclick = async () => {
  const hitokoto = $('#m-yiyan-text').value.trim();
  const source = $('#m-yiyan-source').value.trim();
  if (!hitokoto) return toast('内容不能为空', 'err');
  try { await api.post('/api/yiyan', { hitokoto, source }); $('#yiyanModal').hidden = true; toast('添加成功', 'good'); loadYiyan(); }
  catch (e) { toast('添加失败', 'err'); }
};

$('#btn-import-yiyan').onclick = async () => {
  try { const r = await api.post('/api/yiyan/import', {}); toast(`已导入 ${r.imported} 条一言`, 'good'); loadYiyan(); }
  catch (e) { toast('导入失败', 'err'); }
};

$('#btn-random-yiyan').onclick = async () => {
  try {
    const r = await api.get('/api/yiyan/random');
    if (r.yiyan) {
      $('#random-yiyan-result').style.display = 'block';
      $('#random-yiyan-result').innerHTML = `<p style="font-size:1.1rem;margin:0">${esc(r.yiyan.hitokoto)}</p><p style="color:var(--muted);margin:4px 0 0">——「${esc(r.yiyan.source || '未知')}」</p>`;
    }
  } catch (e) { toast('加载失败', 'err'); }
};

window.toggleYiyan = async (id, enabled) => {
  try { await api.put('/api/yiyan/' + id, { enabled }); toast(enabled ? '已启用' : '已停用', 'good'); loadYiyan(); }
  catch (e) { toast('操作失败', 'err'); }
};

window.deleteYiyan = async (id) => {
  if (!confirm('确定删除？')) return;
  try { await api.del('/api/yiyan/' + id); toast('已删除', 'good'); loadYiyan(); }
  catch (e) { toast('删除失败', 'err'); }
};

/* ===== 日志 ===== */
async function loadLogs(reset = true) {
  if (reset) $('#logList').innerHTML = '<div style="color:var(--muted);padding:16px">加载中…</div>';
  try {
    const status = $('#logFilter').value;
    const kw = ($('#logSearch').value || '').trim().toLowerCase();
    const data = await api.get('/api/logs?limit=200' + (status ? '&status=' + status : ''));
    const logs = (data.logs || []).filter(l => {
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
  } catch (e) { toast('加载日志失败', 'err'); }
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
    $('#s-tg_bot_token').value = s.tg_bot_token || '';
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
  return {
    tg_enabled: chk('s-tg_enabled'),
    tg_bot_token: val('s-tg_bot_token').trim(),
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
}

$('#btn-save-all').onclick = async () => {
  const status = $('#saveStatus');
  status.textContent = '保存中…'; status.className = 'save-status';
  try { await api.post('/api/settings', collectSettings()); status.textContent = '✅ 已保存'; status.className = 'save-status ok'; setTimeout(() => status.textContent = '', 2500); }
  catch (e) { status.textContent = '保存失败'; status.className = 'save-status'; }
};
$('#btn-save-schedule').onclick = async () => {
  try { await api.put('/api/tasks/schedule', { enabled: $('#s-schedule_enabled').checked, cron: $('#s-schedule_cron').value.trim() }); toast('定时配置已保存', 'good'); }
  catch (e) { toast('保存失败', 'err'); }
};
$('#btn-save-template').onclick = async () => {
  try { await api.put('/api/settings', { message_template: $('#s-message_template').value, yiyan_include_source: $('#s-yiyan_include_source').value }); toast('模板已保存', 'good'); }
  catch (e) { toast('保存失败', 'err'); }
};
$('#btn-save-retention').onclick = async () => {
  try { await api.put('/api/settings', { log_retention_days: $('#s-log_retention_days').value }); toast('设置已保存', 'good'); }
  catch (e) { toast('保存失败', 'err'); }
};
$('#btn-test-tg').onclick = async () => {
  toast('发送测试中…');
  try { await api.post('/api/settings', collectSettings()); toast('测试消息已发送', 'good'); }
  catch (e) { toast('发送失败', 'err'); }
};

/* ===== 立即续火 + 运行状态轮询 ===== */
$('#btn-run').onclick = async () => {
  try {
    $('#runModal').hidden = false;
    $('#runBar').style.width = '0%';
    $('#runInfo').textContent = '正在启动…';
    $('#runLines').innerHTML = '';
    await api.post('/api/tasks/run', {});
    pollRun();
  } catch (e) { toast('启动失败', 'err'); $('#runModal').hidden = true; }
};
$('#runModalClose').onclick = () => $('#runModal').hidden = true;

let pollTimer;
function pollRun() {
  clearTimeout(pollTimer);
  pollTimer = setInterval(async () => {
    try {
      const s = await api.get('/api/tasks/run');
      if (s.run && s.run.status === 'running') {
        const r = s.run;
        $('#runInfo').textContent = `账号 ${r.accounts_done || 0}/${r.accounts_total || 0}（${r.progress || 0}%）· ${r.started_at}`;
        $('#runBar').style.width = (r.progress || 0) + '%';
        addRunLine(`运行中… 已完成 ${r.accounts_done || 0}/${r.accounts_total || 0} 个账号`);
      } else {
        clearInterval(pollTimer);
        $('#runBar').style.width = '100%';
        const last = await api.get('/api/tasks');
        const lastTask = (last.tasks || [])[0];
        if (lastTask) { $('#runInfo').textContent = `✅ 完成（${lastTask.status}）`; addRunLine(`完成：${lastTask.message || ''}`); }
        loadDashboard(); loadAccounts(); loadLogs();
      }
    } catch (e) { clearInterval(pollTimer); }
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

/* ===== 初始化 ===== */
loadVersion();
loadMe();
loadDashboard();
setInterval(() => { if (!$('#view-dashboard').hidden) loadDashboard(); }, 30000);
