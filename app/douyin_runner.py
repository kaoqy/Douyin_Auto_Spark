# 抖音自动续火花管理面板 - Playwright 自动化
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
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


async def verify_cookie(cookie: str, proxy: str = "") -> dict:
    """验证账号 Cookie 是否有效"""
    from playwright.async_api import async_playwright

    try:
        cookies = parse_cookie_json(cookie)
    except Exception as e:
        return {"valid": False, "message": f"Cookie 解析失败: {e}"}

    async with async_playwright() as p:
        browser = None
        try:
            launch_options = {"headless": True}
            proxy_config = _parse_proxy_url(proxy)
            if proxy_config:
                launch_options["proxy"] = proxy_config
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
            await page.goto("https://www.douyin.com/chat", wait_until="domcontentloaded")

            search_input = page.locator('input.semi-input[placeholder="搜索"]').first
            try:
                await search_input.wait_for(state="visible", timeout=15000)
                return {"valid": True, "message": "Cookie 有效"}
            except Exception:
                pass

            for marker in ("登录", "扫码登录", "立即登录", "二维码登录"):
                try:
                    btn = page.get_by_text(marker, exact=False).first
                    if await btn.is_visible(timeout=2000):
                        return {"valid": False, "message": "Cookie 已失效，需要重新登录"}
                except Exception:
                    continue

            return {"valid": False, "message": "无法确认 Cookie 状态"}

        except Exception as e:
            log.error("验证账号异常: %s", e, exc_info=True)
            return {"valid": False, "message": f"验证失败: {_humanize_playwright_error(e, used_proxy=bool(proxy))}"}
        finally:
            if browser:
                try:
                    await browser.close()
                except Exception:
                    pass


async def fetch_friend_list(account: dict) -> list[str]:
    """自动获取抖音聊天页的好友列表（带重试和多种选择器）"""
    from playwright.async_api import async_playwright

    proxy_url = account.get("proxy", "") or ""

    try:
        cookies = parse_cookie_json(account["cookie"])
    except Exception as e:
        log.error("Cookie 解析失败: %s", e)
        return []

    friends = []
    async with async_playwright() as p:
        browser = None
        try:
            launch_options = {"headless": True}
            proxy_config = _parse_proxy_url(proxy_url)
            if proxy_config:
                launch_options["proxy"] = proxy_config
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
            await page.goto("https://www.douyin.com/chat", wait_until="domcontentloaded")

            search_input = page.locator('input.semi-input[placeholder="搜索"]').first
            try:
                await search_input.wait_for(state="visible", timeout=15000)
            except Exception:
                log.warning("搜索框未出现，无法获取好友列表")
                return []

            # 等待会话列表渲染
            await page.wait_for_timeout(3000)

            # 多种选择器依次尝试
            selectors = [
                '[class*="conversationItem"]',
                '[class*="ConversationItem"]',
                '.SearchPanelitembox',
                '[class*="chatItem"]',
                '[class*="session-item"]',
                '[class*="sessionItem"]',
            ]

            conversation_items = []
            for sel in selectors:
                try:
                    items = page.locator(sel).all()
                    if items:
                        conversation_items = items
                        log.info("使用选择器 %s 找到 %d 个会话", sel, len(items))
                        break
                except Exception:
                    continue

            for item in conversation_items:
                try:
                    name_el = item.locator('[class*="name"], [class*="Name"], [class*="title"], [class*="Title"]').first
                    name = await name_el.text_content(timeout=2000)
                    if name and name.strip():
                        friends.append(name.strip())
                except Exception:
                    pass

            # 兜底：如果还没拿到，尝试取所有可见文本
            if not friends:
                log.info("主选择器未命中，尝试兜底文本提取")
                all_items = page.locator('.SearchPanelitembox, [class*="conversation"], [class*="chatItem"]').all()
                for item in all_items:
                    try:
                        text = await item.text_content(timeout=2000)
                        if text and len(text.strip()) > 0 and len(text.strip()) < 50:
                            friends.append(text.strip().split('\n')[0])
                    except Exception:
                        pass

        except Exception as e:
            log.error("获取好友列表失败: %s", e, exc_info=True)
            return []
        finally:
            if browser:
                try:
                    await browser.close()
                except Exception:
                    pass

    # 去重
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

    async with async_playwright() as p:
        browser = None
        try:
            browser_path = os.environ.get("PLAYWRIGHT_BROWSER_PATH", "").strip() or None
            headless = os.environ.get("PLAYWRIGHT_HEADLESS", "1") != "0"

            launch_options = {"headless": headless}
            if browser_path:
                launch_options["executable_path"] = browser_path
            proxy_config = _parse_proxy_url(proxy_url)
            if proxy_config:
                launch_options["proxy"] = proxy_config
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
            await page.goto("https://www.douyin.com/chat", wait_until="domcontentloaded")

            search_input = page.locator('input.semi-input[placeholder="搜索"]').first
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

    return result


async def _wait_chat_list_ready(page: Any, account_name: str) -> None:
    """等待会话列表真正渲染"""
    try:
        conversation_locator = page.locator('[class*="conversation"], [class*="Conversation"]').first
        await conversation_locator.wait_for(state="visible", timeout=CHAT_PAGE_READY_TIMEOUT)
    except Exception:
        log.info("  [%s] 会话列表未在预期时间内出现，将依赖搜索重试兜底", account_name)

    try:
        await page.wait_for_load_state("networkidle", timeout=CHAT_PAGE_IDLE_TIMEOUT)
    except Exception:
        pass


async def _search_conversation(
    page: Any, search_input: Any, account_name: str, target_name: str
) -> Any:
    """带重试地搜索会话"""
    for attempt in range(1, SEARCH_RETRY_LIMIT + 1):
        await search_input.fill("")
        try:
            await page.locator(".SearchPanelitembox").first.wait_for(
                state="hidden", timeout=SEARCH_RESULT_TIMEOUT
            )
        except Exception:
            pass
        await page.wait_for_timeout(SEARCH_INPUT_RESET_DELAY)
        await search_input.fill(target_name)

        try:
            search_result = page.locator(".SearchPanelitembox").filter(
                has=page.get_by_text(target_name, exact=True)
            ).first
            await search_result.wait_for(state="visible", timeout=SEARCH_RESULT_TIMEOUT)
            return search_result
        except Exception:
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
