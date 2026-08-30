# 抖音自动续火花管理面板 - 账号 API
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from .. import auth, database

log = logging.getLogger("das.api.accounts")
router = APIRouter(prefix="/api/accounts", tags=["accounts"])


@router.get("")
def list_accounts():
    accounts = database.get_accounts()
    # 脱敏代理 URL
    for acc in accounts:
        acc["proxy"] = database.mask_proxy_url(acc.get("proxy", ""))
    return {"accounts": accounts}


@router.post("")
def create_account(body: dict[str, Any]):
    name = (body.get("name") or "").strip()
    cookie = body.get("cookie", "")
    proxy = (body.get("proxy") or "").strip()
    enabled = body.get("enabled", True)

    if not name:
        raise HTTPException(status_code=400, detail="账号名称不能为空")
    if not cookie:
        raise HTTPException(status_code=400, detail="Cookie 不能为空")

    # 验证 Cookie 格式
    try:
        import json
        data = json.loads(cookie) if isinstance(cookie, str) else cookie
        if not isinstance(data, list) or len(data) == 0:
            raise ValueError("Cookie 必须是非空 JSON 数组")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Cookie 格式错误：{e}")

    aid = database.add_account(name, cookie, proxy, enabled)
    return {"id": aid, "message": "账号添加成功"}


@router.put("/{account_id}")
def update_account(account_id: int, body: dict[str, Any]):
    kwargs: dict[str, Any] = {}
    if "name" in body:
        kwargs["name"] = body["name"]
    if "cookie" in body:
        kwargs["cookie"] = body["cookie"]
    if "proxy" in body:
        kwargs["proxy"] = body["proxy"].strip() if body["proxy"] else ""
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
    acc["proxy"] = database.mask_proxy_url(acc.get("proxy", ""))
    return acc
