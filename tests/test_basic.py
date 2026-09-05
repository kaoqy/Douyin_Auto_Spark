# 抖音续火花管理面板 - 测试
import pytest
import sys
import os
import json
import tempfile
from pathlib import Path

# 设置测试数据目录
os.environ["DAS_DATA_DIR"] = tempfile.mkdtemp()

# 确保能导入 app
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import database, auth


@pytest.fixture(autouse=True)
def setup_db():
    """每个测试前初始化数据库"""
    # 删除旧数据库文件确保测试隔离
    if database.DB_PATH.exists():
        database.DB_PATH.unlink()
    database.close_conn()
    database.init_db()
    yield
    database.close_conn()


class TestDatabase:
    def test_init_db(self):
        """测试数据库初始化"""
        assert database.DB_PATH.exists()

    def test_count_users_initially_zero(self):
        assert database.count_users() == 0

    def test_add_user(self):
        uid = database.create_user("testuser", auth.hash_password("password123"))
        assert uid > 0
        assert database.count_users() == 1

    def test_get_user(self):
        database.create_user("testuser", auth.hash_password("password123"))
        user = database.get_user_by_username("testuser")
        assert user is not None
        assert user["username"] == "testuser"

    def test_add_account(self):
        aid = database.add_account("测试账号", "[]", "socks5://user:pass@host:1080")
        assert aid > 0
        accounts = database.get_accounts()
        assert len(accounts) == 1
        assert accounts[0]["name"] == "测试账号"

    def test_mask_proxy(self):
        masked = database.mask_proxy_url("socks5://user:pass@host:1080")
        assert masked == "socks5://***@host:1080"

    def test_add_target(self):
        aid = database.add_account("测试账号", "[]")
        tid = database.add_target(aid, "好友A")
        assert tid > 0
        targets = database.get_targets(aid)
        assert len(targets) == 1
        assert targets[0]["name"] == "好友A"

    def test_session(self):
        uid = database.create_user("testuser", auth.hash_password("password123"))
        database.create_session("test-token", uid, "2099-12-31 23:59:59")
        user = database.get_session_user("test-token")
        assert user is not None
        assert user["username"] == "testuser"

    def test_settings(self):
        database.set_settings({"test_key": "test_value"})
        assert database.get_setting("test_key") == "test_value"

    def test_logs(self):
        database.add_log({
            "task_id": "test-123",
            "account_id": 1,
            "account_name": "测试",
            "target_name": "好友A",
            "status": "success",
            "message": "测试消息",
        })
        logs = database.get_logs()
        assert len(logs) == 1
        assert logs[0]["status"] == "success"


class TestAuth:
    def test_hash_password(self):
        h1 = auth.hash_password("password123")
        h2 = auth.hash_password("password123")
        assert h1 == h2

    def test_verify_password(self):
        h = auth.hash_password("password123")
        assert auth.verify_password("password123", h) is True
        assert auth.verify_password("wrong", h) is False

    def test_login(self):
        database.create_user("testuser", auth.hash_password("password123"))
        token = auth.login("testuser", "password123")
        assert token is not None
        assert len(token) == 64

    def test_login_wrong_password(self):
        database.create_user("testuser", auth.hash_password("password123"))
        assert auth.login("testuser", "wrong") is None

    def test_logout(self):
        database.create_user("testuser", auth.hash_password("password123"))
        token = auth.login("testuser", password="password123")
        auth.logout(token)
        assert auth.get_current_user(token) is None


class TestYiyan:
    def test_fetch_yiyan_from_api(self):
        """测试从 hitokoto.cn 获取一言"""
        from app import yiyan
        result = yiyan.fetch_yiyan_from_api()
        if result is not None:
            assert "hitokoto" in result
            assert isinstance(result["hitokoto"], str)

    def test_render_message_default(self):
        """测试默认消息渲染"""
        from app import yiyan
        item = {"hitokoto": "测试一言", "source": "测试来源", "from_who": "测试作者"}
        msg = yiyan.render_message(None, "账号A", "好友B", yiyan_item=item, include_source=True)
        assert "测试一言" in msg
        assert "测试作者" in msg

    def test_render_message_template(self):
        """测试模板消息渲染"""
        from app import yiyan
        item = {"hitokoto": "模板一言", "source": "模板来源", "from_who": "模板作者"}
        template = "{{friend}}，{{account}} 续火啦\n{{yiyan}}\n{{from}}"
        msg = yiyan.render_message(template, "我的账号", "好友A", yiyan_item=item)
        assert "好友A" in msg
        assert "我的账号" in msg
        assert "模板一言" in msg
        assert "模板作者" in msg


class TestDouyinCookie:
    def test_parse_cookie_json(self):
        from app.douyin_cookie import parse_cookie_json
        raw = '[{"domain":".douyin.com","name":"test","value":"val","path":"/","secure":true,"httpOnly":false,"sameSite":"no_restriction"}]'
        cookies = parse_cookie_json(raw)
        assert len(cookies) == 1
        assert cookies[0].name == "test"
        assert cookies[0].value == "val"

    def test_to_playwright_cookie(self):
        from app.douyin_cookie import parse_cookie_json
        raw = '[{"domain":".douyin.com","name":"test","value":"val","path":"/","secure":true,"httpOnly":false,"sameSite":"no_restriction","expirationDate":1234567890.0}]'
        cookies = parse_cookie_json(raw)
        pc = cookies[0].to_playwright_cookie()
        assert pc["name"] == "test"
        assert pc["expires"] == 1234567890.0
