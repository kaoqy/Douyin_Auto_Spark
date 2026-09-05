const fs = require('fs');
const path = require('path');
const os = require('os');
const { execSync } = require('child_process');

let JSDOM;
try {
  ({ JSDOM } = require('jsdom'));
} catch {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'das-jsdom-'));
  execSync(`npm install jsdom --prefix ${JSON.stringify(tmp)}`, { stdio: 'inherit' });
  process.env.NODE_PATH = path.join(tmp, 'node_modules');
  require('module').Module._initPaths();
  ({ JSDOM } = require('jsdom'));
}

const root = path.join(__dirname, '..');
const html = fs.readFileSync(path.join(root, 'app/static/index.html'), 'utf8');
const script = fs.readFileSync(path.join(root, 'app/static/app.js'), 'utf8');
let failures = 0;

function check(name, condition) {
  console.log(`${condition ? 'PASS' : 'FAIL'} ${name}`);
  if (!condition) failures += 1;
}

function response(body = {}, status = 200) {
  return Promise.resolve({
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(body),
  });
}

const routes = {
  '/api/health': { version: '2.0.0', time: '2026-09-05 14:00:00' },
  '/api/auth/me': { user: { username: 'admin' } },
  '/api/stats': {
    accounts: { total: 2, enabled: 1 },
    targets: { total: 3, enabled: 2 },
    runs: { total: 8, success: 6, partial: 1, failed: 1, success_rate: '75%' },
    messages: { total: 10, ok: 8, fail: 2 },
    active_accounts: 1,
  },
  '/api/tasks/schedule': { enabled: true, cron: '0 8 * * *', next_run: '2026-09-06 08:00:00' },
  '/api/tasks': { tasks: [{ task_id: 'task-1', trigger_type: 'manual', status: 'success', started_at: '2026-09-05 10:00:00', finished_at: '2026-09-05 10:01:00' }] },
  '/api/accounts': { accounts: [{ id: 1, name: '<账号A>', enabled: true, proxy: 'socks5://user:secret@1.2.3.4:1080', last_status: 'success', last_run: '2026-09-05 10:00:00', last_message: '续火成功' }] },
  '/api/proxies': [{ id: 1, label: '香港节点', ip: '1.2.3.4', port: 1080, url: 'socks5://user:secret@1.2.3.4:1080', geo_country: '中国', geo_region: '香港', geo_country_code: 'CN', enabled: true }],
  '/api/targets': { targets: [{ id: 1, account_id: 1, name: '好友A', enabled: true, last_run: '2026-09-05 10:00:00' }] },
  '/api/logs': { logs: [{ id: 1, account_name: '账号A', target_name: '好友A', status: 'success', message: '已发送', created_at: '2026-09-05 10:00:00' }] },
  '/api/settings': { settings: { tg_bot_token: 'secret-token', tg_enabled: '1', schedule_enabled: '1', schedule_cron: '0 8 * * *' } },
  '/api/yiyan/random': { yiyan: { hitokoto: '今天也要加油', source: '测试' } },
};

function mockFetch(url) {
  const parsed = new URL(url, 'http://localhost');
  const key = parsed.pathname;
  if (key === '/api/targets') return response(routes['/api/targets']);
  if (key === '/api/logs') return response(routes['/api/logs']);
  if (Object.prototype.hasOwnProperty.call(routes, key)) return response(routes[key]);
  return response({});
}

(async () => {
  const dom = new JSDOM(html, { runScripts: 'outside-only', url: 'http://localhost/' });
  const { window } = dom;
  window.fetch = mockFetch;
  window.confirm = () => true;
  window.setInterval = () => 1;
  window.clearInterval = () => {};
  window.scrollTo = () => {};
  window.eval(script);
  await new Promise(resolve => setTimeout(resolve, 300));

  const d = window.document;
  check('页面标题正确', d.title.includes('抖音续火花'));
  check('六个导航入口存在', d.querySelectorAll('.nav-item').length === 6);
  check('非��活动页面初始隐藏', [...d.querySelectorAll('.view')].filter(v => v.id !== 'view-dashboard').every(v => v.hidden));
  check('所有模态框初始隐藏', [...d.querySelectorAll('.modal-mask')].every(v => v.hidden));
  check('仪表盘渲染八张统计卡', d.querySelectorAll('#statGrid .stat').length === 8);
  check('每日一言正常渲染', d.querySelector('#quoteBox').textContent.includes('今天也要加油'));
  check('定时提示正常渲染', d.querySelector('#schedText').textContent.includes('2026-09-06'));

  d.querySelector('[data-view="accounts"]').click();
  await new Promise(resolve => setTimeout(resolve, 80));
  const accountText = d.querySelector('#accTable').textContent;
  check('账号页面可以切换', !d.querySelector('#view-accounts').hidden);
  check('账号名称按文本转义', d.querySelector('#accTable').innerHTML.includes('&lt;账号A&gt;'));
  check('账号列表不泄露代理凭据', !accountText.includes('secret') && !accountText.includes('1.2.3.4'));

  d.querySelector('#btn-add-acc').click();
  check('添加账号弹窗可打开', !d.querySelector('#accModal').hidden);
  d.querySelector('#accModalCancel').click();
  check('账号弹窗可关闭', d.querySelector('#accModal').hidden);

  d.querySelector('[data-view="proxies"]').click();
  await new Promise(resolve => setTimeout(resolve, 80));
  const proxyText = d.querySelector('#proxyList').textContent;
  check('代理卡片正常渲染', d.querySelectorAll('#proxyList .proxy-card').length === 1);
  check('代理页不泄露密码和完整链接', !proxyText.includes('secret') && !proxyText.includes('socks5://'));

  d.querySelector('[data-view="settings"]').click();
  await new Promise(resolve => setTimeout(resolve, 80));
  check('暗色主题选项存在', !!d.querySelector('#theme option[value="dark"]'));
  check('TG Token 使用密码输入框', d.querySelector('#s-tg_bot_token').type === 'password');
  check('后端返�回的 TG Token 不回填到页面', d.querySelector('#s-tg_bot_token').value === '');
  check('设置页保留 Telegram、定时、模板和安全策略', ['s-tg_enabled', 's-schedule_cron', 's-message_template', 's-anti_ban_enabled'].every(id => d.getElementById(id)));

  d.querySelector('[data-view="friends"]').click();
  await new Promise(resolve => setTimeout(resolve, 80));
  check('好友管理入口可用', !d.querySelector('#view-friends').hidden);

  d.querySelector('[data-view="logs"]').click();
  await new Promise(resolve => setTimeout(resolve, 80));
  check('日志列表正常渲染', d.querySelectorAll('#logList .log-simple').length === 1);

  if (failures) {
    console.error(`\n${failures} frontend checks failed`);
    process.exit(1);
  }
  console.log('\nAll frontend render checks passed');
})();
