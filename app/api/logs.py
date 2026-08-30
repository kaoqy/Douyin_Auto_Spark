# 抖音自动续火花管理面板 - 日志 API
from __future__ import annotations

import logging

from fastapi import APIRouter, Query

from .. import database

log = logging.getLogger("das.api.logs")
router = APIRouter(prefix="/api/logs", tags=["logs"])


@router.get("")
def list_logs(
    limit: int = Query(default=100, le=500),
    offset: int = Query(default=0, ge=0),
    status: str | None = None,
    account_id: int | None = None,
):
    logs = database.get_logs(limit, offset, status, account_id)
    return {"logs": logs, "limit": limit, "offset": offset}


@router.delete("")
def clear_logs():
    """清空所有日志"""
    conn = database.get_conn()
    conn.execute("DELETE FROM logs")
    conn.commit()
    return {"message": "日志已清空"}
