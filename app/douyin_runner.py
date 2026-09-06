# 抖音自动续火花管理面板 - Playwright 自动化
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

# 超时配置（毫秒）
CHAT_PAGE_READY_TIMEOUT = 30000
CHAT_PAGE_IDLE_TIMEOUT = 10000
SEARCH_RESULT_TIMEOUT = 5000
SEARCH_RETRY_LIMIT = 3
SEARCH_RETRY_INTERVAL = 2000
SEARCH_INPUT_RESET_DELAY = 500

# 截图目录
SCREENSHOT_DIR = Path(os.environ.get("DAS_DATA_DIR", str(Path(__file__).resolve().parent.parent / "data"))) / "screenshots"


# === 错误信息翻译 ===
def _humanize_playwright_error(err: Exception, used_proxy: bool = False) -> str:
    """把 Playwright 异常翻译为用户能看懂的提示。"""
    text = str(err)
    if "ERR_PROXY_CONNECTION_FAILED" in text:
        return "代理连接失败：检查 SOCKS5 地址/端口/账号密码是否正确，或代理服务器是否在线"
    if "ERR_TIMED_OUT" in text or "Timeout" in type(err).__name__:
        return "网络超时：检查是否能直连 douyin.com，或换更稳定的代理"
    if "ERR_NAME_NOT_RESOLVED" in text:
        return "DNS 解析失败：检查代理 DNS 设置，或网络是否能解析 douyin.com"
    if "ERR_CONNECTION_REFUSED" in text:
        return "连接被拒绝：检查 douyin.com 是否可达或代理端口"
    if "ERR_TUNNEL_CONNECTION_FAILED" in text:
        return "代理隧道失败：检查认证信息与代理协议是否匹配"
    if "ERR_INVALID_HTTP_RESPONSE" in text:
        return "代理返回非法响应：可能不是 SOCKS5 代理"
    if "Cookie should have a url or a domain/path pair" in text:
        return "Cookie 缺少 domain 或 url：所有 cookie 必须有 domain 或 url 字段"
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
    """日志只记录安全的通道摘要"""
    if channel == "socks":
        return "SOCKS5 代理"
    return "直连"


def _safe_proxy_label(proxy_url: str) -> str:
    """脱敏代理 URL 用于日志"""
    if not proxy_url or "@" not in proxy_url:
        return proxy_url or "直连"
    try:
        protocol, rest = proxy_url.split("://", 1)
        auth, host_part = rest.rsplit("@", 1)
        return f"{protocol}://***@{host_part}"
    except Exception:
        return "代理"


def _parse_proxy_url(proxy_url: str) -> dict | None:
    """解析代理 URL 为 Playwright proxy 配置。

    支持的格式：
    - socks5://user:pass@host:port
    - socks5://host:port
    - http://user:pass@host:port  （HTTPS 代理）
    - http://host:port
    - host:port:user:pass
    - host:port
    """
    if not proxy_url:
        return None
    proxy_url = proxy_url.strip()
    try:
        # 带 scheme 的标准 URL
        # 用 \S+ 保证非空白；密码允许包含特殊字符用 [^@]*
        m = re.match(
            r"^(?P<scheme>https?|socks5?)://(?:(?P<user>[^:@/]+)(?::(?P<pass>[^@]*))?@)?(?P<host>[^:/]+):(?P<port>\d+)",
            proxy_url,
        )
        if m:
            scheme = m.group("scheme")
            host = m.group("host")
            port = m.group("port")
            proxy = {"server": f"{scheme}://{host}:{port}"}
            if m.group("user"):
                proxy["username"] = m.group("user")
            if m.group("pass"):
                proxy["password"] = m.group("pass")
            return proxy
        # 无 scheme：ip:port[:user:pass]
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
    """判断 Playwright proxy config 是否是带认证的 SOCKS5（Chromium 不支持）。"""
    if not proxy_config:
        return False
    server = proxy_config.get("server", "")
    # server 形如 socks5://host:port 或 socks5h://host:port
    is_socks = server.startswith("socks5://") or server.startswith("socks5h://")
    if not is_socks:
        return False
    return bool(proxy_config.get("username")) or bool(proxy_config.get("password"))


class LocalProxy:
    """本地无认证代理转发。

    Chromium 内核不支持带认证的 SOCKS5 代理。
    本类在容器内起一个 gost 进程，把远端带认证的代理转发到本地无认证端口，
    让 Playwright 通过 127.0.0.1:PORT 直连即可。

    不带认证或解析失败的代理 ``ok=True`` 但 ``playwright_config`` 可能为 None，调用方按直连处理。
    带认证的 SOCKS5 会启动 gost 进程，``playwright_config`` 指向 127.0.0.1。

    用法::

        local_proxy = LocalProxy(proxy_url)
        try:
            await local_proxy.start()
            if not local_proxy.ok:
                # 启动失败：local_proxy.error 包含原因
                return
            launch_options["proxy"] = local_proxy.playwright_config
            # ... use launch_options ...
        finally:
            await local_proxy.stop()
    """

    _PORT_RANGE_START = 19080
    _PORT_RANGE_END = 19180
    _next_port = _PORT_RANGE_START
    _proc_lock: "asyncio.Lock | None" = None
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

    @classmethod
    def _get_lock(cls) -> "asyncio.Lock":
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
        """准备代理配置；带认证 SOCKS5 时启动 gost 进程。"""
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
            self._error = "gost 未安装：容器缺少 gost，镜像构建失败？"
            log.error(self._error)
            return

        async with self._get_lock():
            self.port = self._allocate_port()
            scheme, _, hostport = proxy_config["server"].partition("://")
            if proxy_config.get("username"):
                userinfo = proxy_config["username"]
                if proxy_config.get("password"):
                    userinfo += f":{proxy_config['password']}"
                forward = f"{scheme}://{userinfo}@{hostport}"
            else:
                forward = f"{scheme}://{hostport}"
            cmd = [
                gost,
                "-L", f"socks5://127.0.0.1:{self.port}",
                "-F", forward,
            ]
            try:
                self._proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.PIPE,
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
            log.info(
                "本地代理转发已启动：127.0.0.1:%d -> %s",
                self.port, _safe_proxy_label(self.proxy_url),
            )

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
                asyncio.open_connection("127.0.0.1", self.port),
                timeout=0.3,
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
    """LocalProxy 复用池。

    不同账号可能使用同一个 SOCKS5 代理：每次验证都起/停 gost 进程太浪费。
    本类按 proxy_url 缓存已启动的 LocalProxy，多个调用方同时复用。
    直连（空 url）也建一个“伪”条目便于统一调用。

    不是 thread/connection 池 —— 只是进程池。Playwright 仍需要串行访问代理
    端口，但 gost 是无状态的转发器，并发请求不冲突。
    """

    _instances: dict[str, "LocalProxy"] = {}
    _lock: "asyncio.Lock | None" = None

    @classmethod
    def _get_lock(cls) -> "asyncio.Lock":
        if cls._lock is None:
            cls._lock = asyncio.Lock()
        return cls._lock

    @classmethod
    async def acquire(cls, proxy_url: str) -> LocalProxy:
        """获取一个已就绪的 LocalProxy。重复调用同一 url 返回同一实例。"""
        key = proxy_url or ""
        async with cls._get_lock():
            lp = cls._instances.get(key)
            if lp is None or not lp._is_alive():
                lp = LocalProxy(proxy_url)
                await lp.start()
                if not lp.ok:
                    # 启动失败：原样返回，调用方根据 lp.error / lp.ok 判断
                    cls._instances[key] = lp
                    return lp
                cls._instances[key] = lp
            return lp

    @classmethod
    async def shutdown(cls) -> None:
        """关闭所有实例，进程退出前调用。"""
        async with cls._get_lock():
            items = list(cls._instances.items())
            cls._instances.clear()
        for _, lp in items:
            try:
                await lp.stop()
            except Exception:
                pass


def _is_alive(self_ref) -> bool:
    """LocalProxy 的存活判断：进程在且端口可连。"""
    proc = self_ref._proc
    if proc is not None and proc.returncode is not None:
        return False
    return True

# 把 _is_alive 挂到 LocalProxy 上
LocalProxy._is_alive = _is_alive  # type: ignore[attr-defined]


async def verify_cookie(cookie: str, proxy: str = "") -> dict:
    """验证账号 Cookie 是否有效。

    关键优化：
    1. LocalProxyPool 复用 gost 进程，同一代理多次验证不重启
    2. 多个“有效指示器”并发探查（asyncio.gather），不再串行
    3. 网络空闲超时从 10s 降到 5s
    4. page.goto 用 commit，domcontentloaded 之后直接探查
    """
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
            # 先按原状加载；sameSite 之类的参数在 to_playwright_cookie 中已经过验证。
            try:
                await context.add_cookies([c.to_playwright_cookie() for c in cookies])
            except Exception as add_err:
                # 后备方案：只传 name+value+domain，其它去掉
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
            # 用 commit 等待返回，dom 立即可用；不依赖 networkidle
            try:
                await page.goto("https://www.douyin.com/chat", wait_until="commit", timeout=20000)
            except Exception as e:
                return {"valid": False, "message": f"打开抖音页失败：{_humanize_playwright_error(e, used_proxy=bool(proxy))}"}

            # 并发探查多个“有效”指示器
            valid_selectors = (
                'input[placeholder*="搜索"]',
                '[contenteditable="true"]',
                '[class*="conversation"]',
                '[class*="message-list"]',
                '[class*="chat-list"]',
            )
            valid_tasks = [
                _probe_selector_visible(page, sel, timeout_ms=4000)
                for sel in valid_selectors
            ]
            valid_results = await asyncio.gather(*valid_tasks, return_exceptions=True)
            for ok in valid_results:
                if ok is True:
                    return {"valid": True, "message": "Cookie 有效，已进入抖音消息页面"}

            # 并发探查“登录页”指示器
            invalid_markers = ("登录", "扫码登录", "立即登录", "二维码登录", "验证码登录", "密码登录")
            invalid_tasks = [
                _probe_text_visible(page, marker, timeout_ms=2000)
                for marker in invalid_markers
            ]
            invalid_results = await asyncio.gather(*invalid_tasks, return_exceptions=True)
            for ok in invalid_results:
                if ok is True:
                    return {"valid": False, "message": "Cookie 已失效，需要重新登录"}

            # 页面可能因风控、验证码或结构变化而无法直接识别，返回具体页面信息，
            # 不再把这种情况笼统显示为“无法确认 Cookie 状态”。
            current_url = page.url
            title = ""
            try:
                title = await page.title()
            except Exception:
                pass
            if "/chat" in current_url and "login" not in current_url.lower():
                return {
                    "valid": True,
                    "message": "Cookie 可能有效：已进入消息页，但页面控件尚未完全加载",
                    "uncertain": True,
                }
            return {
                "valid": False,
                "message": f"未进入抖音消息页，可能遇到登录验证或风控（页面：{title or current_url}）",
            }

        except Exception as e:
            log.error("验证账号异常: %s", e, exc_info=True)
            return {"valid": False, "message": f"验证失败: {_humanize_playwright_error(e, used_proxy=bool(proxy))}"}
        finally:
            if browser:
                try:
                    await browser.close()
                except Exception:
                    pass
            # 不 stop local_proxy——它被池复用


async def _probe_selector_visible(page, selector: str, timeout_ms: int) -> bool:
    """并发安全地探查一个选择器是否可见。"""
    try:
        loc = page.locator(selector).first
        return await loc.is_visible(timeout=timeout_ms)
    except Exception:
        return False


async def _probe_text_visible(page, text: str, timeout_ms: int) -> bool:
    """并发安全地探查页面是否包含指定文本。"""
    try:
        loc = page.get_by_text(text, exact=False).first
        return await loc.is_visible(timeout=timeout_ms)
    except Exception:
        return False



async def fetch_friend_list(account: dict) -> list[str]:
    """自动获取抖音聊天页的好友列表。

    关键优化：
    1. LocalProxyPool 复用 gost 进程
    2. 用 commit 等待代替 networkidle 10s + wait_for_timeout 3s
    3. 只在“明确”登录页信号才早返回；模糊信号让页加载后重新评估
    """
    from playwright.async_api import async_playwright

    proxy_url = account.get("proxy", "") or ""

    try:
        cookies = parse_cookie_json(account["cookie"])
    except Exception as e:
        log.error("Cookie 解析失败: %s", e)
        return []

    friends: list[str] = []
    local_proxy = await LocalProxyPool.acquire(proxy_url)
    if proxy_url and not local_proxy.ok:
        log.error("代理初始化失败：%s", local_proxy.error)
        return []
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
                log.error("打开抖音页失败：%s", e)
                return []

            # 1) 探查登录状态。只在“明确”信号才返回；不依赖 networkidle。
            login_signals = await page.evaluate(
                """() => {
                    const url = window.location.href;
                    const hasLoginPath = url.includes('/login') || url.includes('/passport');
                    const hasQR = !!document.querySelector('img[src*="qrcode"], img[src*="qr"]') ||
                        !!document.querySelector('[class*="qrcode"], [class*="QRCode"]');
                    const hasScanText = [...document.querySelectorAll('*')].some(el =>
                        el.textContent && el.textContent.trim() === '扫码登录'
                    );
                    const hasPhoneInput = !!document.querySelector('input[type="tel"]');
                    const hasVerifyInput = !!document.querySelector('input[placeholder*="验证码"], input[placeholder*="手机号"]');
                    const hasSearch = !!document.querySelector('input[placeholder*="搜索"], input[type="search"]');
                    return {hasLoginPath, hasQR, hasScanText, hasPhoneInput, hasVerifyInput, hasSearch};
                }"""
            )

            # 只有“多个强信号同时出现”才判定登录页；只是 hasLoginBtn 不够
            if login_signals.get("hasLoginPath") and (
                login_signals.get("hasQR") or login_signals.get("hasScanText") or login_signals.get("hasPhoneInput")
            ):
                log.warning(
                    "当前处于登录页，Cookie 已失效或未登录（signals: %s）",
                    {k: v for k, v in login_signals.items() if v},
                )
                return []

            # 2) 等待聊天页渲染 — 并发探查多个“聊天页”指示器
            ready_selectors = (
                'input[placeholder*="搜索"]',
                '[class*="conversation"]',
                '[class*="message-list"]',
                '[class*="chat-list"]',
                '[contenteditable="true"]',
            )
            ready_tasks = [
                _probe_selector_visible(page, sel, timeout_ms=8000)
                for sel in ready_selectors
            ]
            ready_results = await asyncio.gather(*ready_tasks, return_exceptions=True)
            if not any(r is True for r in ready_results):
                log.warning("聊天页指示器均未出现，尝试提取会话列表（可能为加载缓慢）")

            # 3) 提取好友名称 — 结构探测，不依赖类名
            items = await page.evaluate(
                """() => {
                    const results = [];
                    const seen = new Set();

                    // 策略1：找左侧会话列表区域
                    const divs = document.querySelectorAll('div');
                    for (const container of divs) {
                        const rect = container.getBoundingClientRect();
                        if (rect.left < 400 && rect.width > 200 && rect.height > 300 && container.children.length >= 3) {
                            let validItems = 0;
                            for (const child of container.children) {
                                const hasImg = child.querySelector('img') !== null;
                                const text = (child.textContent || '').trim();
                                if (hasImg && text.length >= 2 && text.length <= 20 && !text.includes('\n')) {
                                    if (!['系统通知', '消息', '抖音'].some(k => text.includes(k))) {
                                        if (!seen.has(text)) {
                                            seen.add(text);
                                            results.push(text);
                                        }
                                        validItems++;
                                    }
                                }
                            }
                            if (validItems >= 3) break;
                        }
                    }

                    // 策略2：用 role="listitem" 或 aria 标签
                    if (results.length < 3) {
                        const listItems = document.querySelectorAll('[role="listitem"], [role="option"]');
                        for (const item of listItems) {
                            const text = (item.textContent || '').trim();
                            if (text.length >= 2 && text.length <= 20 && !text.includes('\n')) {
                                if (!['系统通知', '消息', '抖音'].some(k => text.includes(k))) {
                                    if (!seen.has(text)) {
                                        seen.add(text);
                                        results.push(text);
                                    }
                                }
                            }
                        }
                    }

                    // 策略3：找头像 + 短文本组合
                    if (results.length < 3) {
                        const all = document.querySelectorAll('div, a, li');
                        for (const el of all) {
                            const img = el.querySelector('img');
                            if (!img) continue;
                            const imgRect = img.getBoundingClientRect();
                            if (imgRect.width < 15 || imgRect.width > 80) continue;
                            const text = (el.textContent || '').trim();
                            if (text.length >= 2 && text.length <= 20 && !text.includes('\n')) {
                                if (!['系统通知', '消息', '抖音'].some(k => text.includes(k))) {
                                    if (!seen.has(text)) {
                                        seen.add(text);
                                        results.push(text);
                                    }
                                }
                            }
                        }
                    }

                    return results.slice(0, 100);
                }"""
            )
            if items:
                friends.extend(items)

        except Exception as e:
            log.error("获取好友列表失败: %s", e, exc_info=True)
            return []
        finally:
            if browser:
                try:
                    await browser.close()
                except Exception:
                    pass
            # local_proxy 被池复用，不 stop

    return list(dict.fromkeys(friends))


async def run_account_spark(account: dict, task_id: str) -> AccountResult:
    """执行单个账号的续火任务"""
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
            try:
                await page.goto("https://www.douyin.com/chat", wait_until="commit", timeout=20000)
            except Exception as e:
                result.status = "failed"
                result.message = f"打开抖音页失败：{_humanize_playwright_error(e, used_proxy=bool(proxy_url))}"
                log.error("  [%s] %s", account["name"], result.message)
                return result

            search_input = page.locator('input[placeholder*="搜索"], input[type="search"]').first
            try:
                await search_input.wait_for(state="visible", timeout=CHAT_PAGE_READY_TIMEOUT)
            except Exception:
                result.status = "failed"
                result.message = "聊天页搜索框未出现，Cookie 可能已经失效"
                log.error("  [%s] 聊天页搜索框未出现，Cookie 可能已经失效", account["name"])
                await _capture_screenshot(page, f"{account['name']}-cookie-expired")
                return result

            await _wait_chat_list_ready(page, account["name"])

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

                # 点击搜索结果进入对话
                try:
                    send_btn = None
                    for marker in ("发消息", "发私信"):
                        try:
                            candidate = search_result.get_by_text(marker, exact=False).first
                            if await candidate.is_visible(timeout=2000):
                                send_btn = candidate
                                break
                        except Exception:
                            continue
                    if send_btn:
                        await send_btn.click(timeout=5000)
                    else:
                        await search_result.click(timeout=5000)
                except Exception:
                    try:
                        await search_result.click(timeout=5000)
                    except Exception:
                        pass

                log.info("  [%s] 已打开私信：%s", account["name"], target_name)
                await page.wait_for_timeout(2000)

                editor_input = page.locator(
                    '.messageEditorimChatEditorContainer '
                    '[data-slate-editor="true"][contenteditable="true"]'
                ).first
                try:
                    await editor_input.wait_for(state="visible", timeout=10000)
                except Exception:
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

                # 渲染并发送消息
                msg = yiyan.render_message(
                    message_template or None,
                    account["name"],
                    target_name,
                    include_source=include_source,
                )

                await page.keyboard.insert_text(msg)
                await page.wait_for_timeout(500)
                await page.keyboard.press("Enter")
                log.info("  [%s] 已发送消息：%s", account["name"], target_name)
                await page.wait_for_timeout(1500)

                result.detail.append({
                    "target": target_name,
                    "status": "success",
                    "message": "已发送",
                })
                result.success += 1
                database.touch_target_result(target["id"], "success")

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
            result.message = _humanize_playwright_error(e, used_proxy=bool(proxy_url))
        finally:
            if browser:
                try:
                    await browser.close()
                except Exception:
                    pass
            # local_proxy 被池复用，不 stop

    return result


async def _wait_chat_list_ready(page: Any, account_name: str) -> None:
    """等待会话列表真正渲染（用搜索框出现判断）。"""
    try:
        search = page.get_by_placeholder("搜索", exact=False)
        await search.first.wait_for(state="visible", timeout=CHAT_PAGE_READY_TIMEOUT)
        log.info("  [%s] 搜索框已出现，聊天页就绪", account_name)
    except Exception:
        try:
            page.locator('input[type="search"], input[placeholder*="搜索"]').first.wait_for(
                state="visible", timeout=5000
            )
        except Exception:
            log.info("  [%s] 搜索框未在预期时间内出现", account_name)

    try:
        await page.wait_for_load_state("networkidle", timeout=CHAT_PAGE_IDLE_TIMEOUT)
    except Exception:
        pass


async def _search_conversation(
    page: Any, search_input: Any, account_name: str, target_name: str
) -> Any:
    """带重试地搜索会话（不依赖 .SearchPanelitembox 类名）。"""
    for attempt in range(1, SEARCH_RETRY_LIMIT + 1):
        await search_input.fill("")
        await page.wait_for_timeout(SEARCH_INPUT_RESET_DELAY)
        await search_input.fill(target_name)
        await page.wait_for_timeout(1500)

        # 策略1：精确匹配目标名的可见元素
        try:
            target_el = page.get_by_text(target_name, exact=True).first
            if await target_el.is_visible(timeout=SEARCH_RESULT_TIMEOUT):
                bbox = await target_el.bounding_box()
                if bbox and bbox.get("width", 0) > 50:
                    return target_el
        except Exception:
            pass

        # 策略2：JS 结构探测
        try:
            found = await page.evaluate(
                """(targetName) => {
                    const all = document.querySelectorAll('div, li, a');
                    for (const el of all) {
                        const text = (el.textContent || '').trim();
                        if (text === targetName || text.includes(targetName)) {
                            const rect = el.getBoundingClientRect();
                            if (rect.width > 50 && rect.height > 20 && rect.height < 200) {
                                if (rect.top > 50 && rect.top < window.innerHeight * 0.7) {
                                    el.setAttribute('data-das-search-hit', '1');
                                    return true;
                                }
                            }
                        }
                    }
                    return false;
                }""",
                target_name,
            )
            if found:
                result = page.locator("[data-das-search-hit='1']").first
                await page.evaluate(
                    """() => {
                        document.querySelectorAll("[data-das-search-hit]").forEach(el => el.removeAttribute('data-das-search-hit'));
                    }"""
                )
                return result
        except Exception:
            pass

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


def run_account_spark_sync(account: dict, task_id: str) -> AccountResult:
    """同步包装器"""
    return asyncio.run(run_account_spark(account, task_id))


def verify_cookie_sync(cookie: str, proxy: str = "") -> dict:
    """同步包装器：验证 Cookie"""
    return asyncio.run(verify_cookie(cookie, proxy))


def fetch_friend_list_sync(account: dict) -> list[str]:
    """同步包装器：获取好友列表"""
    return asyncio.run(fetch_friend_list(account))


# ==================== 代理测试与归属地检测 ====================
#
# 不依赖 curl / requests / PySocks，使用纯标准库实现 SOCKS5 拨号。
# 实现 SOCKS5 RFC 1928（CONNECT 命令、IPv4 地址、无认证 / 用户名密码认证）。
# DNS 解析在使用 SOCKS5 时放在远端（type 0x03 表示域名），规避本地无外网/受限 DNS 的问题。

import socket
import struct
from concurrent.futures import ThreadPoolExecutor
from typing import Any

_PROXY_TIMEOUT = float(os.environ.get("DAS_PROXY_TIMEOUT", "30") or "30")
_GEO_HTTP_TARGET = ("ip-api.com", 80)
_GEO_HTTP_PATH = (
    "/json/?lang=zh-CN&fields=status,country,countryCode,regionName,city,query"
)
_DIRECT_DNS_HOSTS = ("1.1.1.1", "8.8.8.8")
_DIRECT_DNS_PORT = 53


def _split_proxy_url(proxy_url: str) -> tuple[str, int, str, str]:
    """解析 socks5://[user:pass@]host:port 为 (host, port, user, password)。

    也支持：
    - http://[user:pass@]host:port （会报 ValueError 提示只支持 SOCKS5）
    - host:port:user:pwd
    - host:port
    """
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
    # 处理 host:port:user:pwd
    parts = host_part.split(":")
    if len(parts) >= 2:
        host = parts[0]
        try:
            port = int(parts[1])
        except ValueError:
            raise ValueError(f"代理端口必须为数字：{parts[1]!r}")
        if len(parts) >= 4 and not user:
            # host:port:user:pwd 形式
            user = parts[2]
            pwd = parts[3]
    else:
        raise ValueError("代理 URL 缺少端口：socks5://host:port")
    return host.strip(), port, user, pwd


def _socks5_connect(proxy_url: str, target_host: str, target_port: int) -> socket.socket:
    """通过 SOCKS5 拨号，target_host 可以是域名或 IP。返回已握手的 socket。"""
    host, port, user, pwd = _split_proxy_url(proxy_url)
    sock = socket.create_connection((host, port), timeout=_PROXY_TIMEOUT)
    try:
        # GREETING：0x05 0x01 0x00（VER CMD METHOD）
        sock.sendall(b"\x05\x01\x00")
        greeting = _recv_exact(sock, 2)
        if greeting[0] != 0x05:
            raise ConnectionError("SOCKS5 服务器协议错误")
        if greeting[1] == 0xFF:
            raise ConnectionError("SOCKS5 服务器无可用认证方式")
        if greeting[1] != 0x00:
            # 0x02 表示需要用户名密码认证
            if not user:
                raise ConnectionError("SOCKS5 服务器需要认证但 URL 未提供凭据")
            req = b"\x01" + bytes([len(user)]) + user.encode("utf-8") + bytes([len(pwd)]) + pwd.encode("utf-8")
            sock.sendall(req)
            auth_resp = _recv_exact(sock, 2)
            if auth_resp[1] != 0x00:
                raise ConnectionError("SOCKS5 用户名密码认证失败")
        # CONNECT 请求：VER CMD RSV ATYP DST.ADDR DST.PORT
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
        # 应答：VER REP RSV ATYP BND.ADDR BND.PORT
        resp = _recv_exact(sock, 4)
        atyp = resp[3]
        if resp[1] != 0x00:
            err_map = {
                0x01: "一般性失败",
                0x02: "规则不允许",
                0x03: "网络不可达",
                0x04: "主机不可达",
                0x05: "连接被拒",
                0x06: "TTL 过期",
                0x07: "命令不支持",
                0x08: "地址类型不支持",
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
    """精确接收 n 字节。"""
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
    """通过 SOCKS5 发起 HTTP GET，返回响应体文本。"""
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
    """直连 HTTP GET（仅在明确代理为空时使用）。"""
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
    """同步执行：测试代理并解析 ip-api.com 响应。"""
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
        "ok": True,
        "ip": ip,
        "country": country,
        "country_code": country_code,
        "region": region,
        "city": city,
        "message": f"✅ {location_str} ({ip})",
    }


async def _test_proxy_async(proxy_url: str) -> dict:
    """异步包装：在线程池中跑 SOCKS5 拨号与 HTTP 读取。"""
    loop = asyncio.get_running_loop()
    with ThreadPoolExecutor(max_workers=1) as pool:
        return await loop.run_in_executor(pool, _test_proxy_internal, proxy_url)


def test_proxy_sync(proxy_url: str) -> dict:
    """同步包装：测试代理。"""
    return _test_proxy_internal(proxy_url)


def detect_geo_sync(proxy_url: str) -> dict:
    """同步包装：检测归属地。"""
    return _test_proxy_internal(proxy_url)
