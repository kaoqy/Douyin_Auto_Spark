# 抖音续火花管理面板 - 调度器测试
import pytest
import sys
import os
import tempfile
from datetime import datetime

os.environ["DAS_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import database, auth, scheduler


@pytest.fixture(autouse=True)
def setup_db():
    if database.DB_PATH.exists():
        database.DB_PATH.unlink()
    database.close_conn()
    database.init_db()
    yield
    database.close_conn()


class TestScheduler:
    def test_next_run_info_default(self):
        info = scheduler.next_run_info()
        assert "enabled" in info
        assert "cron" in info
        assert "next_run" in info
        assert "seconds_left" in info

    def test_next_run_info_disabled(self):
        database.set_settings({"schedule_enabled": "0"})
        info = scheduler.next_run_info()
        assert info["enabled"] is False

    def test_next_run_info_enabled(self):
        database.set_settings({"schedule_enabled": "1", "schedule_cron": "0 8 * * *"})
        info = scheduler.next_run_info()
        assert info["enabled"] is True
        assert info["cron"] == "0 8 * * *"

    def test_current_run_initially_none(self):
        assert scheduler.get_current_run() is None

    def test_running_lock(self):
        """测试运行锁 - 同一时刻只能有一个任务"""
        import threading

        # 锁初始应该是未锁定的
        assert scheduler._running_lock.acquire(blocking=False) is True
        # 现在已被锁定，再次获取应该失败
        assert scheduler._running_lock.acquire(blocking=False) is False
        # 释放后应该能再次获取
        scheduler._running_lock.release()
        assert scheduler._running_lock.acquire(blocking=False) is True
        scheduler._running_lock.release()
