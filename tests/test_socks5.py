"""SOCKS5 拨号的本地单测：起一个临时 TCP 服务器模拟代理与 HTTP 后端，验证握手、域名解析、认证和错误处理。"""
from __future__ import annotations

import json
import socket
import struct
import threading

from app.douyin_runner import (
    _looks_like_ip,
    _split_proxy_url,
    _test_proxy_internal,
)


def _pick_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _build_socks5_server(port: int, target_host: str, target_port: int, with_auth: bool) -> tuple[threading.Thread, socket.socket]:
    """起一个本地 SOCKS5 代理服务器，返回 (thread, listener_socket) 以便测试结束释放。"""
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", port))
    listener.listen(8)

    def handle(client: socket.socket) -> None:
        try:
            client.settimeout(5)
            greeting = client.recv(3)
            if greeting[0] != 0x05:
                client.close()
                return
            if with_auth:
                client.sendall(b"\x05\x02")
                ver = client.recv(1)[0]
                ulen = client.recv(1)[0]
                u = client.recv(ulen)
                plen = client.recv(1)[0]
                p = client.recv(plen)
                ok = (ver == 0x01 and u == b"kaoqy" and p == b"testpwd")
                client.sendall(b"\x01\x00" if ok else b"\x01\x01")
                if not ok:
                    client.close()
                    return
            else:
                client.sendall(b"\x05\x00")
            head = b""
            while len(head) < 4:
                head += client.recv(4 - len(head))
            atyp = head[3]
            if atyp == 0x01:
                client.recv(4)
            elif atyp == 0x03:
                ln = client.recv(1)[0]
                client.recv(ln)
            else:
                client.sendall(b"\x05\x08\x00\x00\x01\x00\x00\x00\x00\x00\x00")
                client.close()
                return
            client.recv(2)
            try:
                upstream = socket.create_connection((target_host, target_port), timeout=5)
            except OSError:
                client.sendall(b"\x05\x05\x00\x00\x01\x00\x00\x00\x00\x00\x00")
                client.close()
                return
            client.sendall(b"\x05\x00\x00\x01\x00\x00\x00\x00\x00\x00")
            try:
                body = json.dumps({
                    "status": "success",
                    "query": "203.0.113.7",
                    "country": "United States",
                    "countryCode": "US",
                    "regionName": "Virginia",
                    "city": "Ashburn",
                })
                resp = (
                    f"HTTP/1.1 200 OK\r\nContent-Length: {len(body)}\r\n"
                    f"Content-Type: application/json\r\nConnection: close\r\n\r\n{body}"
                )
                client.sendall(resp.encode("ascii"))
            except Exception:
                pass
            try:
                upstream.close()
            except Exception:
                pass
            try:
                client.close()
            except Exception:
                pass
        except OSError:
            try:
                client.close()
            except Exception:
                pass

    def serve():
        while True:
            try:
                c, _ = listener.accept()
            except OSError:
                break
            threading.Thread(target=handle, args=(c,), daemon=True).start()

    t = threading.Thread(target=serve, daemon=True)
    t.start()
    return t, listener


def _stop_server(t: threading.Thread, listener: socket.socket) -> None:
    try:
        listener.close()
    except OSError:
        pass
    t.join(timeout=1)


def test_looks_like_ip():
    assert _looks_like_ip("1.2.3.4")
    assert _looks_like_ip("255.255.255.255")
    assert not _looks_like_ip("1.2.3")
    assert not _looks_like_ip("1.2.3.4.5")
    assert not _looks_like_ip("example.com")


def test_split_proxy_url():
    assert _split_proxy_url("socks5://1.2.3.4:1080") == ("1.2.3.4", 1080, "", "")
    assert _split_proxy_url("socks5://u:p@5.6.7.8:1081") == ("5.6.7.8", 1081, "u", "p")
    with_auth = _split_proxy_url("socks5h://kaoqy:testpwd@1.2.3.4:1080")
    assert with_auth[2:] == ("kaoqy", "testpwd")


def test_test_proxy_with_fake_server_no_auth(monkeypatch=None):
    """通过模拟 SOCKS5 + 假 HTTP 后端验证 _test_proxy_internal 走通。"""
    port = _pick_port()

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", port))
    listener.listen(8)

    def handle_no_auth_json(client: socket.socket) -> None:
        try:
            client.settimeout(5)
            client.recv(3)
            client.sendall(b"\x05\x00")
            head = client.recv(4)
            atyp = head[3]
            if atyp == 0x01:
                client.recv(4)
            elif atyp == 0x03:
                ln = client.recv(1)[0]
                client.recv(ln)
            client.recv(2)
            client.sendall(b"\x05\x00\x00\x01\x00\x00\x00\x00\x00\x00")
            body = json.dumps({
                "status": "success",
                "query": "203.0.113.7",
                "country": "United States",
                "countryCode": "US",
                "regionName": "Virginia",
                "city": "Ashburn",
            })
            resp = (
                f"HTTP/1.1 200 OK\r\nContent-Length: {len(body)}\r\n"
                f"Content-Type: application/json\r\nConnection: close\r\n\r\n{body}"
            )
            client.sendall(resp.encode("ascii"))
            client.close()
        except OSError:
            try:
                client.close()
            except Exception:
                pass

    def serve():
        while True:
            try:
                c, _ = listener.accept()
            except OSError:
                break
            threading.Thread(target=handle_no_auth_json, args=(c,), daemon=True).start()

    t = threading.Thread(target=serve, daemon=True)
    t.start()
    result = _test_proxy_internal(f"socks5://127.0.0.1:{port}")
    _stop_server(t, listener)
    assert result["ok"] is True, result
    assert result["country_code"] == "US"


def test_test_proxy_auth_success(monkeypatch=None):
    """带认证的 SOCKS5，模拟 ip-api.com 的 JSON 响应。"""
    # 目标连接 localhost 一个明显不监听的端口，让 server 走“CONNECT 被拒”路径，
    # 然后改用返 JSON 的 server 重复送一次。但为简化，我们让 server 跳过上游连接，
    # 直接在成功 CONNECT 后给客户端发 JSON body。
    port = _pick_port()

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", port))
    listener.listen(8)

    def handle_auth_then_json(client: socket.socket) -> None:
        try:
            client.settimeout(5)
            client.recv(3)
            client.sendall(b"\x05\x02")
            ver = client.recv(1)[0]
            ulen = client.recv(1)[0]
            u = client.recv(ulen)
            plen = client.recv(1)[0]
            p = client.recv(plen)
            if not (ver == 0x01 and u == b"kaoqy" and p == b"testpwd"):
                client.sendall(b"\x01\x01")
                client.close()
                return
            client.sendall(b"\x01\x00")
            head = client.recv(4)
            atyp = head[3]
            if atyp == 0x01:
                client.recv(4)
            elif atyp == 0x03:
                ln = client.recv(1)[0]
                client.recv(ln)
            else:
                client.sendall(b"\x05\x08\x00\x01\x00\x00\x00\x00\x00\x00")
                client.close()
                return
            client.recv(2)
            client.sendall(b"\x05\x00\x00\x01\x00\x00\x00\x00\x00\x00")
            body = json.dumps({
                "status": "success",
                "query": "203.0.113.7",
                "country": "United States",
                "countryCode": "US",
                "regionName": "Virginia",
                "city": "Ashburn",
            })
            resp = (
                f"HTTP/1.1 200 OK\r\nContent-Length: {len(body)}\r\n"
                f"Content-Type: application/json\r\nConnection: close\r\n\r\n{body}"
            )
            client.sendall(resp.encode("ascii"))
            client.close()
        except OSError:
            try:
                client.close()
            except Exception:
                pass

    def serve():
        while True:
            try:
                c, _ = listener.accept()
            except OSError:
                break
            threading.Thread(target=handle_auth_then_json, args=(c,), daemon=True).start()

    t = threading.Thread(target=serve, daemon=True)
    t.start()
    result = _test_proxy_internal(f"socks5://kaoqy:testpwd@127.0.0.1:{port}")
    _stop_server(t, listener)
    assert result["ok"] is True, result
    assert result["country"] == "United States"
    assert result["country_code"] == "US"
    assert result["city"] == "Ashburn"
    assert result["ip"] == "203.0.113.7"


def test_test_proxy_empty_url():
    r = _test_proxy_internal("")
    assert r["ok"] is False
    assert "空" in r["message"]


def test_test_proxy_invalid_url():
    r = _test_proxy_internal("not a url")
    # 缺少端口
    assert r["ok"] is False


def test_test_proxy_rejects_https_scheme():
    r = _test_proxy_internal("http://1.2.3.4:8080")
    assert r["ok"] is False
    assert "SOCKS5" in r["message"]
