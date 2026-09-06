"""_split_proxy_url 各种格式覆盖测试。"""
import pytest

from app.douyin_runner import _split_proxy_url, _parse_proxy_url


def test_split_empty():
    import pytest as _p
    with _p.raises(ValueError, match="空"):
        _split_proxy_url("")
    with _p.raises(ValueError, match="空"):
        _split_proxy_url(None)


def test_split_socks5_with_auth():
    assert _split_proxy_url("socks5://user:pwd@1.2.3.4:1080") == ("1.2.3.4", 1080, "user", "pwd")


def test_split_socks5_no_auth():
    assert _split_proxy_url("socks5://1.2.3.4:1080") == ("1.2.3.4", 1080, "", "")


def test_split_socks5h_scheme():
    assert _split_proxy_url("socks5h://1.2.3.4:1080") == ("1.2.3.4", 1080, "", "")


def test_split_bare_host_port():
    assert _split_proxy_url("1.2.3.4:1080") == ("1.2.3.4", 1080, "", "")


def test_split_bare_host_port_user_pwd():
    assert _split_proxy_url("1.2.3.4:1080:user:pwd") == ("1.2.3.4", 1080, "user", "pwd")


def test_split_bare_host_port_user_only():
    # 6 个 colons -> ['1.2.3.4', '1080', 'user'] -> host/port/user only
    assert _split_proxy_url("1.2.3.4:1080:user")[0:2] == ("1.2.3.4", 1080)


def test_split_http_rejected():
    with pytest.raises(ValueError, match="仅支持 SOCKS5"):
        _split_proxy_url("http://1.2.3.4:8080")


def test_split_missing_port():
    with pytest.raises(ValueError):
        _split_proxy_url("socks5://1.2.3.4")


def test_split_non_numeric_port():
    with pytest.raises(ValueError, match="数字"):
        _split_proxy_url("socks5://1.2.3.4:abc")


def test_parse_proxy_url_variants():
    assert _parse_proxy_url("") is None
    assert _parse_proxy_url("1.2.3.4:1080")["server"] == "socks5://1.2.3.4:1080"
    # 实际返回的是真实凭据（这是内部函数），不是 masked
    out = _parse_proxy_url("socks5://u:p@1.2.3.4:1080")
    assert out["server"] == "socks5://1.2.3.4:1080"
    assert out["username"] == "u"
    assert out["password"] == "p"
