# 抖音自动续火花管理面板 - Playwright 自动化
from __future__ import annotations

import asyncio
import logging
import os
import shutil
import tempfile
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
class RunResult:
    """单次续火结果"""
    status: str = "pending"          # success / failed / skipped
    channel: str = "direct"          # direct / socks
    message: str = ""
    total: int = 0
    success: int = 0
    fail: int = 0
    detail: list[dict] = field(default_factory=list)


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


def _now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _safe_channel_label(channel: str, proxy_url: str) -> str:
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


async def run_account_spark(account: dict, task_id: str) -> AccountResult:
    """执行单个账号的续火任务"""
    from playwright.async_api import async_playwright, Browser, Page, Locator

    result = AccountResult(
        account_id=account["id"],
        account_name=account["name"],
    )

    proxy_url = account.get("proxy", "") or ""
    if proxy_url:
        result.channel = "socks"

    proxy_label = _safe_proxy_label(proxy_url)
    log.info("👤 [%s] 账号：%s", proxy_label, account["name"])

    # 获取该账号启用的好友
    targets = database.get_enabled_targets(account["id"])
    if not targets:
        result.status = "skipped"
        result.message = "没有启用的好友"
        log.info("  [%s] 没有启用的好友，跳过", account["name"])
        return result

    result.total = len(targets)

    # 解析 Cookie
    try:
        cookies = parse_cookie_json(account["cookie"])
    except Exception as e:
        result.status = "failed"
        result.message = f"Cookie 解析失败：{e}"
        log.error("  [%s] Cookie 解析失败：%s", account["name"], e)
        return result

    # 获取消息模板
    message_template = database.get_setting("message_template", "")
    include_source = database.get_setting("yiyan_include_source", "1") == "1"

    async with async_playwright() as p:
        browser_path = os.environ.get("PLAYWRIGHT_BROWSER_PATH", "").strip() or None
        headless = os.environ.get("PLAYWRIGHT_HEADLESS", "1") != "0"

        browser: Browser | None = None
        try:
            browser = await p.chromium.launch(
                headless=headless,
                **({"executablePath": browser_path} if browser_path else {}),
            )

            context = await browser.new_context()
            await context.add_cookies([c.to_playwright_cookie() for c in cookies])

            page = await context.new_page()
            await page.goto("https://www.douyin.com/chat", wait_until="domcontentloaded")

            # 等待搜索框出现
            search_input = page.locator('input.semi-input[placeholder="搜索"]').first()
            search_visible = await search_input.wait_for(
                state="visible", timeout=CHAT_PAGE_READY_TIMEOUT
            ).then(lambda: True).catch(lambda: False)

            if not search_visible:
                result.status = "failed"
                result.message = "聊天页搜索框未出现，Cookie 可能已经失效"
                log.error("  [%s] 聊天页搜索框未出现，Cookie 可能已经失效", account["name"])
                await _capture_screenshot(page, f"{account['name']}-cookie-expired")
                return result

            # 等待会话列表就绪
            await _wait_chat_list_ready(page, account["name"])

            # 依次处理每个好友
            missing_names: list[str] = []
            for target in targets:
                target_name = target["name"]
                log.info("  [%s] 开始搜索会话：%s", account["name"], target_name)

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

                # 点击「发消息」
                try:
                    await search_result.get_by_text(r"^(发消息|发私信)$").click(timeout=5000)
                except Exception:
                    # 备用：直接点击搜索结果
                    await search_result.click(timeout=5000)

                log.info("  [%s] 已打开私信：%s", account["name"], target_name)

                # 定位输入框
                editor_input = page.locator(
                    '.messageEditorimChatEditorContainer [data-slate-editor="true"][contenteditable="true"]'
                ).first()
                await editor_input.wait_for(state="visible", timeout=10000)
                await editor_input.click()

                # 渲染消息
                msg = yiyan.render_message(
                    message_template or None,
                    account["name"],
                    target_name,
                    include_source=include_source,
                )

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

            await page.wait_for_timeout(5000)

            # 汇总
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
    search_result = page.locator(".SearchPanelitembox").filter(
        has=page.get_by_text(target_name, exact=True)
    ).first()

    for attempt in range(1, SEARCH_RETRY_LIMIT + 1):
        await search_input.fill("")
        # 等旧结果消失
        try:
            await page.locator(".SearchPanelitembox").first().wait_for(
                state="hidden", timeout=SEARCH_RESULT_TIMEOUT
            )
        except Exception:
            pass
        await page.wait_for_timeout(SEARCH_INPUT_RESET_DELAY)
        await search_input.fill(target_name)

        try:
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
