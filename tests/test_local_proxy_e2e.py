"""End-to-end: LocalProxy + 真 gost 二进制 + 假 SOCKS5 服务器。

验证 gost 真的能把本地无认证流量转发到带认证的远端 SOCKS5。
如果环境没 gost，这个测试会被 skip。
"""
from __future__ import annotations

import asyncio
import os
import shutil
import socket
import struct
import threading
import time

import pytest

from app.douyin_runner import LocalProxy


GOST_BIN_ENV = os.environ.get("GOST_BIN") or shutil.which("gost") or "/usr/local/bin/gost"
HAS_GOST = os.path.isfile(GOST_BIN_ENV) and os.access(GOST_BIN_ENV, os.X_OK)


class _FakeUpstreamSocks5:
    """假远端 SOCKS5 服务器，校验认证信息。

    正确读取 SOCKS5 协议：先读 ver + nmethods，再读 nmethods 个 method。
    """

    def __init__(self, expected_user: bytes, expected_pass: bytes):
        self.expected_user = expected_user
        self.expected_pass = expected_pass
        self.captured: list[dict] = []
        self.listener: socket.socket | None = None
        self.thread: threading.Thread | None = None
        self._stop = False

    def start(self) -> int:
        self.listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen(8)
        port = self.listener.getsockname()[1]
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()
        return port

    def stop(self) -> None:
        self._stop = True
        try:
            self.listener.close()
        except Exception:
            pass
        if self.thread:
            self.thread.join(timeout=2)

    def _serve(self) -> None:
        while not self._stop:
            try:
                client, _ = self.listener.accept()
            except OSError:
                break
            threading.Thread(target=self._handle, args=(client,), daemon=True).start()

    def _recv_exact(self, c: socket.socket, n: int) -> bytes:
        buf = b""
        while len(buf) < n:
            d = c.recv(n - len(buf))
            if not d:
                raise ConnectionError("closed")
            buf += d
        return buf

    def _handle(self, client: socket.socket) -> None:
        try:
            client.settimeout(3)
            ver = self._recv_exact(client, 1)[0]
            nmethods = self._recv_exact(client, 1)[0]
            self._recv_exact(client, nmethods)
            # 总是要求 user/pass
            client.sendall(b"\x05\x02")
            ver2 = self._recv_exact(client, 1)[0]
            ulen = self._recv_exact(client, 1)[0]
            u = self._recv_exact(client, ulen)
            plen = self._recv_exact(client, 1)[0]
            p = self._recv_exact(client, plen)
            self.captured.append({"ver": ver2, "user": u, "pass": p})
            if u == self.expected_user and p == self.expected_pass:
                client.sendall(b"\x01\x00")
            else:
                client.sendall(b"\x01\x01")
                client.close()
                return
            # CONNECT
            head = self._recv_exact(client, 4)
            atyp = head[3]
            if atyp == 0x03:
                ln = self._recv_exact(client, 1)[0]
                self._recv_exact(client, ln)
            elif atyp == 0x01:
                self._recv_exact(client, 4)
            else:
                client.close()
                return
            self._recv_exact(client, 2)
            # success
            client.sendall(b"\x05\x00\x00\x01\x00\x00\x00\x00\x00\x00")
            time.sleep(0.2)
            client.close()
        except Exception:
            try:
                client.close()
            except Exception:
                pass


def _asyncio_run(coro):
    """简单包装，循环关闭时容错。"""
    try:
        return asyncio.run(coro)
    except RuntimeError:
        return None


@pytest.mark.skipif(not HAS_GOST, reason=f"gost 不存在 ({GOST_BIN_ENV})")
def test_local_proxy_e2e_with_real_gost(monkeypatch):
    """端到端：本地 127.0.0.1:lp_port -> gost -> 假 SOCKS5 上游。

    1. 假 SOCKS5 上游要求 user/pass 认证
    2. LocalProxy 启动 gost，把 socks5://user:pass@upstream 转成本地 socks5://127.0.0.1:lp_port
    3. 测试客户端连本地 lp_port，做 SOCKS5 CONNECT
    4. 验证假上游收到了 user=alice, pass=***
    """
    monkeypatch.setattr(LocalProxy, "_resolve_gost", classmethod(lambda cls: GOST_BIN_ENV))

    upstream = _FakeUpstreamSocks5(b"alice", b"s3cret!")
    upstream_port = upstream.start()
    try:
        proxy_url = f"socks5://alice:s3cret!@127.0.0.1:{upstream_port}"
        lp = LocalProxy(proxy_url)
        _asyncio_run(lp.start())
        try:
            assert lp.ok, f"LocalProxy.start failed: {lp.error}"
            assert lp.port is not None

            with socket.create_connection(("127.0.0.1", lp.port), timeout=3) as s:
                s.sendall(b"\x05\x01\x00")  # 无认证
                resp = s.recv(2)
                assert resp == b"\x05\x00", f"gost greeting 异常：{resp!r}"
                s.sendall(b"\x05\x01\x00\x01\x7f\x00\x00\x01\x00\x50")  # CONNECT 127.0.0.1:80
                s.settimeout(3)
                resp = s.recv(10)
                assert resp[0] == 0x05 and resp[1] == 0x00, f"gost CONNECT 失败：{resp!r}"

            time.sleep(0.3)
            assert len(upstream.captured) >= 1, f"上游没收到请求，captured={upstream.captured}"
            auth = upstream.captured[0]
            assert auth["ver"] == 0x01
            assert auth["user"] == b"alice", f"got user={auth['user']!r}"
            assert auth["pass"] == b"s3cret!", f"got pass={auth['pass']!r}"
        finally:
            _asyncio_run(lp.stop())
    finally:
        upstream.stop()
