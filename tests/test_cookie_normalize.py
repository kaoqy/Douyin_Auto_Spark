"""Cookie 字段归一化与 Playwright cookie 转换测试。"""
import json
import pytest

from app.douyin_cookie import (
    DEFAULT_COOKIE_DOMAIN,
    DEFAULT_COOKIE_PATH,
    DouyinCookieItem,
    cookies_to_json,
    parse_cookie_json,
)


def test_parse_minimal_cookie():
    """只提供 name+value 的最简 cookie，应自动补全 domain/path/sameSite。"""
    items = parse_cookie_json(json.dumps([{"name": "sessionid", "value": "abc"}]))
    assert len(items) == 1
    assert items[0].name == "sessionid"
    assert items[0].value == "abc"
    assert items[0].domain == DEFAULT_COOKIE_DOMAIN
    assert items[0].path == DEFAULT_COOKIE_PATH
    assert items[0].sameSite == "Lax"


def test_parse_with_domain():
    items = parse_cookie_json(
        json.dumps([{"name": "x", "value": "y", "domain": "https://www.douyin.com"}])
    )
    assert items[0].domain == "https://www.douyin.com"


def test_to_playwright_minimal_has_url_or_domain():
    """最少 cookie 必能被 Playwright 接受：有 domain 或 url。"""
    item = DouyinCookieItem.from_dict({"name": "sessionid", "value": "abc"})
    pw = item.to_playwright_cookie()
    assert "url" in pw or ("domain" in pw and "path" in pw)
    assert pw["name"] == "sessionid"
    assert pw["value"] == "abc"
    # expires 默认 -1 (会话级)
    assert pw["expires"] == -1


def test_to_playwright_with_url():
    item = DouyinCookieItem.from_dict(
        {"name": "x", "value": "y", "url": "https://www.douyin.com"}
    )
    pw = item.to_playwright_cookie()
    assert pw["url"] == "https://www.douyin.com"
    # 用了 url 就不要同时传 domain/path
    assert "domain" not in pw or pw.get("url")


def test_to_playwright_explicit_domain_path():
    item = DouyinCookieItem.from_dict(
        {"name": "x", "value": "y", "domain": ".example.com", "path": "/api"}
    )
    pw = item.to_playwright_cookie()
    assert pw["domain"] == ".example.com"
    assert pw["path"] == "/api"


def test_same_site_always_valid():
    """未知 sameSite 值降级为 None。"""
    item = DouyinCookieItem.from_dict(
        {"name": "x", "value": "y", "sameSite": "weird-value"}
    )
    assert item.sameSite == "None"
    pw = item.to_playwright_cookie()
    assert pw["sameSite"] == "None"


def test_same_site_no_restriction_maps_to_none():
    """Chrome DevTools 导出中的 no_restriction 应被映射为 None。"""
    item = DouyinCookieItem.from_dict(
        {"name": "x", "value": "y", "sameSite": "no_restriction"}
    )
    assert item.sameSite == "None"


def test_same_site_unset_maps_to_lax():
    """Chrome DevTools 导出中的 Unset 应被映射为 Lax。"""
    item = DouyinCookieItem.from_dict(
        {"name": "x", "value": "y", "sameSite": "Unset"}
    )
    assert item.sameSite == "Lax"


def test_explicit_samesite_preserved():
    item = DouyinCookieItem.from_dict(
        {"name": "x", "value": "y", "sameSite": "Strict"}
    )
    assert item.to_playwright_cookie()["sameSite"] == "Strict"


def test_case_insensitive_field_names():
    """Cookie Editor 输出大小写字段也能识别。"""
    item = DouyinCookieItem.from_dict({"Name": "x", "Value": "y", "Domain": ".d.com"})
    assert item.name == "x"
    assert item.value == "y"
    assert item.domain == ".d.com"


def test_parse_invalid_json_raises():
    with pytest.raises(Exception):
        parse_cookie_json("not a json")


def test_parse_non_array_raises():
    with pytest.raises(Exception):
        parse_cookie_json('{"name":"x"}')


def test_serialize_roundtrip():
    items = parse_cookie_json(
        json.dumps([
            {"name": "a", "value": "1", "domain": ".d.com", "path": "/", "secure": True, "httpOnly": False, "sameSite": "Lax"},
            {"name": "b", "value": "2"},
        ])
    )
    out = cookies_to_json(items)
    reparsed = parse_cookie_json(out)
    assert len(reparsed) == 2
    assert reparsed[0].name == "a"
    assert reparsed[0].domain == ".d.com"
    assert reparsed[1].name == "b"
    assert reparsed[1].domain == DEFAULT_COOKIE_DOMAIN


def test_humanize_playwright_error():
    """人类可读错误翻译。"""
    from app.douyin_runner import _humanize_playwright_error
    e = Exception("Page.goto: net::ERR_PROXY_CONNECTION_FAILED at https://x")
    assert "代理" in _humanize_playwright_error(e, used_proxy=True)
    e2 = Exception("ERR_TIMED_OUT")
    assert "超时" in _humanize_playwright_error(e2, used_proxy=False)
    e3 = Exception("Cookie should have a url or a domain/path pair")
    assert "domain" in _humanize_playwright_error(e3, used_proxy=False)
    e4 = Exception("Random Error")
    assert "Random Error" in _humanize_playwright_error(e4, used_proxy=False)
