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
    """解析 SOCKS5 代理 URL 为 Playwright proxy 配置"""
    if not proxy_url:
        return None
    try:
        m = re.match(r'socks5://(?:(?P<user>[^:@]+):(?P<pass>[^@]*)@)?(?P<host>[^:]+):(?P<port>\d+)', proxy_url)
        if not m:
            return None
        proxy = {"server": f"socks5://{m.group('host')}:{m.group('port')}"}
        if m.group("user"):
            proxy["username"] = m.group("user")
        if m.group("pass"):
            proxy["password"] = m.group("pass")
        return proxy
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
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(proxy=_parse_proxy_url(proxy))
            await context.add_cookies([c.to_playwright_cookie() for c in cookies])
            page = await context.new_page()
            await page.goto("https://www.douyin.com/chat", wait_until="domcontentloaded")

            search_input = page.locator('input.semi-input[placeholder="搜索"]').first()
            try:
                await search_input.wait_for(state="visible", timeout=15000)
                return {"valid": True, "message": "Cookie 有效"}
            except Exception:
                pass

            try:
                login_btn = page.locator('text=登录, text=扫码登录').first()
                if await login_btn.is_visible(timeout=3000):
                    return {"valid": False, "message": "Cookie 已失效，需要重新登录"}
            except Exception:
                pass

            return {"valid": False, "message": "无法确认 Cookie 状态"}

        except Exception as e:
            return {"valid": False, "message": f"验证失败: {e}"}
        finally:
            if browser:
                await browser.close()


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
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(proxy=_parse_proxy_url(proxy_url))
            await context.add_cookies([c.to_playwright_cookie() for c in cookies])
            page = await context.new_page()
            await page.goto("https://www.douyin.com/chat", wait_until="domcontentloaded")

            search_input = page.locator('input.semi-input[placeholder="搜索"]').first()
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
                    name_el = item.locator('[class*="name"], [class*="Name"], [class*="title"], [class*="Title"]').first()
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
            log.error("获取好友列表失败: %s", e)
        finally:
            if browser:
                await browser.close()

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
    include_source = database.get_setting("yiyan_include_source", "1") == "1"

    async with async_playwright() as p:
        browser = None
        try:
            browser_path = os.environ.get("PLAYWRIGHT_BROWSER_PATH", "").strip() or None
            headless = os.environ.get("PLAYWRIGHT_HEADLESS", "1") != "0"

            browser = await p.chromium.launch(
                headless=headless,
                **({"executablePath": browser_path} if browser_path else {}),
            )

            context = await browser.new_context(proxy=_parse_proxy_url(proxy_url))
            await context.add_cookies([c.to_playwright_cookie() for c in cookies])

            page = await context.new_page()
            await page.goto("https://www.douyin.com/chat", wait_until="domcontentloaded")

            search_input = page.locator('input.semi-input[placeholder="搜索"]').first()
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
                    send_btn = search_result.locator('text=发消息, text=发私信').first()
                    if await send_btn.is_visible(timeout=3000):
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

                # 定位输入框
                editor_input = None
                selectors = [
                    '.messageEditorimChatEditorContainer [data-slate-editor="true"][contenteditable="true"]',
                    '[data-slate-editor="true"][contenteditable="true"]',
                    '[contenteditable="true"][data-slate-editor="true"]',
                    '.public-DraftEditor-content',
                    '[contenteditable="true"]',
                ]
                for sel in selectors:
                    try:
                        editor_input = page.locator(sel).first()
                        if await editor_input.is_visible(timeout=3000):
                            break
                    except Exception:
                        continue

                if not editor_input:
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
            result.message = str(e)
        finally:
            if browser:
                await browser.close()

    return result


async def _wait_chat_list_ready(page: Any, account_name: str) -> None:
    """等待会话列表真正渲染"""
    try:
        conversation_locator = page.locator('[class*="conversation"], [class*="Conversation"]').first()
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
            await page.locator(".SearchPanelitembox").first().wait_for(
                state="hidden", timeout=SEARCH_RESULT_TIMEOUT
            )
        except Exception:
            pass
        await page.wait_for_timeout(SEARCH_INPUT_RESET_DELAY)
        await search_input.fill(target_name)

        try:
            search_result = page.locator(".SearchPanelitembox").filter(
                has=page.get_by_text(target_name, exact=True)
            ).first()
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

async def _test_proxy_async(proxy_url: str) -> dict:
    """异步测试代理并获取归属地（通过 ip-api.com）"""
    if not proxy_url:
        return {"ok": False, "message": "代理 URL 为空"}

    proxy = _parse_proxy_url(proxy_url)
    if not proxy:
        return {"ok": False, "message": "代理 URL 解析失败"}

    try:
        import urllib.request
        # 构造代理 handler
        proxy_handler = urllib.request.ProxyHandler({
            "http": proxy_url,
            "https": proxy_url,
        })
        opener = urllib.request.build_opener(proxy_handler)
        opener.addheaders = [("User-Agent", "Mozilla/5.0")]
        urllib.request.install_opener(opener)

        # ip-api.com 返回 JSON，包含 country/region/city 等
        req = urllib.request.Request(
            "http://ip-api.com/json/?lang=zh-CN&fields=status,country,countryCode,regionName,city,query"
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        if data.get("status") != "success":
            return {"ok": False, "message": "归属地查询失败"}

        ip = data.get("query", "")
        country = data.get("country", "")
        country_code = data.get("countryCode", "")
        region = data.get("regionName", "")
        city = data.get("city", "")

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
    except Exception as e:
        return {"ok": False, "message": f"测试失败: {e}"}


def test_proxy_sync(proxy_url: str) -> dict:
    """同步包装器：测试代理"""
    return asyncio.run(_test_proxy_async(proxy_url))


def detect_geo_sync(proxy_url: str) -> dict:
    """同步包装器：检测归属地"""
    return asyncio.run(_test_proxy_async(proxy_url))
