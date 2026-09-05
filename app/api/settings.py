# 抖音自动续火花管理面板 - 设置 API
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter

from .. import database, scheduler, tg_sender

log = logging.getLogger("das.api.settings")
router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("")
def get_all_settings():
    settings = database.get_all_settings()
    return {"settings": settings}


@router.put("")
def update_settings(body: dict[str, Any]):
    settings = {k: str(v) for k, v in body.items()}
    database.set_settings(settings)
    # 如果修改了定时设置，重新加载调度
    if "schedule_cron" in settings or "schedule_enabled" in settings:
        scheduler.reload_schedule()
    return {"message": "设置已保存"}


@router.post("/test-tg")
def test_tg_push():
    """发送测试 TG 消息"""
    result = tg_sender.test_push()
    return result
