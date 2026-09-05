// 抖音续火花管理面板 - Cookie 编辑器逻辑测试
// 通过 jsdom 仅加载 Cookie 编辑器部分代码，避免触发 app.js 顶层的 setInterval/fetch。
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { JSDOM } = require('jsdom');

const HTML = fs.readFileSync(
  path.join(__dirname, '..', 'app', 'static', 'index.html'),
  'utf8'
);
const APP_JS = fs.readFileSync(
  path.join(__dirname, '..', 'app', 'static', 'app.js'),
  'utf8'
);

function setup() {
  const dom = new JSDOM(HTML, { runScripts: 'outside-only', pretendToBeVisual: true });
  const { window } = dom;
  // 注入 datalist
  const dl = window.document.createElement('datalist');
  dl.id = 'cookie-domain-list';
  window.document.body.appendChild(dl);
  // 注入 mock 工具与 Cookie 编辑器相关代码
  const prelude = `
    const $ = (s, r = document) => r.querySelector(s);
    const $$ = (s, r = document) => [...r.querySelectorAll(s)];
    function esc(s) { return String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])); }
    function toast() {}
  `;
  // 截取 Cookie 编辑器相关代码：openAccModal 之后到最后的部分
  const idx = APP_JS.indexOf('/* ===== Cookie 编辑器 ===== */');
  let endIdx = APP_JS.indexOf('/* ===== 代理管理 ===== */');
  if (endIdx < 0) endIdx = APP_JS.length;
  const cookieJs = APP_JS.slice(idx, endIdx);
  window.eval(prelude + '\n' + cookieJs);
  return { dom, window };
}

test('Cookie 编辑器：JSON 数组能解析并填到编辑字段', () => {
  const { window } = setup();
  getById(window, 'm-cookie').value = JSON.stringify([
    { name: 'sessionid', value: 'abc', domain: '.douyin.com' },
    { name: 'uid_tt', value: '12345', domain: '.douyin.com' },
  ]);
  window.document.getElementById('btn-cookie-parse').click();
  const rows = window.document.querySelectorAll('#cookieEditorRows .cookie-row');
  assert.equal(rows.length, 2);
  const json = JSON.parse(getById(window, 'm-cookie-json').value);
  assert.equal(json.length, 2);
  assert.equal(json[0].name, 'sessionid');
});

test('Cookie 编辑器：Netscape 字符串解析', () => {
  const { window } = setup();
  getById(window, 'm-cookie').value = 'sessionid=abc; uid_tt=12345; sid_tt=xyz';
  window.document.getElementById('btn-cookie-parse').click();
  const rows = window.document.querySelectorAll('#cookieEditorRows .cookie-row');
  assert.equal(rows.length, 3);
  assert.equal(rows[0].querySelector('.cookie-name').value, 'sessionid');
  assert.equal(rows[0].querySelector('.cookie-value').value, 'abc');
});

test('Cookie 编辑器：Set-Cookie 完整格式解析', () => {
  const { window } = setup();
  const text = [
    'sessionid=abc; Domain=.douyin.com; Path=/; Expires=Wed, 21 Oct 2099 07:28:00 GMT; HttpOnly; Secure; SameSite=None',
    'sid_tt=xyz; Domain=.douyin.com; Path=/; SameSite=Lax',
  ].join('\n');
  getById(window, 'm-cookie').value = text;
  window.document.getElementById('btn-cookie-parse').click();
  const json = JSON.parse(getById(window, 'm-cookie-json').value);
  assert.equal(json.length, 2);
  assert.equal(json[0].name, 'sessionid');
  assert.equal(json[0].domain, '.douyin.com');
  assert.equal(json[0].secure, true);
  assert.equal(json[0].httpOnly, true);
  assert.equal(json[0].sameSite, 'None');
  assert.ok(json[0].expires > 0);
  assert.equal(json[1].sameSite, 'Lax');
});

test('Cookie 编辑器：编辑字段后 JSON 实时同步', () => {
  const { window } = setup();
  getById(window, 'm-cookie').value = 'sessionid=abc';
  window.document.getElementById('btn-cookie-parse').click();
  const valueInput = window.document.querySelector('.cookie-row .cookie-value');
  valueInput.value = 'NEW_VALUE';
  valueInput.dispatchEvent(new window.Event('input', { bubbles: true }));
  const json = JSON.parse(getById(window, 'm-cookie-json').value);
  assert.equal(json[0].value, 'NEW_VALUE');
});

test('Cookie 编辑器：去重按钮移除重复字段（保留首次）', () => {
  const { window } = setup();
  getById(window, 'm-cookie').value = 'sessionid=abc; uid_tt=1; sessionid=def';
  window.document.getElementById('btn-cookie-parse').click();
  window.document.getElementById('btn-cookie-dedupe').click();
  const rows = window.document.querySelectorAll('#cookieEditorRows .cookie-row');
  assert.equal(rows.length, 2);
  assert.equal(rows[0].querySelector('.cookie-value').value, 'abc');
});

test('Cookie 编辑器：同 name 覆盖保留最后一个', () => {
  const { window } = setup();
  getById(window, 'm-cookie').value = 'sessionid=abc; uid_tt=1; sessionid=def';
  window.document.getElementById('btn-cookie-parse').click();
  window.document.getElementById('btn-cookie-replace-dupe').click();
  const rows = window.document.querySelectorAll('#cookieEditorRows .cookie-row');
  const sessionRow = Array.from(rows).find(
    (r) => r.querySelector('.cookie-name').value === 'sessionid'
  );
  assert.ok(sessionRow);
  assert.equal(sessionRow.querySelector('.cookie-value').value, 'def');
});

test('Cookie 编辑器：增加字段、清空字段', () => {
  const { window } = setup();
  window.document.getElementById('btn-add-cookie-row').click();
  let rows = window.document.querySelectorAll('#cookieEditorRows .cookie-row');
  assert.equal(rows.length, 1);
  rows[0].querySelector('.cookie-name').value = 'manual';
  rows[0].querySelector('.cookie-name').dispatchEvent(new window.Event('input', { bubbles: true }));
  rows[0].querySelector('.cookie-value').value = 'val';
  rows[0].querySelector('.cookie-value').dispatchEvent(new window.Event('input', { bubbles: true }));
  const json = JSON.parse(getById(window, 'm-cookie-json').value);
  assert.equal(json.length, 1);
  assert.equal(json[0].name, 'manual');
  // 删除
  rows[0].querySelector('.cookie-row-del').click();
  rows = window.document.querySelectorAll('#cookieEditorRows .cookie-row');
  assert.equal(rows.length, 0);
  assert.equal(getById(window, 'm-cookie-json').value, '');
});

test('Cookie 编辑器：JSON 不可解析时给出错误', () => {
  const { window } = setup();
  getById(window, 'm-cookie').value = 'not valid { json at all';
  window.document.getElementById('btn-cookie-parse').click();
  // 不会有任何 row
  const rows = window.document.querySelectorAll('#cookieEditorRows .cookie-row');
  assert.equal(rows.length, 0);
  const status = getById(window, 'cookieParseStatus');
  assert.match(status.textContent, /未能识别/);
});

function getById(window, id) {
  return window.document.getElementById(id);
}
