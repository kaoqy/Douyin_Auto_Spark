// 抖音续火花管理面板 - 前端逻辑
const API = '';

// ==================== 工具函数 ====================

function $(sel) { return document.querySelector(sel); }
function $$(sel) { return document.querySelectorAll(sel); }

function showToast(msg, type = 'info') {
    const toast = $('#toast');
    toast.textContent = msg;
    toast.className = `toast toast-${type} show`;
    setTimeout(() => toast.classList.remove('show'), 3000);
}

async function api(path, opts = {}) {
    const res = await fetch(API + path, {
        headers: { 'Content-Type': 'application/json' },
        ...opts,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
        throw new Error(data.detail || `请求失败 (${res.status})`);
    }
    return data;
}

function escapeHtml(str) {
    if (!str) return '';
    return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

// ==================== 认证 ====================

async function checkAuth() {
    try {
        const data = await api('/api/auth/me');
        $('#user-info').textContent = `👤 ${data.user.username}`;
        return true;
    } catch {
        return false;
    }
}

async function logout() {
    await api('/api/auth/logout', { method: 'POST' });
    location.reload();
}

function showLogin() {
    document.body.innerHTML = `
        <div style="display:flex;justify-content:center;align-items:center;min-height:100vh;background:#f5f5f5;">
            <div style="background:white;padding:2rem;border-radius:8px;box-shadow:0 4px 12px rgba(0,0,0,0.1);width:360px;">
                <h2 style="text-align:center;margin-bottom:1.5rem;">🔥 抖音续火花</h2>
                <div class="form-group">
                    <label>用户名</label>
                    <input type="text" id="login-username" placeholder="请输入用户名">
                </div>
                <div class="form-group">
                    <label>密码</label>
                    <input type="password" id="login-password" placeholder="请输入密码">
                </div>
                <button class="btn btn-primary" style="width:100%;" onclick="doLogin()">登录</button>
            </div>
        </div>
    `;
}

async function doLogin() {
    const username = $('#login-username').value;
    const password = $('#login-password').value;
    try {
        await api('/api/auth/login', {
            method: 'POST',
            body: JSON.stringify({ username, password }),
        });
        location.reload();
    } catch (e) {
        showToast(e.message, 'error');
    }
}

// ==================== 导航 ====================

function initNav() {
    $$('.nav-item').forEach(item => {
        item.addEventListener('click', e => {
            e.preventDefault();
            const page = item.dataset.page;
            $$('.nav-item').forEach(n => n.classList.remove('active'));
            item.classList.add('active');
            $$('.page').forEach(p => p.classList.remove('active'));
            $(`#page-${page}`).classList.add('active');
            loadPage(page);
        });
    });
}

function loadPage(page) {
    switch (page) {
        case 'dashboard': loadDashboard(); break;
        case 'accounts': loadAccounts(); break;
        case 'targets': loadTargets(); break;
        case 'yiyan': loadYiyan(); break;
        case 'logs': loadLogs(); break;
        case 'settings': loadSettings(); break;
    }
}

// ==================== 仪表盘 ====================

async function loadDashboard() {
    try {
        const [accountsRes, targetsRes, tasksRes] = await Promise.all([
            api('/api/accounts'),
            api('/api/targets'),
            api('/api/tasks'),
        ]);
        $('#stat-accounts').textContent = accountsRes.accounts.length;
        $('#stat-targets').textContent = targetsRes.targets.length;

        // 统计今日成功/失败
        const today = new Date().toISOString().slice(0, 10);
        let success = 0, fail = 0;
        for (const task of tasksRes.tasks) {
            if (task.started_at && task.started_at.startsWith(today)) {
                if (task.status === 'success') success++;
                else if (task.status === 'failed' || task.status === 'partial') fail++;
            }
        }
        $('#stat-success').textContent = success;
        $('#stat-fail').textContent = fail;

        // 下次运行
        const schedule = await api('/api/tasks/schedule');
        if (schedule.enabled && schedule.next_run) {
            $('#next-run').innerHTML = `<strong>${schedule.next_run}</strong>（${schedule.cron}）`;
        } else {
            $('#next-run').textContent = '定时任务未启用';
        }

        // 最近任务
        const tasksHtml = tasksRes.tasks.slice(0, 5).map(t => `
            <div class="log-item">
                <span>${escapeHtml(t.trigger_type)} - ${escapeHtml(t.status)}</span>
                <span class="log-time">${t.started_at || ''}</span>
            </div>
        `).join('') || '<p style="color:#888;">暂无任务记录</p>';
        $('#recent-tasks').innerHTML = tasksHtml;

    } catch (e) {
        showToast(e.message, 'error');
    }
}

// ==================== 账号管理 ====================

async function loadAccounts() {
    try {
        const data = await api('/api/accounts');
        const html = data.accounts.map(acc => `
            <tr>
                <td><strong>${escapeHtml(acc.name)}</strong></td>
                <td>${acc.proxy || '直连'}</td>
                <td><span class="badge ${acc.enabled ? 'badge-success' : 'badge-pending'}">${acc.enabled ? '启用' : '停用'}</span></td>
                <td>${acc.last_run || '-'}</td>
                <td>${acc.last_status || '-'}</td>
                <td>
                    <button class="btn btn-sm" onclick="toggleAccount(${acc.id}, ${!acc.enabled})">${acc.enabled ? '停用' : '启用'}</button>
                    <button class="btn btn-sm" onclick="editAccount(${acc.id})">编辑</button>
                    <button class="btn btn-sm btn-danger" onclick="deleteAccount(${acc.id})">删除</button>
                </td>
            </tr>
        `).join('');
        $('#accounts-list').innerHTML = `
            <table>
                <thead><tr><th>名称</th><th>代理</th><th>状态</th><th>最近运行</th><th>最近状态</th><th>操作</th></tr></thead>
                <tbody>${html || '<tr><td colspan="6" style="text-align:center;color:#888;">暂无账号</td></tr>'}</tbody>
            </table>
        `;
    } catch (e) {
        showToast(e.message, 'error');
    }
}

function showAddAccount() {
    $('#modal-body').innerHTML = `
        <h3>添加账号</h3>
        <div class="form-group">
            <label>账号名称</label>
            <input type="text" id="account-name" placeholder="如：我的抖音">
        </div>
        <div class="form-group">
            <label>Cookie JSON</label>
            <textarea id="account-cookie" rows="4" placeholder="从 Cookie-Editor 导出的完整 JSON 数组"></textarea>
        </div>
        <div class="form-group">
            <label>SOCKS5 代理（可选）</label>
            <input type="text" id="account-proxy" placeholder="socks5://user:pass@host:port">
        </div>
        <button class="btn btn-primary" onclick="addAccount()">保存</button>
    `;
    $('#modal').classList.add('active');
}

async function addAccount() {
    const name = $('#account-name').value.trim();
    const cookie = $('#account-cookie').value.trim();
    const proxy = $('#account-proxy').value.trim();
    if (!name || !cookie) return showToast('名称和 Cookie 必填', 'error');
    try {
        await api('/api/accounts', { method: 'POST', body: JSON.stringify({ name, cookie, proxy }) });
        closeModal();
        showToast('账号添加成功', 'success');
        loadAccounts();
    } catch (e) {
        showToast(e.message, 'error');
    }
}

async function toggleAccount(id, enabled) {
    try {
        await api(`/api/accounts/${id}`, { method: 'PUT', body: JSON.stringify({ enabled }) });
        showToast('状态已更新', 'success');
        loadAccounts();
    } catch (e) {
        showToast(e.message, 'error');
    }
}

function editAccount(id) {
    showToast('编辑功能：重新添加同名账号或先删除再添加', 'info');
}

async function deleteAccount(id) {
    if (!confirm('确定要删除该账号及其所有好友吗？')) return;
    try {
        await api(`/api/accounts/${id}`, { method: 'DELETE' });
        showToast('删除成功', 'success');
        loadAccounts();
    } catch (e) {
        showToast(e.message, 'error');
    }
}

// ==================== 好友管理 ====================

async function loadTargets() {
    try {
        const accountId = $('#targets-account-filter').value;
        const url = accountId ? `/api/targets?account_id=${accountId}` : '/api/targets';
        const data = await api(url);

        // 加载账号到筛选下拉
        if (!$('#targets-account-filter').children.length) {
            const accounts = await api('/api/accounts');
            $('#targets-account-filter').innerHTML = '<option value="">全部账号</option>' +
                accounts.accounts.map(a => `<option value="${a.id}">${escapeHtml(a.name)}</option>`).join('');
            if (accountId) $('#targets-account-filter').value = accountId;
        }

        const html = data.targets.map(t => `
            <tr>
                <td><strong>${escapeHtml(t.name)}</strong></td>
                <td>${t.account_id}</td>
                <td><span class="badge ${t.enabled ? 'badge-success' : 'badge-pending'}">${t.enabled ? '启用' : '停用'}</span></td>
                <td>${t.last_run || '-'}</td>
                <td>
                    <button class="btn btn-sm" onclick="toggleTarget(${t.id}, ${!t.enabled})">${t.enabled ? '停用' : '启用'}</button>
                    <button class="btn btn-sm btn-danger" onclick="deleteTarget(${t.id})">删除</button>
                </td>
            </tr>
        `).join('');

        $('#targets-list').innerHTML = `
            <table>
                <thead><tr><th>好友名称</th><th>账号 ID</th><th>状态</th><th>最近运行</th><th>操作</th></tr></thead>
                <tbody>${html || '<tr><td colspan="5" style="text-align:center;color:#888;">暂无好友</td></tr>'}</tbody>
            </table>
        `;
    } catch (e) {
        showToast(e.message, 'error');
    }
}

function showAddTarget() {
    $('#modal-body').innerHTML = `
        <h3>添加好友</h3>
        <div class="form-group">
            <label>所属账号</label>
            <select id="target-account"></select>
        </div>
        <div class="form-group">
            <label>好友名称</label>
            <input type="text" id="target-name" placeholder="建议用抖音备注名">
        </div>
        <button class="btn btn-primary" onclick="addTarget()">保存</button>
    `;
    api('/api/accounts').then(data => {
        $('#target-account').innerHTML = data.accounts
            .filter(a => a.enabled)
            .map(a => `<option value="${a.id}">${escapeHtml(a.name)}</option>`).join('');
    });
    $('#modal').classList.add('active');
}

async function addTarget() {
    const account_id = parseInt($('#target-account').value);
    const name = $('#target-name').value.trim();
    if (!account_id || !name) return showToast('请选择账号并填写名称', 'error');
    try {
        await api('/api/targets', { method: 'POST', body: JSON.stringify({ account_id, name }) });
        closeModal();
        showToast('好友添加成功', 'success');
        loadTargets();
    } catch (e) {
        showToast(e.message, 'error');
    }
}

async function toggleTarget(id, enabled) {
    try {
        await api(`/api/targets/${id}`, { method: 'PUT', body: JSON.stringify({ enabled }) });
        showToast('状态已更新', 'success');
        loadTargets();
    } catch (e) {
        showToast(e.message, 'error');
    }
}

async function deleteTarget(id) {
    if (!confirm('确定要删除该好友吗？')) return;
    try {
        await api(`/api/targets/${id}`, { method: 'DELETE' });
        showToast('删除成功', 'success');
        loadTargets();
    } catch (e) {
        showToast(e.message, 'error');
    }
}

// ==================== 一言库 ====================

async function loadYiyan() {
    try {
        const data = await api('/api/yiyan');
        const html = data.yiyan.map(y => `
            <div class="yiyan-item">
                <div class="yiyan-text">${escapeHtml(y.hitokoto)}</div>
                <div class="yiyan-source">——「${escapeHtml(y.source || '未知')}」</div>
                <div style="margin-top:0.5rem;">
                    <span class="badge ${y.enabled ? 'badge-success' : 'badge-pending'}">${y.enabled ? '启用' : '停用'}</span>
                    <button class="btn btn-sm" onclick="toggleYiyan(${y.id}, ${!y.enabled})">${y.enabled ? '停用' : '启用'}</button>
                    <button class="btn btn-sm btn-danger" onclick="deleteYiyan(${y.id})">删除</button>
                </div>
            </div>
        `).join('');
        $('#yiyan-list').innerHTML = html || '<p style="color:#888;">一言库为空</p>';
    } catch (e) {
        showToast(e.message, 'error');
    }
}

function showAddYiyan() {
    $('#modal-body').innerHTML = `
        <h3>添加一言</h3>
        <div class="form-group">
            <label>内容</label>
            <textarea id="yiyan-text" rows="3" placeholder="输入一言内容"></textarea>
        </div>
        <div class="form-group">
            <label>出处</label>
            <input type="text" id="yiyan-source" placeholder="如：火影忍者">
        </div>
        <button class="btn btn-primary" onclick="addYiyan()">保存</button>
    `;
    $('#modal').classList.add('active');
}

async function addYiyan() {
    const hitokoto = $('#yiyan-text').value.trim();
    const source = $('#yiyan-source').value.trim();
    if (!hitokoto) return showToast('内容不能为空', 'error');
    try {
        await api('/api/yiyan', { method: 'POST', body: JSON.stringify({ hitokoto, source }) });
        closeModal();
        showToast('添加成功', 'success');
        loadYiyan();
    } catch (e) {
        showToast(e.message, 'error');
    }
}

async function toggleYiyan(id, enabled) {
    try {
        await api(`/api/yiyan/${id}`, { method: 'PUT', body: JSON.stringify({ enabled }) });
        loadYiyan();
    } catch (e) {
        showToast(e.message, 'error');
    }
}

async function deleteYiyan(id) {
    if (!confirm('确定删除？')) return;
    try {
        await api(`/api/yiyan/${id}`, { method: 'DELETE' });
        loadYiyan();
    } catch (e) {
        showToast(e.message, 'error');
    }
}

async function importDefaultYiyan() {
    try {
        const data = await api('/api/yiyan/import', { method: 'POST' });
        showToast(`已导入 ${data.imported} 条一言`, 'success');
        loadYiyan();
    } catch (e) {
        showToast(e.message, 'error');
    }
}

async function pickRandomYiyan() {
    try {
        const data = await api('/api/yiyan/random');
        if (data.yiyan) {
            $('#random-yiyan-result').style.display = 'block';
            $('#random-yiyan-result').innerHTML = `
                <p style="font-size:1.1rem;">${escapeHtml(data.yiyan.hitokoto)}</p>
                <p style="color:#888;">——「${escapeHtml(data.yiyan.source || '未知')}」</p>
            `;
        }
    } catch (e) {
        showToast(e.message, 'error');
    }
}

// ==================== 日志 ====================

async function loadLogs() {
    try {
        const status = $('#logs-status-filter').value;
        const url = status ? `/api/logs?status=${status}` : '/api/logs';
        const data = await api(url);
        const html = data.logs.map(l => `
            <div class="log-item">
                <div>
                    <span class="badge badge-${l.status === 'success' ? 'success' : l.status === 'failed' ? 'failed' : 'partial'}">${l.status}</span>
                    <strong>${escapeHtml(l.account_name || '')}</strong>
                    ${l.target_name ? `→ <strong>${escapeHtml(l.target_name)}</strong>` : ''}
                    <span style="color:#888;margin-left:0.5rem;">${escapeHtml(l.message || '')}</span>
                </div>
                <span class="log-time">${l.created_at}</span>
            </div>
        `).join('');
        $('#logs-list').innerHTML = html || '<p style="color:#888;">暂无日志</p>';
    } catch (e) {
        showToast(e.message, 'error');
    }
}

async function clearLogs() {
    if (!confirm('确定要清空所有日志吗？')) return;
    try {
        await api('/api/logs', { method: 'DELETE' });
        showToast('日志已清空', 'success');
        loadLogs();
    } catch (e) {
        showToast(e.message, 'error');
    }
}

// ==================== 设置 ====================

async function loadSettings() {
    try {
        const data = await api('/api/settings');
        const s = data.settings;
        $('#set-schedule-enabled').checked = (s.schedule_enabled || '1') === '1';
        $('#set-schedule-cron').value = s.schedule_cron || '0 8 * * *';
        $('#set-message-template').value = s.message_template || '';
        $('#set-log-retention').value = s.log_retention_days || '30';
    } catch (e) {
        showToast(e.message, 'error');
    }
}

async function saveSchedule() {
    try {
        await api('/api/tasks/schedule', {
            method: 'PUT',
            body: JSON.stringify({
                enabled: $('#set-schedule-enabled').checked,
                cron: $('#set-schedule-cron').value,
            }),
        });
        showToast('定时设置已保存', 'success');
    } catch (e) {
        showToast(e.message, 'error');
    }
}

async function saveMessageTemplate() {
    try {
        await api('/api/settings', {
            method: 'PUT',
            body: JSON.stringify({ message_template: $('#set-message-template').value }),
        });
        showToast('模板已保存', 'success');
    } catch (e) {
        showToast(e.message, 'error');
    }
}

async function saveLogRetention() {
    try {
        await api('/api/settings', {
            method: 'PUT',
            body: JSON.stringify({ log_retention_days: $('#set-log-retention').value }),
        });
        showToast('设置已保存', 'success');
    } catch (e) {
        showToast(e.message, 'error');
    }
}

// ==================== 模态框 ====================

function closeModal() {
    $('#modal').classList.remove('active');
}

// ==================== 修改密码 ====================

function changePassword() {
    $('#modal-body').innerHTML = `
        <h3>修改密码</h3>
        <div class="form-group">
            <label>原密码</label>
            <input type="password" id="old-password">
        </div>
        <div class="form-group">
            <label>新密码</label>
            <input type="password" id="new-password" placeholder="至少 6 位">
        </div>
        <button class="btn btn-primary" onclick="doChangePassword()">确认修改</button>
    `;
    $('#modal').classList.add('active');
}

async function doChangePassword() {
    try {
        await api('/api/auth/change-password', {
            method: 'POST',
            body: JSON.stringify({
                old_password: $('#old-password').value,
                new_password: $('#new-password').value,
            }),
        });
        closeModal();
        showToast('密码修改成功，请重新登录', 'success');
        setTimeout(() => location.reload(), 1500);
    } catch (e) {
        showToast(e.message, 'error');
    }
}

// ==================== 初始化 ====================

async function init() {
    // 检查是否需要初始化
    const needsInit = await api('/api/auth/needs-init');
    if (needsInit.needs_init) {
        document.body.innerHTML = `
            <div style="display:flex;justify-content:center;align-items:center;min-height:100vh;background:#f5f5f5;">
                <div style="background:white;padding:2rem;border-radius:8px;box-shadow:0 4px 12px rgba(0,0,0,0.1);width:360px;">
                    <h2 style="text-align:center;margin-bottom:1.5rem;">🔥 抖音续火花</h2>
                    <p style="text-align:center;color:#888;margin-bottom:1.5rem;">首次使用，请创建管理员账号</p>
                    <div class="form-group">
                        <label>用户名</label>
                        <input type="text" id="init-username" value="admin">
                    </div>
                    <div class="form-group">
                        <label>密码</label>
                        <input type="password" id="init-password" placeholder="至少 6 位">
                    </div>
                    <button class="btn btn-primary" style="width:100%;" onclick="doInit()">创建管理员</button>
                </div>
            </div>
        `;
        return;
    }

    const authed = await checkAuth();
    if (!authed) {
        showLogin();
        return;
    }

    initNav();
    loadDashboard();
}

async function doInit() {
    const username = $('#init-username').value.trim();
    const password = $('#init-password').value;
    if (!username || password.length < 6) return showToast('请填写完整（密码至少 6 位）', 'error');
    try {
        await api('/api/auth/init', { method: 'POST', body: JSON.stringify({ username, password }) });
        location.reload();
    } catch (e) {
        showToast(e.message, 'error');
    }
}

// 点击模态框外部关闭
$('#modal').addEventListener('click', e => {
    if (e.target === $('#modal')) closeModal();
});

// 启动
init();
