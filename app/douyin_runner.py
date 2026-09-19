# 抖音自动续火花管理面板 - Playwright 自动化
# 续火核心逻辑基于 bling-yshs/douyin-auto-spark (TypeScript + Playwright)
# https://github.com/bling-yshs/douyin-auto-spark
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from . import database, yiyan
from .message_templates import normalize_template
from .douyin_cookie import parse_cookie_json

log = logging.getLogger("das.runner")

# 超时配置（毫秒）—— 与上游保持一致
CHAT_PAGE_READY_TIMEOUT = 30000   # 聊天页搜索框等待
CHAT_PAGE_IDLE_TIMEOUT = 10000    # 聊天页网络空闲
SEARCH_RESULT_TIMEOUT = 5000      # 搜索结果等待
SEARCH_RETRY_LIMIT = 3           # 搜索重试次数
SEARCH_RETRY_INTERVAL = 2000     # 搜索重试间隔
SEARCH_INPUT_RESET_DELAY = 500   # 搜索框清空后等待

# 截图目录
SCREENSHOT_DIR = Path(os.environ.get("DAS_DATA_DIR", str(Path(__file__).resolve().parent.parent / "data"))) / "screenshots"


# === 错误信息翻译 ===
def _humanize_playwright_error(err: Exception, used_proxy: bool = False) -> str:
    text = str(err)
    if "ERR_PROXY_CONNECTION_FAILED" in text:
        return "代理连接失败：检查 SOCKS5 地址/端口/账号密码是否正确，或代理服务器是否在线"
    if "ERR_TIMED_OUT" in text or "Timeout" in type(err).__name__:
        return "网络超时：检查是否能直连 douyin.com，或换更稳定的代理"
    if "ERR_NAME_NOT_RESOLVED" in text:
        return "DNS 解析失败：检查代理 DNS 设置"
    if "ERR_CONNECTION_REFUSED" in text:
        return "连接被拒绝：检查 douyin.com 是否可达"
    if "ERR_TUNNEL_CONNECTION_FAILED" in text:
        return "代理隧道失败：检查认证信息"
    if "ERR_INVALID_HTTP_RESPONSE" in text:
        return "代理返回非法响应"
    if "Cookie should have a url or a domain/path pair" in text:
        return "Cookie 缺少 domain 或 url"
    if "net::ERR_ABORTED" in text:
        return "导航被中止：检查代理是否稳定"
    if used_proxy:
        return f"使用代理时出错：{text.splitlines()[0] if text else type(err).__name__}"
    return f"{type(err).__name__}: {text.splitlines()[0] if text else err}"


@dataclass
class AccountResult:
    """单个账号的续火结果"""
    account_id: int
    account_name: str
    status: str = "pending"
    channel: str = "direct"
    message: str = ""
    total: int = 0
    success: int = 0
    fail: int = 0
    detail: list[dict] = field(default_factory=list)


def _safe_channel_label(channel: str) -> str:
    if channel == "socks":
        return "SOCKS5 代理"
    return "直连"


def _safe_proxy_label(proxy_url: str) -> str:
    if not proxy_url or "@" not in proxy_url:
        return proxy_url or "直连"
    try:
        protocol, rest = proxy_url.split("://", 1)
        _, host_part = rest.rsplit("@", 1)
        return f"{protocol}://***@{host_part}"
    except Exception:
        return "代理"


# === 代理 URL 解析 ===

def _parse_proxy_url(proxy_url: str) -> dict | None:
    if not proxy_url:
        return None
    proxy_url = proxy_url.strip()
    try:
        m = re.match(
            r"^(?P<scheme>https?|socks5?)://(?:(?P<user>[^:@/]+)(?::(?P<pass>[^@]*))?@)?(?P<host>[^:/]+):(?P<port>\d+)",
            proxy_url,
        )
        if m:
            proxy = {"server": f"{m.group('scheme')}://{m.group('host')}:{m.group('port')}"}
            if m.group("user"):
                proxy["username"] = m.group("user")
            if m.group("pass"):
                proxy["password"] = m.group("pass")
            return proxy
        m2 = re.match(
            r"^(?P<host>[^:]+):(?P<port>\d+)(?::(?P<user>[^:]+)(?::(?P<pass>.*))?)?$",
            proxy_url,
        )
        if m2:
            proxy = {"server": f"socks5://{m2.group('host')}:{m2.group('port')}"}
            if m2.group("user"):
                proxy["username"] = m2.group("user")
            if m2.group("pass"):
                proxy["password"] = m2.group("pass")
            return proxy
        return None
    except Exception as e:
        log.error("解析代理 URL 失败: %s", e)
        return None


def _has_socks5_auth(proxy_config: dict | None) -> bool:
    if not proxy_config:
        return False
    server = proxy_config.get("server", "")
    is_socks = server.startswith("socks5://") or server.startswith("socks5h://")
    return is_socks and bool(proxy_config.get("username"))


# === 本地代理转发（gost） ===

class LocalProxy:
    """本地无认证代理转发。Chromium 不支持带认证的 SOCKS5。"""

    _PORT_RANGE_START = 19080
    _PORT_RANGE_END = 19180
    _next_port = _PORT_RANGE_START
    _proc_lock: asyncio.Lock | None = None
    _gost_path: str | None = None
    _gost_checked: bool = False

    def __init__(self, proxy_url: str):
        self.proxy_url = proxy_url
        self.playwright_config: dict | None = None
        self.port: int | None = None
        self._proc: Any = None
        self._ok = False
        self._error: str = ""

    @property
    def ok(self) -> bool:
        return self._ok

    @property
    def error(self) -> str:
        return self._error

    @property
    def _is_alive(self) -> bool:
        proc = self._proc
        if proc is not None and proc.returncode is not None:
            return False
        return True

    @classmethod
    def _get_lock(cls) -> asyncio.Lock:
        if cls._proc_lock is None:
            cls._proc_lock = asyncio.Lock()
        return cls._proc_lock

    @classmethod
    def _resolve_gost(cls) -> str | None:
        if not cls._gost_checked:
            env_path = os.environ.get("GOST_BIN", "").strip()
            if env_path and os.path.isfile(env_path) and os.access(env_path, os.X_OK):
                cls._gost_path = env_path
            else:
                resolved = shutil.which("gost")
                cls._gost_path = resolved or "/usr/local/bin/gost"
            cls._gost_checked = True
        return cls._gost_path if (cls._gost_path and os.path.isfile(cls._gost_path)) else None

    def _allocate_port(self) -> int:
        LocalProxy._next_port += 1
        if LocalProxy._next_port > LocalProxy._PORT_RANGE_END:
            LocalProxy._next_port = LocalProxy._PORT_RANGE_START
        return LocalProxy._next_port

    async def start(self) -> None:
        proxy_config = _parse_proxy_url(self.proxy_url)
        if not proxy_config:
            self._error = "代理 URL 解析失败"
            return
        if not _has_socks5_auth(proxy_config):
            self.playwright_config = proxy_config
            self._ok = True
            return

        gost = self._resolve_gost()
        if not gost:
            self._error = "gost 未安装"
            log.error(self._error)
            return

        async with self._get_lock():
            self.port = self._allocate_port()
            scheme, _, hostport = proxy_config["server"].partition("://")
            userinfo = proxy_config.get("username", "")
            if proxy_config.get("password"):
                userinfo += f":{proxy_config['password']}"
            forward = f"{scheme}://{userinfo}@{hostport}" if userinfo else f"{scheme}://{hostport}"
            cmd = [gost, "-L", f"socks5://127.0.0.1:{self.port}", "-F", forward]
            try:
                self._proc = await asyncio.create_subprocess_exec(
                    *cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
                )
            except Exception as e:
                self._error = f"启动 gost 失败：{e}"
                log.error(self._error)
                return

            for _ in range(20):
                if await self._can_connect():
                    break
                await asyncio.sleep(0.1)
            else:
                self._error = "gost 启动后端口 2s 内未就绪"
                log.error(self._error)
                await self._kill()
                return

            self.playwright_config = {"server": f"socks5://127.0.0.1:{self.port}"}
            self._ok = True
            log.info("本地代理转发已启动：127.0.0.1:%d -> %s", self.port, _safe_proxy_label(self.proxy_url))

    async def stop(self) -> None:
        if self._proc is None:
            return
        await self._kill()
        log.info("本地代理转发已关闭：127.0.0.1:%d", self.port)

    async def _kill(self) -> None:
        proc = self._proc
        self._proc = None
        if proc is None:
            return
        try:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=2)
            except asyncio.TimeoutError:
                proc.kill()
                try:
                    await asyncio.wait_for(proc.wait(), timeout=2)
                except Exception:
                    pass
        except ProcessLookupError:
            pass
        except Exception as e:
            log.warning("关闭 gost 进程异常：%s", e)

    async def _can_connect(self) -> bool:
        if self.port is None:
            return False
        try:
            _, writer = await asyncio.wait_for(
                asyncio.open_connection("127.0.0.1", self.port), timeout=0.3,
            )
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
            return True
        except Exception:
            return False


class LocalProxyPool:
    """LocalProxy 复用池。"""
    _instances: dict[str, LocalProxy] = {}
    _lock: asyncio.Lock | None = None

    @classmethod
    def _get_lock(cls) -> asyncio.Lock:
        if cls._lock is None:
            cls._lock = asyncio.Lock()
        return cls._lock

    @classmethod
    async def acquire(cls, proxy_url: str) -> LocalProxy:
        key = proxy_url or ""
        async with cls._get_lock():
            lp = cls._instances.get(key)
            if lp is None or not lp._is_alive:
                lp = LocalProxy(proxy_url)
                await lp.start()
                cls._instances[key] = lp
            return lp

    @classmethod
    async def shutdown(cls) -> None:
        async with cls._get_lock():
            items = list(cls._instances.items())
            cls._instances.clear()
        for _, lp in items:
            try:
                await lp.stop()
            except Exception:
                pass


# === Cookie 验证 ===

async def verify_cookie(cookie: str, proxy: str = "") -> dict:
    from playwright.async_api import async_playwright
    try:
        cookies = parse_cookie_json(cookie)
    except Exception as e:
        return {"valid": False, "message": f"Cookie 解析失败: {e}"}

    local_proxy = await LocalProxyPool.acquire(proxy)
    if proxy and not local_proxy.ok:
        return {"valid": False, "message": f"代理初始化失败：{local_proxy.error}"}

    async with async_playwright() as p:
        browser = None
        try:
            launch_options = {"headless": True}
            if local_proxy.playwright_config:
                launch_options["proxy"] = local_proxy.playwright_config
            browser = await p.chromium.launch(**launch_options)
            context = await browser.new_context()
            try:
                await context.add_cookies([c.to_playwright_cookie() for c in cookies])
            except Exception as add_err:
                log.warning("add_cookies 初次失败 (%s)，后备只传 name+value+domain", add_err)
                minimal = [{"name": c.name, "value": c.value, "domain": c.domain or ".douyin.com", "path": "/"} for c in cookies]
                await context.add_cookies(minimal)

            page = await context.new_page()
            try:
                await page.goto("https://www.douyin.com/chat", wait_until="commit", timeout=20000)
            except Exception as e:
                return {"valid": False, "message": f"打开抖音页失败：{_humanize_playwright_error(e, bool(proxy))}"}

            # 并发探查
            valid_selectors = (
                'input[placeholder*="搜索"]',
                '[contenteditable="true"]',
                '[class*="conversation"]',
                '[class*="message-list"]',
                '[class*="chat-list"]',
            )
            valid_tasks = [_probe_selector_visible(page, sel, 4000) for sel in valid_selectors]
            valid_results = await asyncio.gather(*valid_tasks, return_exceptions=True)
            if any(r is True for r in valid_results):
                return {"valid": True, "message": "Cookie 有效，已进入抖音消息页面"}

            invalid_markers = ("登录", "扫码登录", "立即登录", "二维码登录", "验证码登录", "密码登录")
            invalid_tasks = [_probe_text_visible(page, m, 2000) for m in invalid_markers]
            invalid_results = await asyncio.gather(*invalid_tasks, return_exceptions=True)
            if any(r is True for r in invalid_results):
                return {"valid": False, "message": "Cookie 已失效，需要重新登录"}

            current_url = page.url
            if "/chat" in current_url and "login" not in current_url.lower():
                return {"valid": True, "message": "Cookie 可能有效：已进入消息页", "uncertain": True}
            return {"valid": False, "message": f"未进入抖音消息页（页面：{current_url}）"}
        except Exception as e:
            log.error("验证账号异常: %s", e, exc_info=True)
            return {"valid": False, "message": f"验证失败: {_humanize_playwright_error(e, bool(proxy))}"}
        finally:
            if browser:
                try:
                    await browser.close()
                except Exception:
                    pass


async def _probe_selector_visible(page, selector: str, timeout_ms: int) -> bool:
    try:
        return await page.locator(selector).first.is_visible(timeout=timeout_ms)
    except Exception:
        return False


async def _probe_text_visible(page, text: str, timeout_ms: int) -> bool:
    try:
        return await page.get_by_text(text, exact=False).first.is_visible(timeout=timeout_ms)
    except Exception:
        return False


# === 获取好友列表 ===

async def fetch_friend_list(account: dict) -> dict:
    """自动获取抖音聊天页的好友列表。"""
    from playwright.async_api import async_playwright

    proxy_url = account.get("proxy", "") or ""
    try:
        cookies = parse_cookie_json(account["cookie"])
    except Exception as e:
        return {"friends": [], "message": f"Cookie 解析失败：{e}", "reason": "no_cookies"}

    local_proxy = await LocalProxyPool.acquire(proxy_url)
    if proxy_url and not local_proxy.ok:
        return {"friends": [], "message": f"代理初始化失败：{local_proxy.error}", "reason": "proxy_failed"}

    friends: list[str] = []
    async with async_playwright() as p:
        browser = None
        try:
            launch_options = {"headless": True}
            if local_proxy.playwright_config:
                launch_options["proxy"] = local_proxy.playwright_config
            browser = await p.chromium.launch(**launch_options)
            context = await browser.new_context()
            try:
                await context.add_cookies([c.to_playwright_cookie() for c in cookies])
            except Exception:
                minimal = [{"name": c.name, "value": c.value, "domain": c.domain or ".douyin.com", "path": "/"} for c in cookies]
                await context.add_cookies(minimal)

            page = await context.new_page()
            await page.goto("https://www.douyin.com/chat", wait_until="commit", timeout=20000)

            # 等待搜索框出现
            search_visible = await page.locator('input[placeholder*="搜索"]').first.is_visible(timeout=CHAT_PAGE_READY_TIMEOUT)
            if not search_visible:
                # 检查登录页
                login_text = await page.get_by_text("扫码登录", exact=False).first.is_visible(timeout=2000)
                if login_text:
                    return {"friends": [], "message": "Cookie 已失效：当前页面是登录页", "reason": "login_page"}
                return {"friends": [], "message": "聊天页加载超时", "reason": "timeout"}

            # 等待会话列表渲染
            await page.wait_for_load_state("networkidle", timeout=CHAT_PAGE_IDLE_TIMEOUT)
            await page.wait_for_timeout(2000)

            # 提取好友名称 —— JS 结构探测
            items = await page.evaluate(
                r"""() => {
                    var results = [];
                    var seen = {};
                    function blocked(t) {
                        var list = ['系统通知', '消息', '抖音', '抖音小助手', '抖音官方', '互动消息', '陌生人消息', '通知'];
                        for (var b = 0; b < list.length; b++) if (t === list[b]) return true;
                        if (t.indexOf('系统') === 0 || t.indexOf('通知') === 0) return true;
                        return false;
                    }
                    function add(t) {
                        t = (t || '').trim();
                        if (t.length < 2 || t.length > 30) return false;
                        if (t.indexOf('\n') >= 0) return false;
                        if (blocked(t)) return false;
                        if (seen[t]) return false;
                        if (/^\d+$/.test(t)) return false;
                        seen[t] = true;
                        results.push(t);
                        return true;
                    }
                    // 策略 A：找 img 旁的短文本
                    var imgs = document.querySelectorAll('img');
                    for (var i = 0; i < imgs.length; i++) {
                        var img = imgs[i];
                        var r = img.getBoundingClientRect();
                        if (r.width < 15 || r.width > 80 || r.height < 15 || r.height > 80) continue;
                        var p = img.parentElement;
                        if (!p) continue;
                        var children = p.children;
                        for (var j = 0; j < children.length; j++) {
                            if (children[j] === img) continue;
                            var t = (children[j].textContent || '').trim();
                            if (t.length >= 1 && t.length <= 30 && t.indexOf('\n') < 0) {
                                add(t); break;
                            }
                        }
                    }
                    // 策略 B：左侧栏含 img 的容器
                    if (results.length < 5) {
                        var all = document.querySelectorAll('div, li, a, span');
                        for (var i2 = 0; i2 < all.length; i2++) {
                            var el = all[i2];
                            var r2 = el.getBoundingClientRect();
                            if (r2.left > 400 || r2.width < 30 || r2.height < 20 || r2.height > 200) continue;
                            if (!el.querySelector('img')) continue;
                            var t2 = (el.textContent || '').trim();
                            if (t2.length < 2 || t2.length > 30 || t2.indexOf('\n') >= 0) continue;
                            add(t2);
                        }
                    }
                    return results.slice(0, 100);
                }"""
            )
            if items:
                friends.extend(items)

        except Exception as e:
            log.error("获取好友列表失败: %s", e, exc_info=True)
            return {"friends": [], "message": f"获取好友列表失败：{e}", "reason": "exception"}
        finally:
            if browser:
                try:
                    await browser.close()
                except Exception:
                    pass

    result = list(dict.fromkeys(friends))
    if not result:
        return {"friends": [], "message": "未找到好友：聊天页可能未加载完成", "reason": "empty"}
    return {"friends": result, "message": "", "reason": ""}


# ====================================================================
# 续火核心逻辑 —— 基于 bling-yshs/douyin-auto-spark 上游重写
# ====================================================================

async def run_account_spark(account: dict, task_id: str) -> AccountResult:
    """执行单个账号的续火任务。

    完整复刻上游 bling-yshs/douyin-auto-spark 的流程：
    1. 打开抖音聊天页
    2. 等待搜索框出现
    3. 等待会话列表渲染（networkidle）
    4. 遍历每个好友：
       a. 清空搜索框，等待旧结果消失
       b. 输入好友名
       c. 等待 .SearchPanelitembox 容器出现（含目标名）
       d. 点击「发消息」按钮
       e. 等待输入框出现
       f. 输入消息并发送
       g. 等待 1s
    5. 汇总结果
    """
    from playwright.async_api import async_playwright

    result = AccountResult(
        account_id=account["id"],
        account_name=account["name"],
    )

    proxy_url = account.get("proxy", "") or ""
    if proxy_url:
        result.channel = "socks"

    proxy_label = _safe_proxy_label(proxy_url)
    log.info("👤 [%s] 账号：%s", proxy_label, account["name"])

    targets = database.get_enabled_targets(account["id"])
    if not targets:
        result.status = "skipped"
        result.message = "没有启用的好友"
        log.info("  [%s] 没有启用的好友，跳过", account["name"])
        return result

    result.total = len(targets)

    try:
        cookies = parse_cookie_json(account["cookie"])
    except Exception as e:
        result.status = "failed"
        result.message = f"Cookie 解析失败：{e}"
        log.error("  [%s] Cookie 解析失败：%s", account["name"], e)
        return result

    message_template = database.get_setting("message_template", "")
    if message_template:
        try:
            message_template = normalize_template(message_template, "message_template")
        except ValueError as exc:
            result.status = "failed"
            result.message = str(exc)
            return result
    include_source = database.get_setting("yiyan_include_source", "1") == "1"

    local_proxy = await LocalProxyPool.acquire(proxy_url)
    if proxy_url and not local_proxy.ok:
        result.status = "failed"
        result.message = f"代理初始化失败：{local_proxy.error}"
        log.error("  [%s] %s", account["name"], result.message)
        return result

    async with async_playwright() as p:
        browser = None
        try:
            # 1. 启动浏览器
            browser_path = os.environ.get("PLAYWRIGHT_BROWSER_PATH", "").strip() or None
            headless = os.environ.get("PLAYWRIGHT_HEADLESS", "1") != "0"
            launch_options = {"headless": headless}
            if browser_path:
                launch_options["executable_path"] = browser_path
            if local_proxy.playwright_config:
                launch_options["proxy"] = local_proxy.playwright_config
            browser = await p.chromium.launch(**launch_options)

            context = await browser.new_context()
            try:
                await context.add_cookies([c.to_playwright_cookie() for c in cookies])
            except Exception as add_err:
                log.warning("add_cookies 初次失败 (%s)，后备只传 name+value+domain", add_err)
                minimal = []
                for c in cookies:
                    mc = {"name": c.name, "value": c.value}
                    if c.domain:
                        mc["domain"] = c.domain
                    elif c.url:
                        mc["url"] = c.url
                    else:
                        mc["url"] = "https://www.douyin.com"
                    mc["path"] = "/"
                    minimal.append(mc)
                await context.add_cookies(minimal)

            page = await context.new_page()

            # 2. 打开聊天页（上游用 domcontentloaded，比 commit 更稳）
            try:
                await page.goto("https://www.douyin.com/chat", wait_until="domcontentloaded", timeout=20000)
            except Exception as e:
                result.status = "failed"
                result.message = f"打开抖音页失败：{_humanize_playwright_error(e, bool(proxy_url))}"
                log.error("  [%s] %s", account["name"], result.message)
                return result

            # 3. 等待搜索框出现（上游用 waitFor，不是 isVisible）
            search_input = page.locator('input.semi-input[placeholder="搜索"]').first
            search_visible = False
            try:
                await search_input.wait_for(state="visible", timeout=CHAT_PAGE_READY_TIMEOUT)
                search_visible = True
            except Exception:
                pass
            if not search_visible:
                # 保存调试信息
                debug_dir = SCREENSHOT_DIR / "debug"
                debug_dir.mkdir(parents=True, exist_ok=True)
                debug_name = f"{account['name']}-no-search-box"
                try:
                    await page.screenshot(path=str(debug_dir / f"{debug_name}.png"), full_page=False)
                except Exception:
                    pass
                result.status = "failed"
                result.message = "聊天页搜索框未出现，Cookie 可能已经失效"
                log.error("  [%s] 聊天页搜索框未出现", account["name"])
                return result

            # 4. 等待会话列表渲染
            await _wait_chat_list_ready(page, account["name"])

            # 5. 遍历每个好友
            missing_names: list[str] = []
            spark_delay_min = float(database.get_setting("spark_delay_min", "3") or "3")
            spark_delay_max = float(database.get_setting("spark_delay_max", "8") or "8")

            for idx, target in enumerate(targets):
                target_name = target["name"]
                log.info("  [%s] 开始搜索会话：%s", account["name"], target_name)

                # 好友间随机延时
                if idx > 0 and spark_delay_min > 0:
                    import random
                    delay = random.uniform(spark_delay_min, max(spark_delay_min, spark_delay_max))
                    log.info("  [%s] 好友间延时 %.1f 秒", account["name"], delay)
                    await page.wait_for_timeout(int(delay * 1000))

                # 搜索会话
                search_result = await _search_conversation(
                    page, search_input, account["name"], target_name
                )

                if not search_result:
                    await _capture_screenshot(page, f"{account['name']}-{target_name}-search")
                    log.warning("  [%s] 找不到搜索结果，已跳过：%s", account["name"], target_name)
                    missing_names.append(target_name)
                    result.detail.append({
                        "target": target_name,
                        "status": "failed",
                        "message": "找不到会话",
                    })
                    result.fail += 1
                    continue

                # 点击「发消息」按钮进入对话（上游用正则精确匹配发消息/发私信）
                import re as _re
                try:
                    send_btn = search_result.get_by_text(_re.compile(r"^(发消息|发私信)$")).first
                    await send_btn.click(timeout=5000)
                except Exception as e:
                    log.warning("  [%s] 点「发消息」失败，尝试点容器：%s", account["name"], e)
                    try:
                        await search_result.click(timeout=5000)
                    except Exception as e2:
                        log.warning("  [%s] 点容器也失败：%s", account["name"], e2)
                        missing_names.append(target_name)
                        result.detail.append({
                            "target": target_name,
                            "status": "failed",
                            "message": "无法点击发消息按钮",
                        })
                        result.fail += 1
                        continue

                log.info("  [%s] 已打开私信：%s", account["name"], target_name)

                # 等待输入框出现（上游用 waitFor）
                editor_input = page.locator(
                    '.messageEditorimChatEditorContainer [data-slate-editor="true"][contenteditable="true"]'
                ).first
                editor_visible = False
                try:
                    await editor_input.wait_for(state="visible", timeout=10000)
                    editor_visible = True
                except Exception:
                    pass
                if not editor_visible:
                    log.warning("  [%s] 无法定位输入框", account["name"])
                    missing_names.append(target_name)
                    result.detail.append({
                        "target": target_name,
                        "status": "failed",
                        "message": "无法定位输入框",
                    })
                    result.fail += 1
                    continue

                await editor_input.click()
                await page.wait_for_timeout(500)

                # 渲染消息
                msg = yiyan.render_message(
                    message_template or None,
                    account["name"],
                    target_name,
                    include_source=include_source,
                )

                # 发送消息（与上游同款：insert_text → 直接 Enter → 等待 1s）
                await page.keyboard.insert_text(msg)
                await page.keyboard.press("Enter")
                log.info("  [%s] 已发送消息：%s", account["name"], target_name)
                await page.wait_for_timeout(1000)

                result.detail.append({
                    "target": target_name,
                    "status": "success",
                    "message": "已发送",
                })
                result.success += 1
                database.touch_target_result(target["id"], "success")

            # 6. 汇总
            await page.wait_for_timeout(3000)

            if missing_names:
                result.message = f"以下会话未找到：{'、'.join(missing_names)}"
                if result.success > 0:
                    result.status = "partial"
                else:
                    result.status = "failed"
            else:
                result.status = "success"
                result.message = f"成功续火 {result.success} 个好友"

            log.info("  [%s] 账号执行完成：%s", account["name"], result.message)

        except Exception as e:
            log.exception("  [%s] 账号执行异常：%s", account["name"], e)
            result.status = "failed"
            result.message = _humanize_playwright_error(e, bool(proxy_url))
        finally:
            if browser:
                try:
                    await browser.close()
                except Exception:
                    pass

    return result


async def _wait_chat_list_ready(page: Any, account_name: str) -> None:
    """等待会话列表真正渲染出数据再开始搜索。

    搜索框会先于会话列表渲染，若此时就输入关键词，抖音的搜索索引尚未就绪，
    结果面板会一直为空，导致好友被误判成「改名了」。
    """
    try:
        ready = page.locator('[class*="conversation"], [class*="Conversation"]').first
        await ready.wait_for(state="visible", timeout=CHAT_PAGE_READY_TIMEOUT)
    except Exception:
        log.info("  [%s] 会话列表未在预期时间内出现，将依赖搜索重试兜底", account_name)

    # 等网络安静下来，搜索命中率更高
    try:
        await page.wait_for_load_state("networkidle", timeout=CHAT_PAGE_IDLE_TIMEOUT)
    except Exception:
        pass


async def _search_conversation(
    page: Any, search_input: Any, account_name: str, target_name: str
) -> Any:
    """带重试地搜索会话，返回搜索结果的容器 Locator。

    忠实复刻上游逻辑：
    - 每一轮都重新清空输入框并等待旧结果消失
    - 用 .SearchPanelitembox 容器过滤法定位结果
    - 等待容器变为 visible（wait_for 而非 is_visible）
    """
    search_result = page.locator(".SearchPanelitembox").filter(
        has=page.get_by_text(target_name, exact=True)
    ).first

    for attempt in range(1, SEARCH_RETRY_LIMIT + 1):
        # 清空输入框
        await search_input.fill("")
        # 等旧的结果面板收起（上游同款）
        try:
            await page.locator(".SearchPanelitembox").first.wait_for(
                state="hidden", timeout=SEARCH_RESULT_TIMEOUT
            )
        except Exception:
            pass
        await page.wait_for_timeout(SEARCH_INPUT_RESET_DELAY)

        # 输入好友名
        await search_input.fill(target_name)

        # 等待搜索结果容器变为 visible（关键：用 wait_for 不是 is_visible）
        # is_visible 在元素不存在时会立刻返回 False，不等超时
        # wait_for(state='visible') 会等元素匹配 + 可见
        search_result_visible = False
        try:
            await search_result.wait_for(state="visible", timeout=SEARCH_RESULT_TIMEOUT)
            search_result_visible = True
        except Exception:
            pass

        if search_result_visible:
            return search_result

        if attempt < SEARCH_RETRY_LIMIT:
            log.info(
                "  [%s] 第 %d 次搜索未命中，%dms 后重试：%s",
                account_name, attempt, SEARCH_RETRY_INTERVAL, target_name
            )
            await page.wait_for_timeout(SEARCH_RETRY_INTERVAL)

    return None


async def _capture_screenshot(page: Any, name: str) -> None:
    """保存失败截图"""
    if page is None or page.is_closed():
        return
    try:
        SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
        safe_name = "".join(c if c.isalnum() or c in "-_" else "-" for c in name)
        path = SCREENSHOT_DIR / f"failure-{safe_name}.png"
        await page.screenshot(path=str(path), full_page=True)
        log.info("已保存失败截图：%s", path)
    except Exception as e:
        log.error("保存失败截图失败：%s", e)


# === 同步包装器 ===

def run_account_spark_sync(account: dict, task_id: str) -> AccountResult:
    return asyncio.run(run_account_spark(account, task_id))


def verify_cookie_sync(cookie: str, proxy: str = "") -> dict:
    return asyncio.run(verify_cookie(cookie, proxy))


def fetch_friend_list_sync(account: dict) -> dict:
    return asyncio.run(fetch_friend_list(account))


# ==================== 代理测试与归属地检测 ====================

import socket
import struct
from concurrent.futures import ThreadPoolExecutor

_PROXY_TIMEOUT = float(os.environ.get("DAS_PROXY_TIMEOUT", "30") or "30")
_GEO_HTTP_TARGET = ("ip-api.com", 80)
_GEO_HTTP_PATH = (
    "/json/?lang=zh-CN&fields=status,country,countryCode,regionName,city,query"
)


def _split_proxy_url(proxy_url: str) -> tuple[str, int, str, str]:
    if not proxy_url:
        raise ValueError("代理 URL 为空")
    if "://" in proxy_url:
        scheme, rest = proxy_url.split("://", 1)
        if scheme.lower() not in {"socks5", "socks5h"}:
            raise ValueError(f"仅支持 SOCKS5 代理：{scheme}")
    else:
        rest = proxy_url
    user = pwd = ""
    if "@" in rest:
        auth, host_part = rest.rsplit("@", 1)
        if ":" in auth:
            user, pwd = auth.split(":", 1)
    else:
        host_part = rest
    if ":" not in host_part:
        raise ValueError("代理 URL 缺少端口：socks5://host:port")
    parts = host_part.split(":")
    if len(parts) >= 2:
        host = parts[0]
        try:
            port = int(parts[1])
        except ValueError:
            raise ValueError(f"代理端口必须为数字：{parts[1]!r}")
        if len(parts) >= 4 and not user:
            user = parts[2]
            pwd = parts[3]
    else:
        raise ValueError("代理 URL 缺少端口")
    return host.strip(), port, user, pwd


def _socks5_connect(proxy_url: str, target_host: str, target_port: int) -> socket.socket:
    host, port, user, pwd = _split_proxy_url(proxy_url)
    sock = socket.create_connection((host, port), timeout=_PROXY_TIMEOUT)
    try:
        sock.sendall(b"\x05\x01\x00")
        greeting = _recv_exact(sock, 2)
        if greeting[0] != 0x05:
            raise ConnectionError("SOCKS5 服务器协议错误")
        if greeting[1] == 0xFF:
            raise ConnectionError("SOCKS5 服务器无可用认证方式")
        if greeting[1] != 0x00:
            if not user:
                raise ConnectionError("SOCKS5 服务器需要认证但 URL 未提供凭据")
            req = b"\x01" + bytes([len(user)]) + user.encode("utf-8") + bytes([len(pwd)]) + pwd.encode("utf-8")
            sock.sendall(req)
            auth_resp = _recv_exact(sock, 2)
            if auth_resp[1] != 0x00:
                raise ConnectionError("SOCKS5 用户名密码认证失败")
        if _looks_like_ip(target_host):
            try:
                packed = socket.inet_aton(target_host)
                atyp = b"\x01" + packed
            except OSError:
                atyp = b"\x03" + bytes([len(target_host)]) + target_host.encode("utf-8")
        else:
            atyp = b"\x03" + bytes([len(target_host)]) + target_host.encode("utf-8")
        req = b"\x05\x01\x00" + atyp + struct.pack("!H", target_port)
        sock.sendall(req)
        resp = _recv_exact(sock, 4)
        atyp = resp[3]
        if resp[1] != 0x00:
            err_map = {
                0x01: "一般性失败", 0x02: "规则不允许", 0x03: "网络不可达",
                0x04: "主机不可达", 0x05: "连接被拒", 0x06: "TTL 过期",
                0x07: "命令不支持", 0x08: "地址类型不支持",
            }
            raise ConnectionError(f"SOCKS5 CONNECT 失败：{err_map.get(resp[1], '0x%02x' % resp[1])}")
        if atyp == 0x01:
            _recv_exact(sock, 4)
        elif atyp == 0x03:
            ln = _recv_exact(sock, 1)[0]
            _recv_exact(sock, ln)
        elif atyp == 0x04:
            _recv_exact(sock, 16)
        else:
            raise ConnectionError(f"SOCKS5 不支持的 ATYP：0x{atyp:02x}")
        _recv_exact(sock, 2)
        return sock
    except BaseException:
        try:
            sock.close()
        except Exception:
            pass
        raise


def _recv_exact(sock: socket.socket, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("连接被关闭")
        buf += chunk
    return buf


def _looks_like_ip(host: str) -> bool:
    if host.count(".") != 3:
        return False
    for seg in host.split("."):
        if not seg.isdigit() or not 0 <= int(seg) <= 255:
            return False
    return True


def _http_get_via_socks(proxy_url: str, host: str, port: int, path: str) -> str:
    sock = _socks5_connect(proxy_url, host, port)
    try:
        req = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}\r\n"
            f"User-Agent: Mozilla/5.0 (Douyin-Auto-Spark)\r\n"
            f"Accept: application/json\r\n"
            f"Connection: close\r\n\r\n"
        ).encode("ascii")
        sock.sendall(req)
        chunks = []
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            chunks.append(chunk)
        raw = b"".join(chunks)
        if b"\r\n\r\n" not in raw:
            return raw.decode("utf-8", "replace")
        head, body = raw.split(b"\r\n\r\n", 1)
        return body.decode("utf-8", "replace")
    finally:
        try:
            sock.close()
        except Exception:
            pass


def _direct_http_get(host: str, port: int, path: str) -> str:
    sock = socket.create_connection((host, port), timeout=_PROXY_TIMEOUT)
    try:
        req = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}\r\n"
            f"User-Agent: Mozilla/5.0 (Douyin-Auto-Spark)\r\n"
            f"Accept: application/json\r\n"
            f"Connection: close\r\n\r\n"
        ).encode("ascii")
        sock.sendall(req)
        chunks = []
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            chunks.append(chunk)
        raw = b"".join(chunks)
        if b"\r\n\r\n" not in raw:
            return raw.decode("utf-8", "replace")
        _, body = raw.split(b"\r\n\r\n", 1)
        return body.decode("utf-8", "replace")
    finally:
        try:
            sock.close()
        except Exception:
            pass


def _test_proxy_internal(proxy_url: str) -> dict:
    if not proxy_url:
        return {"ok": False, "message": "代理 URL 为空"}
    try:
        body = _http_get_via_socks(proxy_url, *_GEO_HTTP_TARGET, path=_GEO_HTTP_PATH)
    except (OSError, ConnectionError) as e:
        return {"ok": False, "message": f"测试失败：{e}"}
    except Exception as e:
        return {"ok": False, "message": f"测试失败：{type(e).__name__}: {e}"}

    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return {"ok": False, "message": f"响应解析失败：{body[:120]!r}"}

    if not isinstance(data, dict) or data.get("status") != "success":
        msg = data.get("message") if isinstance(data, dict) else None
        return {"ok": False, "message": f"归属地查询失败：{msg or '无效响应'}"}

    country = data.get("country", "")
    country_code = data.get("countryCode", "")
    region = data.get("regionName", "")
    city = data.get("city", "")
    ip = data.get("query", "")
    parts = [p for p in [country, region, city] if p]
    location_str = " · ".join(parts) if parts else "未知"
    return {
        "ok": True, "ip": ip, "country": country, "country_code": country_code,
        "region": region, "city": city, "message": f"✅ {location_str} ({ip})",
    }


async def _test_proxy_async(proxy_url: str) -> dict:
    loop = asyncio.get_running_loop()
    with ThreadPoolExecutor(max_workers=1) as pool:
        return await loop.run_in_executor(pool, _test_proxy_internal, proxy_url)


def test_proxy_sync(proxy_url: str) -> dict:
    return _test_proxy_internal(proxy_url)


def detect_geo_sync(proxy_url: str) -> dict:
    return _test_proxy_internal(proxy_url)
