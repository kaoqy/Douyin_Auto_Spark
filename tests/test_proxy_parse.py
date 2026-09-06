"""_parse_proxy_url 各种格式覆盖测试。"""
import pytest

from app.douyin_runner import _parse_proxy_url


def test_empty_returns_none():
    assert _parse_proxy_url("") is None
    assert _parse_proxy_url("   ") is None
    assert _parse_proxy_url(None) is None


def test_socks5_no_auth():
    r = _parse_proxy_url("socks5://1.2.3.4:1080")
    assert r == {"server": "socks5://1.2.3.4:1080"}


def test_socks5_with_auth():
    r = _parse_proxy_url("socks5://user:pwd@1.2.3.4:1080")
    assert r == {"server": "socks5://1.2.3.4:1080", "username": "user", "password": "pwd"}


def test_socks5_user_only():
    r = _parse_proxy_url("socks5://user@1.2.3.4:1080")
    assert r == {"server": "socks5://1.2.3.4:1080", "username": "user"}


def test_http_proxy():
    r = _parse_proxy_url("http://1.2.3.4:8080")
    assert r == {"server": "http://1.2.3.4:8080"}


def test_https_proxy_with_auth():
    r = _parse_proxy_url("https://user:pwd@1.2.3.4:443")
    assert r == {"server": "https://1.2.3.4:443", "username": "user", "password": "pwd"}


def test_bare_host_port():
    r = _parse_proxy_url("1.2.3.4:1080")
    assert r == {"server": "socks5://1.2.3.4:1080"}


def test_bare_host_port_user_pass():
    r = _parse_proxy_url("1.2.3.4:1080:user:pwd")
    assert r == {"server": "socks5://1.2.3.4:1080", "username": "user", "password": "pwd"}


def test_bare_host_port_user_only():
    r = _parse_proxy_url("1.2.3.4:1080:user")
    assert r == {"server": "socks5://1.2.3.4:1080", "username": "user"}


def test_garbage_returns_none():
    for t in ["foo bar", "@@@", "abc:def", "1.2.3.4:abc", "1.2.3.4"]:
        assert _parse_proxy_url(t) is None, f"expected None for {t!r}"


def test_ipv6_unsupported_but_doesnt_crash():
    # 解析失败即可，不应抛
    r = _parse_proxy_url("socks5://[::1]:1080")
    # 因为端口规则不匹配 IPv6，会返回 None 或解析为非预期；都不抛即可
    assert r is None or "server" in r
