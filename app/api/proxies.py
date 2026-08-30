"""代理节点管理 API。"""
from __future__ import annotations

import time

from fastapi import APIRouter, HTTPException

from .. import database
from ..douyin_runner import test_proxy_sync, detect_geo_sync

router = APIRouter(prefix="/api/proxies", tags=["proxies"])


def _parse_link(url: str) -> dict:
    """解析 socks5:// 链接为字段。返回 {ip,port,username,password}。"""
    from urllib.parse import urlparse
    if not url:
        return {"ip": "", "port": 0, "username": "", "password": ""}
    try:
        p = urlparse(url)
        host = p.hostname or ""
        port = p.port or 0
        user, pwd = "", ""
        if p.username:
            user = p.username
        if p.password:
            pwd = p.password
        return {"ip": host, "port": port, "username": user, "password": pwd}
    except Exception:
        return {"ip": "", "port": 0, "username": "", "password": ""}


def _public(p: dict) -> dict:
    """对外输出：绝不返回含认证信息的完整代理链接。"""
    p = dict(p)
    raw = p.get("url", "") or ""
    if not raw and p.get("ip"):
        raw = database.build_proxy_url(p)
    p["password"] = "***" if p.get("password") else ""
    p["has_auth"] = bool(p.get("username") or p.get("password"))
    p["url"] = database.mask_proxy_url(raw)
    return p


@router.get("")
def list_proxies():
    return [_public(p) for p in database.get_proxies(include_disabled=True)]


@router.post("")
def create_proxy(data: dict):
    payload = dict(data)
    if payload.get("url"):
        parsed = _parse_link(payload["url"])
        for k, v in parsed.items():
            if not payload.get(k):
                payload[k] = v
    if payload.get("ip"):
        url = database.build_proxy_url(payload) if not payload.get("url") else payload["url"]
        payload["url"] = url
    else:
        raise HTTPException(status_code=400, detail="缺少代理 IP/链接")
    pid = database.add_proxy(payload)
    return _public(database.get_proxy(pid))


@router.put("/{proxy_id}")
def update_one(proxy_id: int, data: dict):
    existing = database.get_proxy(proxy_id)
    if not existing:
        raise HTTPException(404, "代理不存在")
    payload = {k: v for k, v in data.items() if v is not None}
    if payload.get("password") in ("***", "•••"):
        payload.pop("password", None)
    if "url" in payload and payload["url"]:
        parsed = _parse_link(payload["url"])
        for k, v in parsed.items():
            if k in ("username", "password") and not v:
                continue
            payload.setdefault(k, v)
    if payload.get("ip"):
        merged = dict(existing)
        merged.update(payload)
        url = database.build_proxy_url(merged) or payload.get("url", existing.get("url", ""))
        payload["url"] = url
    database.update_proxy(proxy_id, payload)
    return _public(database.get_proxy(proxy_id))


@router.delete("/{proxy_id}")
def delete_one(proxy_id: int):
    if not database.delete_proxy(proxy_id):
        raise HTTPException(404, "代理不存在")
    return {"ok": True}


@router.post("/{proxy_id}/test")
def test_proxy(proxy_id: int):
    p = database.get_proxy(proxy_id)
    if not p:
        raise HTTPException(404, "代理不存在")
    url = p.get("url") or database.build_proxy_url(p)
    
    started = time.perf_counter()
    result = test_proxy_sync(url)
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    
    ok = result.get("ok", False)
    message = result.get("message", "")
    if ok and not message.endswith("ms"):
        message += f" · {elapsed_ms} ms"
    
    database.update_proxy(proxy_id, {
        "last_test": "ok" if ok else "fail",
        "last_latency_ms": elapsed_ms,
        "last_test_at": database._now(),
        "last_test_message": message,
    })
    
    return {"ok": ok, "message": message, "latency_ms": elapsed_ms, "geo": result}


@router.post("/detect")
def detect_url(data: dict):
    """识别归属地（不保存）。"""
    pid = data.get("proxy_id")
    url = ""
    if pid:
        p = database.get_proxy(int(pid))
        if not p:
            raise HTTPException(404, "代理不存在")
        url = p.get("url") or database.build_proxy_url(p)
    if not url:
        url = data.get("url", "") or ""
        if "***" in url:
            url = ""
    if not url and data.get("ip"):
        url = database.build_proxy_url({
            **data,
            "username": data.get("user") or data.get("username", ""),
            "password": data.get("pwd") or data.get("password", ""),
        })
    if not url:
        raise HTTPException(400, "缺少链接或 IP")
    
    result = detect_geo_sync(url)
    return {k: v for k, v in result.items() if k != "_t"}
