"""LocalProxy 单元测试：覆盖 gost 启停、端口分配、错误处理。

不依赖真实 gost 进程：用一个假二进制（Python 脚本）模拟 gost，
或者用 monkeypatch 把 _resolve_gost 替换成 Python 内置服务器。
"""
from __future__ import annotations

import asyncio
import socket
import threading
import time

import pytest

from app import douyin_runner
from app.douyin_runner import LocalProxy, _has_socks5_auth, _parse_proxy_url


# ===== 静态检查：解析与判定 =====

def test_has_socks5_auth_true():
    cfg = {"server": "socks5://1.2.3.4:1080", "username": "u", "password": "p"}
    assert _has_socks5_auth(cfg) is True


def test_has_socks5_auth_user_only():
    cfg = {"server": "socks5://1.2.3.4:1080", "username": "u"}
    assert _has_socks5_auth(cfg) is True


def test_has_socks5_auth_no_user():
    cfg = {"server": "socks5://1.2.3.4:1080"}
    assert _has_socks5_auth(cfg) is False


def test_has_socks5_auth_http_with_user():
    cfg = {"server": "http://1.2.3.4:8080", "username": "u", "password": "p"}
    assert _has_socks5_auth(cfg) is False  # HTTP 代理 Chromium 支持，不走 gost


def test_has_socks5_auth_none():
    assert _has_socks5_auth(None) is False
    assert _has_socks5_auth({}) is False


# ===== 失败路径：无效 URL / gost 缺失 =====

def test_start_invalid_url_does_not_raise():
    lp = LocalProxy("not a url")
    asyncio.run(lp.start())
    assert lp.ok is False
    assert "解析失败" in lp.error


def test_start_empty_url_does_not_raise():
    lp = LocalProxy("")
    asyncio.run(lp.start())
    # 空 URL 会 _parse_proxy_url 返回 None，等同于直连
    # 实际上空 URL _parse_proxy_url 返回 None，self._error = "代理 URL 解析失败"
    assert lp.ok is False


# ===== 成功路径：HTTP 代理无需 gost，直接返回原配置 =====

def test_http_proxy_passthrough():
    lp = LocalProxy("http://1.2.3.4:8080")
    asyncio.run(lp.start())
    assert lp.ok is True
    assert lp.playwright_config == {"server": "http://1.2.3.4:8080"}
    asyncio.run(lp.stop())  # 应该 no-op


def test_socks5_no_auth_passthrough():
    lp = LocalProxy("socks5://1.2.3.4:1080")
    asyncio.run(lp.start())
    assert lp.ok is True
    assert lp.playwright_config == {"server": "socks5://1.2.3.4:1080"}


# ===== 成功路径：SOCKS5 认证需要 gost，monkeypatch 一个假 gost =====

class _FakeGost:
    """假 gost：只是把命令行参数原样写到 stderr，并保持进程存活。"""

    def __init__(self):
        self.calls: list[list[str]] = []

    def script(self) -> str:
        return (
            "#!/usr/bin/env python3\n"
            "import sys, time, signal, threading\n"
            "# 简单 TCP 服务器模拟 gost 监听 -L 端口\n"
            "args = sys.argv[1:]\n"
            "try:\n"
            "    i = args.index('-L')\n"
            "    url = args[i + 1]\n"
            "    port = int(url.rsplit(':', 1)[1])\n"
            "except Exception as e:\n"
            "    print('fake-gost arg error:', e, file=sys.stderr)\n"
            "    sys.exit(1)\n"
            "import socket\n"
            "s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)\n"
            "s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)\n"
            "try:\n"
            "    s.bind(('127.0.0.1', port))\n"
            "    s.listen(5)\n"
            "except Exception as e:\n"
            "    print('fake-gost bind error:', e, file=sys.stderr)\n"
            "    sys.exit(1)\n"
            "print('fake-gost listening on', port, flush=True)\n"
            "stop = threading.Event()\n"
            "def term(*a): stop.set()\n"
            "signal.signal(signal.SIGTERM, term)\n"
            "signal.signal(signal.SIGINT, term)\n"
            "s.settimeout(0.5)\n"
            "while not stop.is_set():\n"
            "    try:\n"
            "        c, _ = s.accept()\n"
            "        c.close()\n"
            "    except socket.timeout:\n"
            "        pass\n"
            "    except Exception:\n"
            "        break\n"
            "s.close()\n"
        )


@pytest.fixture
def fake_gost_path(tmp_path, monkeypatch):
    """把 gost 解析到一个临时脚本，返回路径。"""
    fake = _FakeGost()
    script = tmp_path / "gost"
    script.write_text(fake.script())
    script.chmod(0o755)
    monkeypatch.setattr(LocalProxy, "_resolve_gost", classmethod(lambda cls: str(script)))
    return script


def test_socks5_with_auth_starts_gost(fake_gost_path):
    """带认证 SOCKS5 启动 gost，playwright_config 指向 127.0.0.1。"""
    proxy_url = "socks5://testuser:secret@1.2.3.4:1080"
    lp = LocalProxy(proxy_url)
    asyncio.run(lp.start())
    try:
        assert lp.ok is True, f"start failed: {lp.error}"
        assert lp.port is not None
        assert 19080 <= lp.port <= 19180
        assert lp.playwright_config == {"server": f"socks5://127.0.0.1:{lp.port}"}
        # 端口确实能连
        with socket.create_connection(("127.0.0.1", lp.port), timeout=1) as s:
            assert s is not None
    finally:
        asyncio.run(lp.stop())


def test_socks5_with_auth_password_special_chars(fake_gost_path):
    """密码含特殊字符（@ : 等）也能正常启动。"""
    proxy_url = "socks5://user:p%40ss%3Aword@1.2.3.4:1080"
    lp = LocalProxy(proxy_url)
    asyncio.run(lp.start())
    try:
        # 这里不验证 gost 是否能认证，只验证启动流程没炸
        assert lp.ok is True, f"start failed: {lp.error}"
        assert lp.port is not None
    finally:
        asyncio.run(lp.stop())


def test_socks5_with_auth_stop_terminates_process(fake_gost_path):
    """stop 之后 _proc 置空，不阻塞。

    跨事件循环的进程回收不在单测里验证，由部署后的启动脚本检查。
    """
    proxy_url = "socks5://u:p@1.2.3.4:1080"
    lp = LocalProxy(proxy_url)
    asyncio.run(lp.start())
    assert lp.port is not None
    assert lp._proc is not None
    asyncio.run(lp.stop())
    assert lp._proc is None


# ===== 错误：gost 缺失 =====

def test_gost_missing_returns_error(monkeypatch):
    """gost 不可用时，ok=False，error 包含 gost。"""
    monkeypatch.setattr(LocalProxy, "_resolve_gost", classmethod(lambda cls: None))
    lp = LocalProxy("socks5://u:p@1.2.3.4:1080")
    asyncio.run(lp.start())
    assert lp.ok is False
    assert "gost" in lp.error


# ===== 端口分配不会重复（简单递增） =====

def test_port_allocation_increments():
    p1 = LocalProxy("socks5://u:p@1.2.3.4:1080")._allocate_port()
    p2 = LocalProxy("socks5://u:p@1.2.3.4:1080")._allocate_port()
    assert p2 == p1 + 1
