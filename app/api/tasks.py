# 抖音自动续火花管理面板 - 任务 API
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from .. import database, scheduler

log = logging.getLogger("das.api.tasks")
router = APIRouter(prefix="/api/tasks", tags=["tasks"])


@router.get("/run")
def get_current_run():
    """获取当前运行状态"""
    run = scheduler.get_current_run()
    return {"run": run}


@router.post("/run")
def trigger_run(body: dict | None = None):
    """手动触发续火任务"""
    if body and "account_ids" in body:
        account_ids = body["account_ids"]
    else:
        account_ids = None

    # 在后台线程执行
    import threading
    threading.Thread(
        target=scheduler.run_spark_task,
        args=("manual", account_ids),
        daemon=True,
    ).start()
    return {"message": "任务已启动"}


@router.get("/schedule")
def get_schedule():
    """获取定时任务设置"""
    return scheduler.next_run_info()


@router.put("/schedule")
def update_schedule(body: dict):
    """更新定时任务设置"""
    if "cron" in body:
        database.set_settings({"schedule_cron": body["cron"]})
    if "enabled" in body:
        database.set_settings({"schedule_enabled": "1" if body["enabled"] else "0"})
    scheduler.reload_schedule()
    return scheduler.next_run_info()


@router.get("")
def list_tasks(limit: int = 20):
    tasks = database.get_tasks(limit)
    return {"tasks": tasks}


@router.get("/{task_id}")
def get_task(task_id: str):
    task = database.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return task
