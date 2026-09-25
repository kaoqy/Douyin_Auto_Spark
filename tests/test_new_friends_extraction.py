"""Test the new friend-list extraction strategy.

Skipped when Playwright chromium is not available (e.g. CI containers
that only pip install without ``playwright install chromium``).
"""
import asyncio
import re

import pytest

playwright = pytest.importorskip("playwright.sync_api", reason="playwright not installed")
from playwright.async_api import async_playwright  # noqa: E402

from app import douyin_runner  # noqa: E402


def _chromium_available() -> bool:
    try:
        with playwright.sync_playwright() as p:
            b = p.chromium.launch(headless=True, args=["--no-sandbox"])
            b.close()
            return True
    except Exception:
        return False


if not _chromium_available():
    pytest.skip("Playwright chromium not installed; run `playwright install chromium`", allow_module_level=True)


def test_extraction_uses_conversation_item_selector():
    """提取逻辑使用 [data-e2e=conversation-item] + .conversationConversationItemtitle。"""
    html = '<html><body>' \
        '<div data-e2e="conversation-item" style="width:300px;display:flex;align-items:center;padding:8px">' \
        '<img src="x" style="width:40px;height:40px"/>' \
        '<span class="conversationConversationItemtitle" style="margin-left:10px">好友A</span></div>' \
        '<div data-e2e="conversation-item" style="width:300px;display:flex;align-items:center;padding:8px">' \
        '<img src="x" style="width:40px;height:40px"/>' \
        '<span class="conversationConversationItemtitle" style="margin-left:10px">好友B的抖音</span></div>' \
        '<div data-e2e="conversation-item" style="width:300px;display:flex;align-items:center;padding:8px">' \
        '<img src="x" style="width:40px;height:40px"/>' \
        '<span class="conversationConversationItemtitle" style="margin-left:10px">系统通知</span></div>' \
        '</body></html>'
    asyncio.run(_check(html, ["好友A", "好友B的抖音"]))


def test_extraction_filters_group_chats():
    """标题含逗号的群聊被过滤。"""
    html = '<html><body>' \
        '<div data-e2e="conversation-item"><img/><span class="conversationConversationItemtitle">张三, 李四</span></div>' \
        '<div data-e2e="conversation-item"><img/><span class="conversationConversationItemtitle">正常好友</span></div>' \
        '<div data-e2e="conversation-item"><img/><span class="conversationConversationItemtitle">王五，赵六</span></div>' \
        '</body></html>'
    asyncio.run(_check(html, ["正常好友"]))


def test_extraction_filters_system_accounts():
    """系统账号和通知被过滤。"""
    html = '<html><body>' \
        '<div data-e2e="conversation-item"><img/><span class="conversationConversationItemtitle">系统通知</span></div>' \
        '<div data-e2e="conversation-item"><img/><span class="conversationConversationItemtitle">抖音小助手</span></div>' \
        '<div data-e2e="conversation-item"><img/><span class="conversationConversationItemtitle">互动消息</span></div>' \
        '<div data-e2e="conversation-item"><img/><span class="conversationConversationItemtitle">真实好友</span></div>' \
        '<div data-e2e="conversation-item"><img/><span class="conversationConversationItemtitle">抖音官方</span></div>' \
        '</body></html>'
    asyncio.run(_check(html, ["真实好友"]))


def test_extraction_filters_short_and_numeric():
    """太短或纯数字的标题被过滤。"""
    html = '<html><body>' \
        '<div data-e2e="conversation-item"><img/><span class="conversationConversationItemtitle">X</span></div>' \
        '<div data-e2e="conversation-item"><img/><span class="conversationConversationItemtitle">123</span></div>' \
        '<div data-e2e="conversation-item"><img/><span class="conversationConversationItemtitle">有效好友名</span></div>' \
        '<div data-e2e="conversation-item"><img/><span class="conversationConversationItemtitle">A</span></div>' \
        '</body></html>'
    asyncio.run(_check(html, ["有效好友名"]))


def test_extraction_empty_chat_list():
    """空聊天列表返回空数组。"""
    html = "<html><body></body></html>"
    asyncio.run(_check(html, []))


async def _check(html: str, expected: list):
    """提取 evaluate 中的 JS 并在测试 HTML 上运行。"""
    import re
    with open("app/douyin_runner.py", "r", encoding="utf-8") as f:
        content = f.read()
    # Match the new evaluate block format: function() { ... }
    pattern = re.compile(
        r"items = await page\.evaluate\(\s*function\(\) \{(.*?)\}\s*\)",
        re.DOTALL
    )
    m = pattern.search(content)
    assert m, "items evaluate block not found in douyin_runner.py"
    js_body = m.group(1)
    # Wrap into a callable function
    js = "(function() {" + js_body + "})"

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
        page = await browser.new_page()
        await page.set_content(html)
        result = await page.evaluate(js)
        await browser.close()

    # 验证期望的好友都被找到
    for name in expected:
        assert name in result, f"expected {name!r} in {result}"
    # 过滤掉的元素不应出现
    forbidden = {"系统通知", "抖音小助手", "互动消息", "抖音官方", "张三, 李四", "王五，赵六"}
    for name in forbidden:
        assert name not in result, f"unexpected {name!r} in {result}"
    # 顺序（按 DOM 顺序）
    if len(expected) > 1:
        idxs = [result.index(n) for n in expected]
        assert idxs == sorted(idxs), f"order wrong: {result} vs {expected}"


if __name__ == "__main__":
    test_extraction_uses_conversation_item_selector()
    test_extraction_filters_group_chats()
    test_extraction_filters_system_accounts()
    test_extraction_filters_short_and_numeric()
    test_extraction_empty_chat_list()
    print("all passed")
