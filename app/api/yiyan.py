# 抖音自动续火花管理面板 - 一言 API
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from ..yiyan import fetch_yiyan_from_api

log = logging.getLogger("das.api.yiyan")
router = APIRouter(prefix="/api/yiyan", tags=["yiyan"])


@router.get("/random")
def pick_random():
    """从 hitokoto.cn 获取随机一言"""
    item = fetch_yiyan_from_api()
    if not item:
        raise HTTPException(status_code=502, detail="一言 API 暂时不可用")
    return {"yiyan": item}
