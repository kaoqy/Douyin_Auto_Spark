# 抖音自动续火花管理面板 - 账号 API
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from .. import auth, database
from ..douyin_cookie import cookies_to_json, parse_cookie_json
from ..douyin_runner import verify_cookie_sync, fetch_friend_list_sync

log = logging.getLogger("das.api.accounts")
router = APIRouter(prefix="/api/accounts", tags=["accounts"])


def _resolve_proxy(value):
    """根据前端提交的 proxy 值（id 或 url）获取真实可用的 URL。

    - 空值 / None / 空字符串：直连，返回 ""
    - 整数：当作代理节点 id，查表后返回真实 url
    - 字符串：以 socks5:// / http:// 开头，认作 url，直接返回
    - 数字字符串：当 id 查
    - 其余：原样返回（直连或尝试）
    """
    if value is None:
        return ""
    if isinstance(value, int):
        proxy = database.get_proxy(value)
        return (proxy or {}).get("url", "") or database.build_proxy_url(proxy or {})
    s = str(value).strip()
    if not s:
        return ""
    if s.isdigit():
        proxy = database.get_proxy(int(s))
        return (proxy or {}).get("url", "") or database.build_proxy_url(proxy or {})
    # 仍然允许传 url（向后兼容）
    if "://" in s:
        # 拒绝脱敏字符串
        if "***" in s:
            return ""
        return s
    return s


@router.get("")
def list_accounts():
    accounts = database.get_accounts()
    for acc in accounts:
        proxy_url = acc.get("proxy", "")
        acc["proxy"] = database.mask_proxy_url(proxy_url)
        # 反查 id 供前端代理选择
        if proxy_url:
            row = database.find_proxy_by_url(proxy_url)
            if row:
                acc["proxy_id"] = row["id"]
            else:
                acc["proxy_id"] = None
        else:
            acc["proxy_id"] = None
    return {"accounts": accounts}


@router.post("")
def create_account(body: dict[str, Any]):
    name = (body.get("name") or "").strip()
    cookie = body.get("cookie", "")
    proxy = _resolve_proxy(body.get("proxy"))
    enabled = body.get("enabled", True)

    if not name:
        raise HTTPException(status_code=400, detail="账号名称不能为空")
    if not cookie:
        raise HTTPException(status_code=400, detail="Cookie 不能为空")

    # 验证 Cookie 格式：复用 douyin_cookie.parse_cookie_json
    try:
        items = parse_cookie_json(cookie)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Cookie 格式错误：{e}")
    if not items:
        raise HTTPException(status_code=400, detail="Cookie 数组不能为空")
    for it in items:
        if not it.name or not it.value:
            raise HTTPException(status_code=400, detail="Cookie 数组每个元素必须包含 name 和 value 字段")
    # 存储时使用标准化后的 JSON（补全 domain/path/sameSite）
    cookie = cookies_to_json(items)

    aid = database.add_account(name, cookie, proxy, enabled)
    return {"id": aid, "message": "账号添加成功"}


@router.put("/{account_id}")
def update_account(account_id: int, body: dict[str, Any]):
    kwargs: dict[str, Any] = {}
    if "name" in body:
        kwargs["name"] = body["name"]
    if "cookie" in body:
        cookie = body["cookie"]
        try:
            items = parse_cookie_json(cookie)
            if items:
                cookie = cookies_to_json(items)
        except Exception:
            pass  # 保留原值（用户可能不需要自动修复）
        kwargs["cookie"] = cookie
    if "proxy" in body:
        kwargs["proxy"] = _resolve_proxy(body["proxy"])
    if "enabled" in body:
        kwargs["enabled"] = 1 if body["enabled"] else 0

    database.update_account(account_id, **kwargs)
    return {"message": "更新成功"}


@router.delete("/{account_id}")
def delete_account(account_id: int):
    database.delete_account(account_id)
    return {"message": "删除成功"}


@router.get("/{account_id}")
def get_account(account_id: int):
    acc = database.get_account(account_id)
    if not acc:
        raise HTTPException(status_code=404, detail="账号不存在")
    proxy_url = acc.get("proxy", "")
    acc["proxy"] = database.mask_proxy_url(proxy_url)
    if proxy_url:
        row = database.find_proxy_by_url(proxy_url)
        acc["proxy_id"] = row["id"] if row else None
    else:
        acc["proxy_id"] = None
    return acc


@router.post("/verify")
def verify_cookie(body: dict[str, Any]):
    """验证 Cookie 是否有效（不需要先创建账号）"""
    cookie = body.get("cookie", "")
    proxy = _resolve_proxy(body.get("proxy"))
    if not cookie:
        raise HTTPException(status_code=400, detail="Cookie 不能为空")
    try:
        result = verify_cookie_sync(cookie, proxy)
        return result
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{account_id}/verify")
def verify_account_cookie(account_id: int):
    """验证账号 Cookie 是否有效"""
    acc = database.get_account(account_id)
    if not acc:
        raise HTTPException(status_code=404, detail="账号不存在")
    result = verify_cookie_sync(acc.get("cookie", ""), acc.get("proxy", ""))
    database.touch_account_verify(
        account_id,
        bool(result.get("valid")),
        result.get("message", ""),
    )
    return result


@router.get("/{account_id}/friends")
def get_account_friends(account_id: int):
    """自动获取账号好友列表"""
    acc = database.get_account(account_id)
    if not acc:
        raise HTTPException(status_code=404, detail="账号不存在")
    friends = fetch_friend_list_sync(acc)
    return {"friends": friends, "count": len(friends)}
