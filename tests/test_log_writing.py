"""测试：scheduler 写入 logs 表，fetch_friend_list 返回 dict。"""
from __future__ import annotations

import os
import tempfile

import pytest

from app import database, scheduler, douyin_runner


@pytest.fixture
def tmp_data(monkeypatch):
    """每个测试用独立 DB_DIR。DB_PATH 在模块导入时确定，需要重新加载。"""
    import importlib
    tmp = tempfile.mkdtemp()
    monkeypatch.setenv("DAS_DATA_DIR", tmp)
    # 重置 module-level DB_PATH
    import os
    from pathlib import Path
    database.DB_PATH = Path(tmp) / "douyin_spark.db"
    # 清空 connection 缓存（如果用了）
    importlib.reload(database)
    importlib.reload(scheduler)
    database.init_db()
    return tmp


def test_scheduler_writes_account_and_detail_logs(tmp_data, monkeypatch):
    """_write_run_logs 把 account status + detail 列表写入 logs 表。"""
    # 创建一个账号
    acc_id = database.add_account("测试账号", "[]", "")
    database.add_target(acc_id, "好友A", enabled=True)
    database.add_target(acc_id, "好友B", enabled=True)

    # 造一个 fake run result
    from app.douyin_runner import AccountResult
    result = AccountResult(
        account_id=acc_id,
        account_name="测试账号",
        status="partial",
        channel="direct",
        message="以下会话未找到：好友B",
        total=2,
        success=1,
        fail=1,
        detail=[
            {"target": "好友A", "status": "success", "message": "已发送"},
            {"target": "好友B", "status": "failed", "message": "无法定位输入框"},
        ],
    )

    acc = database.get_account(acc_id)
    scheduler._write_run_logs(acc, "task_test_001", result)

    # 验证 logs 表里能查到
    all_logs = database.get_logs(limit=50)
    assert len(all_logs) >= 2, f"expected >=2 log entries, got {len(all_logs)}: {all_logs}"

    msgs = [l["message"] for l in all_logs]
    targets = [l["target_name"] for l in all_logs]
    statuses = [l["status"] for l in all_logs]

    assert "无法定位输入框" in msgs, f"missing 详情日志: {msgs}"
    assert "好友B" in targets
    assert "好友A" in targets
    assert "failed" in statuses
    assert "success" in statuses


def test_scheduler_writes_no_log_for_full_success(tmp_data):
    """账号状态 success（result.status == success）时不写账号级日志，但 detail 仍会写。"""
    acc_id = database.add_account("全成功账号", "[]", "")
    from app.douyin_runner import AccountResult
    result = AccountResult(
        account_id=acc_id,
        account_name="全成功账号",
        status="success",
        channel="direct",
        message="成功续火 2 个好友",
        total=2,
        success=2,
        fail=0,
        detail=[
            {"target": "A", "status": "success", "message": "已发送"},
            {"target": "B", "status": "success", "message": "已发送"},
        ],
    )
    acc = database.get_account(acc_id)
    scheduler._write_run_logs(acc, "task_test_002", result)
    logs = database.get_logs(limit=50, account_id=acc_id)
    # 只有 detail（2 条），账号级 success 不写
    assert len(logs) == 2, f"got {len(logs)} logs: {logs}"
    assert all(l["target_name"] for l in logs)
    assert all(l["status"] == "success" for l in logs)


def test_scheduler_writes_log_with_proxy(tmp_data):
    """带 SOCKS5 代理的账号，日志 channel 标记为 SOCKS5 代理。"""
    acc_id = database.add_account("代理账号", "[]", "socks5://u:p@1.2.3.4:1080")
    from app.douyin_runner import AccountResult
    result = AccountResult(
        account_id=acc_id,
        account_name="代理账号",
        status="failed",
        channel="socks",
        message="代理初始化失败：gost 未安装",
        total=0,
        success=0,
        fail=0,
        detail=[],
    )
    acc = database.get_account(acc_id)
    scheduler._write_run_logs(acc, "task_test_003", result)
    logs = database.get_logs(limit=50, account_id=acc_id)
    assert len(logs) == 1, f"got {len(logs)} logs: {logs}"
    assert logs[0]["channel"] == "SOCKS5 代理"
    assert logs[0]["status"] == "failed"


# ===== fetch_friend_list 返回 dict =====

def test_fetch_friend_list_sync_returns_dict():
    """fetch_friend_list_sync 总是返回 dict，即使账号不存在。"""
    # 同步函数内部会走 asyncio.run(fetch_friend_list(...))
    # 没有真实 Playwright 也能跑：会失败但返回 dict
    from app.douyin_runner import fetch_friend_list_sync
    # 缺 cookie 字段触发 no_cookies
    acc = {"id": 1, "name": "x", "cookie": "", "proxy": ""}
    result = fetch_friend_list_sync(acc)
    assert isinstance(result, dict)
    assert "friends" in result
    assert "message" in result
    assert "reason" in result
    # 缺 cookie 应该是 exception / no_cookies（实际取决于 parse_cookie_json 行为）
    assert result["friends"] == []
    assert result["reason"] in ("no_cookies", "exception", "proxy_failed", "empty", "login_page", "")
