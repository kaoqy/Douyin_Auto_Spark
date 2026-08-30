# 抖音自动续火花管理面板 - 好友 API
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException

from .. import database

log = logging.getLogger("das.api.targets")
router = APIRouter(prefix="/api/targets", tags=["targets"])


@router.get("")
def list_targets(account_id: int | None = None):
    targets = database.get_targets(account_id)
    return {"targets": targets}


@router.post("")
def create_target(body: dict[str, Any]):
    account_id = body.get("account_id")
    name = (body.get("name") or "").strip()
    enabled = body.get("enabled", True)

    if not account_id:
        raise HTTPException(status_code=400, detail="必须指定账号")
    if not name:
        raise HTTPException(status_code=400, detail="好友名称不能为空")

    tid = database.add_target(account_id, name, enabled)
    return {"id": tid, "message": "好友添加成功"}


@router.put("/{target_id}")
def update_target(target_id: int, body: dict[str, Any]):
    kwargs: dict[str, Any] = {}
    if "name" in body:
        kwargs["name"] = body["name"]
    if "enabled" in body:
        kwargs["enabled"] = 1 if body["enabled"] else 0

    database.update_target(target_id, **kwargs)
    return {"message": "更新成功"}


@router.delete("/{target_id}")
def delete_target(target_id: int):
    database.delete_target(target_id)
    return {"message": "删除成功"}


@router.post("/batch")
def batch_add_targets(body: dict[str, Any]):
    """批量添加好友"""
    account_id = body.get("account_id")
    names = body.get("names", [])
    if not account_id or not names:
        raise HTTPException(status_code=400, detail="参数不完整")

    added = 0
    for name in names:
        name = name.strip()
        if name:
            database.add_target(account_id, name)
            added += 1
    return {"added": added, "message": f"已添加 {added} 个好友"}
