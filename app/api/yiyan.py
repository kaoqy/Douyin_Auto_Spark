# 抖音自动续火花管理面板 - 一言 API
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException

from .. import database, tg_sender
from ..yiyan import pick_random_yiyan, init_yiyan_if_empty

log = logging.getLogger("das.api.yiyan")
router = APIRouter(prefix="/api/yiyan", tags=["yiyan"])


@router.get("")
def list_yiyan():
    items = database.get_yiyan_list(enabled_only=False)
    return {"yiyan": items, "total": len(items)}


@router.post("")
def add_yiyan(body: dict[str, Any]):
    hitokoto = (body.get("hitokoto") or "").strip()
    source = (body.get("source") or "").strip()
    if not hitokoto:
        raise HTTPException(status_code=400, detail="一言内容不能为空")
    yid = database.add_yiyan(hitokoto, source)
    return {"id": yid, "message": "添加成功"}


@router.put("/{yiyan_id}")
def update_yiyan(yiyan_id: int, body: dict[str, Any]):
    kwargs: dict[str, Any] = {}
    if "hitokoto" in body:
        kwargs["hitokoto"] = body["hitokoto"]
    if "source" in body:
        kwargs["source"] = body["source"]
    if "enabled" in body:
        kwargs["enabled"] = 1 if body["enabled"] else 0
    database.update_yiyan(yiyan_id, **kwargs)
    return {"message": "更新成功"}


@router.delete("/{yiyan_id}")
def delete_yiyan(yiyan_id: int):
    database.delete_yiyan(yiyan_id)
    return {"message": "删除成功"}


@router.get("/random")
def pick_random():
    item = pick_random_yiyan()
    return {"yiyan": item}


@router.post("/import")
def import_default():
    """重新导入默认一言库"""
    init_yiyan_if_empty()
    return {"imported": database.count_yiyan(), "message": "默认一言库已导入"}


@router.post("/push")
def push_yiyan():
    """推送每日一言到 TG"""
    item = pick_random_yiyan()
    if not item:
        raise HTTPException(status_code=400, detail="一言库为空")
    ok = tg_sender.push_quote(item.get("hitokoto", ""), item.get("source", ""))
    if ok:
        return {"message": "已推送到 TG"}
    else:
        raise HTTPException(status_code=500, detail="推送失败")
