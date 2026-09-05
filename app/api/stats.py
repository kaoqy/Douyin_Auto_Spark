# 抖音续火花管理面板 - 统计聚合 API
from __future__ import annotations

from fastapi import APIRouter

from .. import database

router = APIRouter(prefix="/api/stats", tags=["stats"])


@router.get("")
def get_stats():
    """仪表盘聚合统计数据"""
    accounts = database.get_accounts()
    targets = database.get_targets()
    tasks = database.get_tasks(limit=1000)
    logs = database.get_logs(limit=5000)

    total_acc = len(accounts)
    enabled_acc = sum(1 for a in accounts if a.get("enabled"))
    total_targets = len(targets)
    enabled_targets = sum(1 for t in targets if t.get("enabled"))

    total_runs = len(tasks)
    success_runs = sum(1 for t in tasks if t.get("status") == "success")
    partial_runs = sum(1 for t in tasks if t.get("status") == "partial")
    failed_runs = sum(1 for t in tasks if t.get("status") == "failed")
    success_rate = f"{success_runs / total_runs * 100:.1f}%" if total_runs else "—"

    total_messages = len(logs)
    ok_messages = sum(1 for l in logs if l.get("status") == "success")
    fail_messages = sum(1 for l in logs if l.get("status") != "success")

    # 最近 30 天活跃账号数
    from datetime import datetime, timedelta
    cutoff = (datetime.now() - timedelta(days=30)).isoformat()[:10]
    active_accounts = len(set(
        l.get("account_id") for l in logs
        if l.get("created_at", "") >= cutoff and l.get("account_id")
    ))

    return {
        "accounts": {"total": total_acc, "enabled": enabled_acc},
        "targets": {"total": total_targets, "enabled": enabled_targets},
        "runs": {
            "total": total_runs,
            "success": success_runs,
            "partial": partial_runs,
            "failed": failed_runs,
            "success_rate": success_rate,
        },
        "messages": {
            "total": total_messages,
            "ok": ok_messages,
            "fail": fail_messages,
        },
        "active_accounts": active_accounts,
    }
