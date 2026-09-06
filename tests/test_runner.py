"""续火核心逻辑的隔离单元测试，不访问真实抖音账号。"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app import douyin_runner
from app.message_templates import needs_yiyan, normalize_template, render_template


def test_parse_authenticated_socks5_proxy():
    assert douyin_runner._parse_proxy_url("socks5://user:pass@127.0.0.1:1080") == {
        "server": "socks5://127.0.0.1:1080",
        "username": "user",
        "password": "pass",
    }


def test_parse_plain_socks5_proxy():
    assert douyin_runner._parse_proxy_url("socks5://127.0.0.1:1080") == {
        "server": "socks5://127.0.0.1:1080"
    }


def test_parse_invalid_proxy_returns_none():
    # 只有乱码才会被拒绝
    for t in ["not a url", "@@@", "abc:def", "1.2.3.4:abc", "1.2.3.4"]:
        assert douyin_runner._parse_proxy_url(t) is None, t
    # http/https 现在也支持
    r = douyin_runner._parse_proxy_url("http://127.0.0.1:8080")
    assert r == {"server": "http://127.0.0.1:8080"}


def test_normalize_template_rejects_unknown_placeholder():
    with pytest.raises(ValueError, match=r"\{\{unknown\}\}"):
        normalize_template("你好 {{unknown}}")


def test_normalize_template_supports_literal_newline():
    assert normalize_template(r"第一行\n第二行") == "第一行\n第二行"


def test_needs_yiyan_matches_upstream_behavior():
    assert needs_yiyan(None) is True
    assert needs_yiyan("{{friend}}，你好") is False
    assert needs_yiyan("{{friend}}：{{yiyan}}") is True
    assert needs_yiyan("来源：{{ from }}") is True


def test_render_template_uses_shanghai_timezone_and_spacing():
    result = render_template(
        "{{ friend }}|{{account}}|{{yiyan}}|{{from}}|{{date}}|{{time}}",
        "账号A",
        "好友B",
        {"hitokoto": "测试一言", "source": "测试出处"},
        now=datetime(2026, 9, 5, 6, 0, tzinfo=timezone.utc),
    )
    assert result == "好友B|账号A|测试一言|测试出处|2026-09-05|14:00"


class _FakeScreenshotPage:
    def __init__(self, closed: bool):
        self.closed = closed
        self.calls = []

    def is_closed(self):
        return self.closed

    async def screenshot(self, **kwargs):
        self.calls.append(kwargs)


@pytest.mark.anyio
async def test_capture_screenshot_skips_closed_page():
    page = _FakeScreenshotPage(closed=True)
    await douyin_runner._capture_screenshot(page, "账号/A")
    assert page.calls == []

