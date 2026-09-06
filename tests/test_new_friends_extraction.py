"""测试新的好友列表提取策略。"""
import asyncio
import pytest
from playwright.async_api import async_playwright

from app import douyin_runner


def test_new_extraction_handles_name_with_chinese_suffix():
    """好友名包含「抖音」等关键字时不应被误过滤。"""
    html = '''<html><body>
    <div class="chat-item" style="width:300px;display:flex;align-items:center;padding:8px">
      <img src="x" style="width:40px;height:40px"/>
      <div class="name" style="margin-left:10px">好友A的抖音</div>
    </div>
    <div class="chat-item" style="width:300px;display:flex;align-items:center;padding:8px">
      <img src="x" style="width:40px;height:40px"/>
      <div class="name" style="margin-left:10px">好友B</div>
    </div>
    <div class="chat-item" style="width:300px;display:flex;align-items:center;padding:8px">
      <img src="x" style="width:40px;height:40px"/>
      <div class="name" style="margin-left:10px">系统通知</div>
    </div>
    </body></html>'''
    asyncio.run(_check(html, ['好友A的抖音', '好友B']))


def test_new_extraction_filters_system_messages():
    """系统通知等 UI 元素被过滤。"""
    html = '''<html><body>
    <div class="chat-item"><img style="width:30px;height:30px"/><div class="name">系统通知</div></div>
    <div class="chat-item"><img style="width:30px;height:30px"/><div class="name">系统消息</div></div>
    <div class="chat-item"><img style="width:30px;height:30px"/><div class="name">通知中心</div></div>
    <div class="chat-item"><img style="width:30px;height:30px"/><div class="name">抖音小助手</div></div>
    <div class="chat-item"><img style="width:30px;height:30px"/><div class="name">真实好友</div></div>
    </body></html>'''
    asyncio.run(_check(html, ['真实好友']))


def test_new_extraction_handles_role_based():
    """role=listitem 元素也能提取。"""
    html = '''<html><body>
    <ul role="list">
      <li role="listitem" style="width:200px"><img style="width:30px;height:30px"/><span>用户A</span></li>
      <li role="listitem" style="width:200px"><img style="width:30px;height:30px"/><span>用户B</span></li>
    </ul>
    </body></html>'''
    asyncio.run(_check(html, ['用户A', '用户B']))


def test_new_extraction_skips_short_text():
    """太短的文本被过滤。"""
    html = '''<html><body>
    <div class="chat-item"><img style="width:30px;height:30px"/><div class="name">X</div></div>
    <div class="chat-item"><img style="width:30px;height:30px"/><div class="name">有效名字</div></div>
    </body></html>'''
    asyncio.run(_check(html, ['有效名字']))


async def _check(html: str, expected: list):
    """用 Chrome 跑 evaluate，验证提取结果。"""
    # 提取新 evaluate 的 JS
    import re
    with open('app/douyin_runner.py', 'r', encoding='utf-8') as f:
        content = f.read()
    pattern = re.compile(
        r'items = await page\.evaluate\(\s*"""\(\) => \{.*?return results\.slice\(0, 100\);\s*\}\s*""",?\s*\)',
        re.DOTALL
    )
    m = pattern.search(content)
    assert m, "items evaluate block not found"
    full_block = m.group(0)
    # 提取 JS 部分
    js_match = re.search(r'"""(\(\) => \{.*?\})"""', full_block, re.DOTALL)
    js = js_match.group(1)
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=['--no-sandbox'])
        page = await browser.new_page()
        await page.set_content(html)
        result = await page.evaluate(js)
        await browser.close()
    
    # 验证期望的好友都被找到
    for name in expected:
        assert name in result, f"expected {name!r} in {result}"
    # 验证顺序（按 DOM 顺序）
    if len(expected) > 1:
        idxs = [result.index(n) for n in expected]
        assert idxs == sorted(idxs), f"order wrong: {result} vs {expected}"


if __name__ == '__main__':
    test_new_extraction_handles_name_with_chinese_suffix()
    test_new_extraction_filters_system_messages()
    test_new_extraction_handles_role_based()
    test_new_extraction_skips_short_text()
    print('all passed')
