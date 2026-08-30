# 抖音自动续火花管理面板 - 认证
from __future__ import annotations

import hashlib
import logging
import os
import secrets
from datetime import datetime, timedelta
from typing import Any

from . import database

log = logging.getLogger("das.auth")

COOKIE_NAME = "das_session"
SESSION_DAYS = 7


def hash_password(password: str) -> str:
    """SHA-256 密码哈希（带固定盐）"""
    salt = "douyin-auto-spark-v1"
    return hashlib.sha256(f"{salt}{password}".encode()).hexdigest()


def verify_password(password: str, password_hash: str) -> bool:
    return hash_password(password) == password_hash


def generate_token() -> str:
    return secrets.token_hex(32)


def login(username: str, password: str) -> str | None:
    """验证用户名密码，成功返回 session token，失败返回 None"""
    user = database.get_user_by_username(username)
    if not user:
        return None
    if not verify_password(password, user["password_hash"]):
        return None
    token = generate_token()
    expires_at = (datetime.now() + timedelta(days=SESSION_DAYS)).strftime("%Y-%m-%d %H:%M:%S")
    database.create_session(token, user["id"], expires_at)
    return token


def logout(token: str) -> None:
    if token:
        database.delete_session(token)


def get_current_user(token: str) -> dict | None:
    if not token:
        return None
    return database.get_session_user(token)


def auth_enabled() -> bool:
    """是否启用了登录（有用户且非首次部署）"""
    return database.count_users() > 0


def ensure_default_admin() -> None:
    """首次部署时创建默认管理员"""
    if database.count_users() == 0:
        admin_user = os.environ.get("DAS_ADMIN_USER", "admin")
        admin_pass = os.environ.get("DAS_ADMIN_PASSWORD", "admin123")
        database.create_user(admin_user, hash_password(admin_pass))
        log.warning("已创建默认管理员：%s / %s（请尽快修改密码）", admin_user, admin_pass)


def change_password(user_id: int, new_password: str) -> bool:
    """修改密码"""
    new_hash = hash_password(new_password)
    conn = database.get_conn()
    conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (new_hash, user_id))
    conn.commit()
    return True
