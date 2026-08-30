# 抖音续火花管理面板 - API 测试
import pytest
import sys
import os
import tempfile

os.environ["DAS_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import database, auth
from app.main import app
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def setup_db():
    if database.DB_PATH.exists():
        database.DB_PATH.unlink()
    database.close_conn()
    database.init_db()
    yield
    database.close_conn()


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def authenticated_client(client):
    """已认证的测试客户端"""
    # 创建用户
    database.create_user("admin", auth.hash_password("admin123"))
    # 登录
    resp = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    assert resp.status_code == 200
    return client


class TestHealth:
    def test_health(self, client):
        resp = client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True


class TestAuthAPI:
    def test_login_page(self, client):
        resp = client.get("/login.html")
        assert resp.status_code == 200

    def test_init_flow(self, client):
        # 检查是否需要初始化
        resp = client.get("/api/auth/needs-init")
        assert resp.status_code == 200
        assert resp.json()["needs_init"] is True

    def test_init_admin(self, client):
        resp = client.post("/api/auth/init", json={"username": "admin", "password": "admin123"})
        assert resp.status_code == 200

    def test_login_after_init(self, client):
        # 先初始化
        client.post("/api/auth/init", json={"username": "admin", "password": "admin123"})
        # 再登录
        resp = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
        assert resp.status_code == 200

    def test_login_wrong_password(self, client):
        client.post("/api/auth/init", json={"username": "admin", "password": "admin123"})
        resp = client.post("/api/auth/login", json={"username": "admin", "password": "wrong"})
        assert resp.status_code == 401

    def test_me(self, authenticated_client):
        resp = authenticated_client.get("/api/auth/me")
        assert resp.status_code == 200
        assert resp.json()["user"]["username"] == "admin"

    def test_logout(self, authenticated_client):
        resp = authenticated_client.post("/api/auth/logout")
        assert resp.status_code == 200


class TestAccountsAPI:
    def test_list_accounts_empty(self, authenticated_client):
        resp = authenticated_client.get("/api/accounts")
        assert resp.status_code == 200
        assert resp.json()["accounts"] == []

    def test_create_account(self, authenticated_client):
        resp = authenticated_client.post("/api/accounts", json={
            "name": "测试账号",
            "cookie": '[{"domain":".douyin.com","name":"test","value":"val"}]',
            "proxy": "socks5://user:pass@host:1080",
        })
        assert resp.status_code == 200
        assert resp.json()["id"] > 0

    def test_create_account_no_cookie(self, authenticated_client):
        resp = authenticated_client.post("/api/accounts", json={"name": "test"})
        assert resp.status_code == 400

    def test_mask_proxy_in_list(self, authenticated_client):
        authenticated_client.post("/api/accounts", json={
            "name": "测试账号",
            "cookie": '[{"domain":".douyin.com","name":"test","value":"val"}]',
            "proxy": "socks5://user:pass@host:1080",
        })
        resp = authenticated_client.get("/api/accounts")
        accounts = resp.json()["accounts"]
        assert accounts[0]["proxy"] == "socks5://***@host:1080"


class TestTargetsAPI:
    def test_list_targets_empty(self, authenticated_client):
        resp = authenticated_client.get("/api/targets")
        assert resp.status_code == 200
        assert resp.json()["targets"] == []

    def test_create_target(self, authenticated_client):
        # 先创建账号
        acc = authenticated_client.post("/api/accounts", json={
            "name": "测试账号",
            "cookie": '[{"domain":".douyin.com","name":"test","value":"val"}]',
        })
        acc_id = acc.json()["id"]
        # 创建好友
        resp = authenticated_client.post("/api/targets", json={
            "account_id": acc_id,
            "name": "好友A",
        })
        assert resp.status_code == 200


class TestSettingsAPI:
    def test_get_settings(self, authenticated_client):
        resp = authenticated_client.get("/api/settings")
        assert resp.status_code == 200

    def test_update_settings(self, authenticated_client):
        resp = authenticated_client.put("/api/settings", json={
            "schedule_cron": "0 9 * * *",
            "schedule_enabled": "1",
        })
        assert resp.status_code == 200


class TestLogsAPI:
    def test_list_logs_empty(self, authenticated_client):
        resp = authenticated_client.get("/api/logs")
        assert resp.status_code == 200
        assert resp.json()["logs"] == []


class TestYiyanAPI:
    def test_list_yiyan(self, authenticated_client):
        resp = authenticated_client.get("/api/yiyan")
        assert resp.status_code == 200

    def test_add_yiyan(self, authenticated_client):
        resp = authenticated_client.post("/api/yiyan", json={
            "hitokoto": "测试一言",
            "source": "测试来源",
        })
        assert resp.status_code == 200

    def test_random_yiyan(self, authenticated_client):
        authenticated_client.post("/api/yiyan", json={
            "hitokoto": "随机测试",
            "source": "测试",
        })
        resp = authenticated_client.get("/api/yiyan/random")
        assert resp.status_code == 200
