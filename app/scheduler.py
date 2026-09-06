# 抖音自动续火花管理面板 - 定时任务
from __future__ import annotations

import logging
import threading
import uuid
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from . import database, tg_sender
from .anti_ban import AntiBanPolicy
from .douyin_runner import run_account_spark_sync, AccountResult

log = logging.getLogger("das.scheduler")

scheduler = BackgroundScheduler(timezone="Asia/Shanghai")
_running_lock = threading.Lock()
_current_run = None
_last_run_summary = None


def _now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def get_current_run() -> dict | None:
    """返回正在进行/最近一次的运行状态"""
    if _current_run is not None:
        return _current_run
    return _last_run_summary


def run_spark_task(trigger_type: str = "manual", account_ids: list[int] | None = None) -> dict:
    """
    执行一次完整的续火任务：遍历启用账号 → 依次续火 → 记录日志 → 汇总
    线程安全（同一时刻只允许一个运行）
    """
    global _current_run, _last_run_summary

    if not _running_lock.acquire(blocking=False):
        log.warning("已有续火任务在运行，跳过本次触发")
        return {"status": "skipped", "message": "已有任务在运行"}

    task_id = uuid.uuid4().hex[:12]
    database.create_task(task_id, trigger_type)
    started = _now_str()
    _current_run = {
        "task_id": task_id,
        "status": "running",
        "trigger_type": trigger_type,
        "started_at": started,
        "progress": 0,
        "accounts_total": 0,
        "accounts_done": 0,
        "current_account": "",
        "message": "正在初始化...",
    }

    log.info("开始续火任务 %s（%s）", task_id, trigger_type)

    try:
        accounts = database.get_enabled_accounts()
        if account_ids:
            ids = set(account_ids)
            accounts = [a for a in accounts if a["id"] in ids]

        _current_run["accounts_total"] = len(accounts)
        if not accounts:
            summary = _finish(task_id, "success", "没有可用账号", started, {
                "accounts": 0, "total": 0, "success": 0, "fail": 0, "detail": []
            })
            return summary

        # 加载防封策略
        policy = AntiBanPolicy.from_settings()
        log.info(policy.describe())

        overall = []
        total = success = fail = 0

        for idx, acc in enumerate(accounts, start=1):
            _current_run["current_account"] = acc["name"]
            # 防封等待
            if idx > 1 or policy.should_wait():
                wait = policy.wait_between_accounts(idx, len(accounts))
                if wait:
                    _current_run["message"] = f"防封等待 {wait:.0f}s 后处理账号 {acc['name']}"

            _current_run["message"] = f"正在处理账号 {acc['name']} ({idx}/{len(accounts)})"
            result = run_account_spark_sync(acc, task_id)

            # 更新账号状态
            database.touch_account_result(acc["id"], result.status, result.message)

            entry = {
                "name": acc.get("name", "未命名账号"),
                "status": result.status,
                "channel": _safe_channel_label(result.channel, acc.get("proxy", "")),
                "message": result.message,
                "total": result.total,
                "success": result.success,
                "fail": result.fail,
                "detail": result.detail,
            }
            overall.append(entry)
            total += result.total
            success += result.success
            fail += result.fail

            _current_run["accounts_done"] += 1
            _current_run["progress"] = round(len(overall) / len(accounts) * 100)

        # 汇总
        if fail > 0 and success == 0:
            status = "failed"
        elif fail > 0:
            status = "partial"
        else:
            status = "success"

        summary = _finish(task_id, status, "完成", started, {
            "accounts": len(overall),
            "total": total,
            "success": success,
            "fail": fail,
            "detail": overall,
            "time": _now_str(),
            "task_id": task_id,
            "trigger_type": trigger_type,
        })

        log.info("续火任务完成：成功 %d / 失败 %d", success, fail)

        # TG 推送
        try:
            tg_sender.push_summary(summary)
        except Exception as e:
            log.warning("TG 推送失败：%s", e)

        return summary

    except Exception as exc:
        log.exception("续火任务异常")
        summary = _finish(task_id, "failed", f"异常：{exc}", started, {
            "accounts": 0, "total": 0, "success": 0, "fail": 0,
            "detail": [], "time": _now_str(), "task_id": task_id,
            "trigger_type": trigger_type, "error": str(exc),
        })
        return summary
    finally:
        _running_lock.release()


def _safe_channel_label(channel: str, proxy_url: str) -> str:
    if channel == "socks":
        return "SOCKS5 代理"
    return "直连"


def _finish(task_id: str, status: str, message: str, started: str, summary: dict) -> dict:
    global _current_run, _last_run_summary
    finished = _now_str()
    database.finish_task(task_id, status, message)
    summary["status"] = status
    summary["finished_at"] = finished
    summary["message"] = message
    database.set_settings({"last_spark_time": finished})
    _current_run = None
    _last_run_summary = summary
    return summary


# ==================== 定时调度 ====================

def _fire_scheduled():
    log.info("定时任务触发，开始续火")
    run_spark_task(trigger_type="schedule")


def next_run_info() -> dict:
    """返回下一次定时续火的信息"""
    enabled = database.get_setting("schedule_enabled", "1") == "1"
    cron_expr = database.get_setting("schedule_cron", "0 8 * * *")
    info = {"enabled": enabled, "cron": cron_expr, "next_run": None, "seconds_left": None}

    if not enabled:
        return info

    job = scheduler.get_job("douyin_spark")
    nxt = getattr(job, "next_run_time", None) if job else None
    if not nxt:
        return info

    info["next_run"] = nxt.strftime("%Y-%m-%d %H:%M:%S")
    try:
        delta = (nxt - datetime.now(nxt.tzinfo)).total_seconds()
        info["seconds_left"] = int(delta) if delta > 0 else 0
    except Exception:
        pass
    return info


def reload_schedule() -> None:
    """根据当前设置重建定时任务"""
    existing = scheduler.get_job("douyin_spark")
    if existing:
        existing.remove()

    enabled = database.get_setting("schedule_enabled", "1") == "1"
    cron_expr = database.get_setting("schedule_cron", "0 8 * * *")
    if not enabled:
        log.info("定时续火已关闭")
        return

    try:
        parts = cron_expr.strip().split()
        fixed = cron_expr.strip()
        if len(parts) == 6:
            fixed = " ".join(parts[1:])
        trigger = CronTrigger.from_crontab(fixed, timezone="Asia/Shanghai")
        scheduler.add_job(
            _fire_scheduled, trigger, id="douyin_spark",
            name=f"抖音定时续火 ({fixed})",
            misfire_grace_time=300, coalesce=True,
        )
        log.info("已配置定时续火：%s", fixed)
    except Exception as exc:
        log.error("定时表达式无效 %r：%s", cron_expr, exc)


def start_scheduler() -> None:
    """启动调度器（幂等）"""
    if not scheduler.running:
        scheduler.start()

    # 每日清理过期日志
    if not scheduler.get_job("log_purge"):
        scheduler.add_job(
            _purge_logs_job,
            trigger=CronTrigger(hour=4, minute=30, timezone="Asia/Shanghai"),
            id="log_purge", max_instances=1, coalesce=True, misfire_grace_time=3600,
        )

    reload_schedule()
    log.info("调度器已启动")


def _purge_logs_job() -> None:
    try:
        days = int(database.get_setting("log_retention_days", "30") or 0)
    except ValueError:
        days = 30
    if days <= 0:
        return
    removed = database.purge_old_logs(days)
    if removed:
        log.info("已清理 %d 条超过 %d 天的日志", removed, days)


def stop_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
        log.info("调度器已停止")
