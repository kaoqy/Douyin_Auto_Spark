"""_resolve_proxy：账号 API 接受 proxy_id 或 url 的解析逻辑。"""
import os
import tempfile


def _fresh_app(monkeypatch=None):
    """每次测试用临时数据库。"""
    tmp = tempfile.mkdtemp()
    os.environ["DAS_DATA_DIR"] = tmp
    # 重新加载 database 模块以使用新目录
    import importlib
    from app import database
    importlib.reload(database)
    database.init_db()
    return database


def test_empty(monkeypatch):
    db = _fresh_app(monkeypatch)
    from app.api.accounts import _resolve_proxy
    assert _resolve_proxy("") == ""
    assert _resolve_proxy(None) == ""
    assert _resolve_proxy("   ") == ""


def test_url_passthrough(monkeypatch):
    db = _fresh_app(monkeypatch)
    from app.api.accounts import _resolve_proxy
    assert _resolve_proxy("socks5://1.2.3.4:1080") == "socks5://1.2.3.4:1080"
    assert _resolve_proxy("  socks5://1.2.3.4:1080  ") == "socks5://1.2.3.4:1080"


def test_masked_url_rejected(monkeypatch):
    db = _fresh_app(monkeypatch)
    from app.api.accounts import _resolve_proxy
    # 拒绝被打码的 url（防止被误用为真实凭据）
    assert _resolve_proxy("socks5://***@1.2.3.4:1080") == ""


def test_int_proxy_id(monkeypatch):
    db = _fresh_app(monkeypatch)
    from app.api.accounts import _resolve_proxy
    pid = db.add_proxy({"ip": "5.6.7.8", "port": 1080, "username": "u", "password": "p", "enabled": 1})
    assert _resolve_proxy(pid) == "socks5://u:p@5.6.7.8:1080"


def test_str_proxy_id(monkeypatch):
    db = _fresh_app(monkeypatch)
    from app.api.accounts import _resolve_proxy
    pid = db.add_proxy({"ip": "5.6.7.8", "port": 1080, "enabled": 1})
    assert _resolve_proxy(str(pid)) == "socks5://5.6.7.8:1080"


def test_nonexistent_proxy_id(monkeypatch):
    db = _fresh_app(monkeypatch)
    from app.api.accounts import _resolve_proxy
    assert _resolve_proxy(9999) == ""
    assert _resolve_proxy("9999") == ""


def test_garbage_passthrough(monkeypatch):
    """不识别的值原样返回（向后兼容）。"""
    db = _fresh_app(monkeypatch)
    from app.api.accounts import _resolve_proxy
    assert _resolve_proxy("foo bar") == "foo bar"
