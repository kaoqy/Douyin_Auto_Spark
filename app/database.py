# 抖音自动续火花管理面板 - 数据库
from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

DB_PATH = Path(os.environ.get("DAS_DATA_DIR", str(Path(__file__).resolve().parent.parent / "data"))) / "douyin_spark.db"

log = logging.getLogger("das.database")

# 线程本地存储
_local = threading.local()


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def get_conn() -> sqlite3.Connection:
    """获取当前线程的数据库连接"""
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = sqlite3.connect(str(DB_PATH), timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        _local.conn = conn
    return conn


def close_conn():
    """关闭当前线程的数据库连接"""
    conn = getattr(_local, "conn", None)
    if conn is not None:
        conn.close()
        _local.conn = None


def init_db() -> None:
    """初始化数据库表"""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = get_conn()
    conn.executescript("""
        -- 用户表（管理员登录）
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now', 'localtime'))
        );

        -- 会话表
        CREATE TABLE IF NOT EXISTS sessions (
            token TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id),
            created_at TEXT DEFAULT (datetime('now', 'localtime')),
            expires_at TEXT NOT NULL
        );

        -- 抖音账号表
        CREATE TABLE IF NOT EXISTS accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            cookie TEXT NOT NULL,
            proxy TEXT DEFAULT '',
            enabled INTEGER DEFAULT 1,
            created_at TEXT DEFAULT (datetime('now', 'localtime')),
            last_run TEXT,
            last_status TEXT,
            last_message TEXT,
            last_verify_at TEXT,
            last_verify_status TEXT,
            last_verify_message TEXT
        );

        -- 好友表（续火对象）
        CREATE TABLE IF NOT EXISTS targets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            enabled INTEGER DEFAULT 1,
            created_at TEXT DEFAULT (datetime('now', 'localtime')),
            last_run TEXT,
            last_status TEXT,
            UNIQUE(account_id, name)
        );

        -- 任务表（定时任务记录）
        CREATE TABLE IF NOT EXISTS tasks (
            id TEXT PRIMARY KEY,
            trigger_type TEXT DEFAULT 'manual',
            status TEXT DEFAULT 'pending',
            message TEXT DEFAULT '',
            started_at TEXT,
            finished_at TEXT
        );

        -- 日志表
        CREATE TABLE IF NOT EXISTS logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT,
            account_id INTEGER,
            account_name TEXT,
            target_name TEXT,
            status TEXT,
            channel TEXT DEFAULT 'direct',
            message TEXT DEFAULT '',
            detail TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now', 'localtime'))
        );

        -- 设置表
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT DEFAULT ''
        );

        -- 一言库
        CREATE TABLE IF NOT EXISTS yiyan (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            hitokoto TEXT NOT NULL,
            source TEXT DEFAULT '',
            enabled INTEGER DEFAULT 1,
            created_at TEXT DEFAULT (datetime('now', 'localtime'))
        );

        -- SOCKS5 代理节点表
        CREATE TABLE IF NOT EXISTS proxies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            label TEXT DEFAULT '',
            ip TEXT DEFAULT '',
            port INTEGER DEFAULT 0,
            username TEXT DEFAULT '',
            password TEXT DEFAULT '',
            url TEXT DEFAULT '',
            geo_country TEXT DEFAULT '',
            geo_region TEXT DEFAULT '',
            geo_city TEXT DEFAULT '',
            geo_country_code TEXT DEFAULT '',
            geo_ip TEXT DEFAULT '',
            enabled INTEGER DEFAULT 1,
            remark TEXT DEFAULT '',
            last_test TEXT DEFAULT '',
            last_latency_ms INTEGER DEFAULT 0,
            last_test_at TEXT DEFAULT '',
            last_test_message TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now', 'localtime')),
            updated_at TEXT DEFAULT (datetime('now', 'localtime'))
        );

        -- 创建索引
        CREATE INDEX IF NOT EXISTS idx_targets_account ON targets(account_id);
        CREATE INDEX IF NOT EXISTS idx_logs_task ON logs(task_id);
        CREATE INDEX IF NOT EXISTS idx_logs_created ON logs(created_at);
    """)
    conn.commit()
    _seed_defaults(conn)
    _migrate_db(conn)


def _migrate_db(conn: sqlite3.Connection) -> None:
    """数据库迁移（增量添加字段等）。"""
    proxy_cols = {row[1] for row in conn.execute("PRAGMA table_info(proxies)").fetchall()}
    if "geo_city" not in proxy_cols:
        conn.execute("ALTER TABLE proxies ADD COLUMN geo_city TEXT DEFAULT ''")

    account_cols = {row[1] for row in conn.execute("PRAGMA table_info(accounts)").fetchall()}
    account_migrations = {
        "last_verify_at": "TEXT",
        "last_verify_status": "TEXT",
        "last_verify_message": "TEXT",
    }
    for column, column_type in account_migrations.items():
        if column not in account_cols:
            conn.execute(f"ALTER TABLE accounts ADD COLUMN {column} {column_type}")

    conn.commit()


def _seed_defaults(conn: sqlite3.Connection) -> None:
    """写入默认设置"""
    defaults = {
        "tg_enabled": "0",
        "tg_bot_token": "",
        "tg_user_id": "",
        "tg_quote_enabled": "1",
        "tg_only_on_change": "0",
        "tg_silent": "0",
        "schedule_enabled": "1",
        "schedule_cron": "0 8 * * *",
        "anti_ban_enabled": "1",
        "anti_ban_wait_min": "120",
        "anti_ban_wait_max": "300",
        "anti_ban_window_hour": "7",
        "proxy_force": "0",
        "proxy_fallback": "1",
        "spark_delay_min": "3",
        "spark_delay_max": "8",
        "log_retention_days": "30",
        "message_template": "",
        "yiyan_include_source": "1",
    }
    for k, v in defaults.items():
        conn.execute(
            "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
            (k, v),
        )
    conn.commit()


# ==================== 用户与认证 ====================

def count_users() -> int:
    conn = get_conn()
    return conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]


def create_user(username: str, password_hash: str) -> int:
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO users (username, password_hash) VALUES (?, ?)",
        (username, password_hash),
    )
    conn.commit()
    return cur.lastrowid


def get_user_by_username(username: str) -> dict | None:
    conn = get_conn()
    row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    return dict(row) if row else None


def get_user_by_id(user_id: int) -> dict | None:
    conn = get_conn()
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return dict(row) if row else None


# ==================== 会话管理 ====================

def create_session(token: str, user_id: int, expires_at: str) -> None:
    conn = get_conn()
    conn.execute(
        "INSERT INTO sessions (token, user_id, expires_at) VALUES (?, ?, ?)",
        (token, user_id, expires_at),
    )
    conn.commit()


def get_session_user(token: str) -> dict | None:
    conn = get_conn()
    row = conn.execute(
        """SELECT s.token, s.user_id, u.username FROM sessions s
           JOIN users u ON s.user_id = u.id
           WHERE s.token = ? AND s.expires_at > datetime('now', 'localtime')""",
        (token,),
    ).fetchone()
    return dict(row) if row else None


def delete_session(token: str) -> None:
    conn = get_conn()
    conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
    conn.commit()


def purge_expired_sessions() -> int:
    conn = get_conn()
    cur = conn.execute("DELETE FROM sessions WHERE expires_at < datetime('now', 'localtime')")
    conn.commit()
    return cur.rowcount


# ==================== 账号管理 ====================

def add_account(name: str, cookie: str, proxy: str = "", enabled: bool = True) -> int:
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO accounts (name, cookie, proxy, enabled) VALUES (?, ?, ?, ?)",
        (name, cookie, proxy, 1 if enabled else 0),
    )
    conn.commit()
    return cur.lastrowid


def update_account(account_id: int, **kwargs: Any) -> bool:
    conn = get_conn()
    allowed = {"name", "cookie", "proxy", "enabled"}
    sets = []
    vals = []
    for k, v in kwargs.items():
        if k not in allowed:
            continue
        sets.append(f"{k} = ?")
        vals.append(v)
    if not sets:
        return False
    vals.append(account_id)
    conn.execute(f"UPDATE accounts SET {', '.join(sets)} WHERE id = ?", vals)
    conn.commit()
    return True


def delete_account(account_id: int) -> None:
    conn = get_conn()
    conn.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
    conn.commit()


def get_accounts() -> list[dict]:
    conn = get_conn()
    rows = conn.execute("SELECT * FROM accounts ORDER BY id").fetchall()
    return [dict(r) for r in rows]


def get_account(account_id: int) -> dict | None:
    conn = get_conn()
    row = conn.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()
    return dict(row) if row else None


def get_enabled_accounts() -> list[dict]:
    conn = get_conn()
    rows = conn.execute("SELECT * FROM accounts WHERE enabled = 1 ORDER BY id").fetchall()
    return [dict(r) for r in rows]


def touch_account_result(account_id: int, status: str, message: str = "") -> None:
    conn = get_conn()
    conn.execute(
        "UPDATE accounts SET last_run = datetime('now', 'localtime'), last_status = ?, last_message = ? WHERE id = ?",
        (status, message, account_id),
    )
    conn.commit()


def touch_account_verify(account_id: int, valid: bool, message: str = "") -> None:
    """保存账号 Cookie 最近一次验证结果。"""
    conn = get_conn()
    conn.execute(
        "UPDATE accounts SET last_verify_at = datetime('now', 'localtime'), last_verify_status = ?, last_verify_message = ? WHERE id = ?",
        ("valid" if valid else "invalid", message, account_id),
    )
    conn.commit()


# ==================== 好友管理 ====================

def add_target(account_id: int, name: str, enabled: bool = True) -> int:
    conn = get_conn()
    cur = conn.execute(
        "INSERT OR IGNORE INTO targets (account_id, name, enabled) VALUES (?, ?, ?)",
        (account_id, name, 1 if enabled else 0),
    )
    conn.commit()
    return cur.lastrowid


def update_target(target_id: int, **kwargs: Any) -> bool:
    conn = get_conn()
    allowed = {"name", "enabled"}
    sets = []
    vals = []
    for k, v in kwargs.items():
        if k not in allowed:
            continue
        sets.append(f"{k} = ?")
        vals.append(v)
    if not sets:
        return False
    vals.append(target_id)
    conn.execute(f"UPDATE targets SET {', '.join(sets)} WHERE id = ?", vals)
    conn.commit()
    return True


def delete_target(target_id: int) -> None:
    conn = get_conn()
    conn.execute("DELETE FROM targets WHERE id = ?", (target_id,))
    conn.commit()


def get_targets(account_id: int | None = None) -> list[dict]:
    conn = get_conn()
    if account_id is not None:
        rows = conn.execute(
            "SELECT * FROM targets WHERE account_id = ? ORDER BY id", (account_id,)
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM targets ORDER BY account_id, id").fetchall()
    return [dict(r) for r in rows]


def get_enabled_targets(account_id: int) -> list[dict]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM targets WHERE account_id = ? AND enabled = 1 ORDER BY id",
        (account_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def touch_target_result(target_id: int, status: str) -> None:
    conn = get_conn()
    conn.execute(
        "UPDATE targets SET last_run = datetime('now', 'localtime'), last_status = ? WHERE id = ?",
        (status, target_id),
    )
    conn.commit()


# ==================== 任务管理 ====================

def create_task(task_id: str, trigger_type: str = "manual") -> None:
    conn = get_conn()
    conn.execute(
        "INSERT INTO tasks (id, trigger_type, status, started_at) VALUES (?, ?, 'running', datetime('now', 'localtime'))",
        (task_id, trigger_type),
    )
    conn.commit()


def finish_task(task_id: str, status: str, message: str = "") -> None:
    conn = get_conn()
    conn.execute(
        "UPDATE tasks SET status = ?, message = ?, finished_at = datetime('now', 'localtime') WHERE id = ?",
        (status, message, task_id),
    )
    conn.commit()


def get_tasks(limit: int = 20) -> list[dict]:
    conn = get_conn()
    rows = conn.execute("SELECT * FROM tasks ORDER BY started_at DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


def get_task(task_id: str) -> dict | None:
    conn = get_conn()
    row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    return dict(row) if row else None


# ==================== 日志管理 ====================

def add_log(entry: dict) -> int:
    conn = get_conn()
    cur = conn.execute(
        """INSERT INTO logs (task_id, account_id, account_name, target_name, status, channel, message, detail)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            entry.get("task_id", ""),
            entry.get("account_id"),
            entry.get("account_name", ""),
            entry.get("target_name", ""),
            entry.get("status", ""),
            entry.get("channel", "direct"),
            entry.get("message", ""),
            entry.get("detail", ""),
        ),
    )
    conn.commit()
    return cur.lastrowid


def get_logs(limit: int = 100, offset: int = 0, status: str | None = None, account_id: int | None = None) -> list[dict]:
    conn = get_conn()
    query = "SELECT * FROM logs WHERE 1=1"
    params: list[Any] = []
    if status:
        query += " AND status = ?"
        params.append(status)
    if account_id:
        query += " AND account_id = ?"
        params.append(account_id)
    query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def purge_old_logs(days: int) -> int:
    conn = get_conn()
    cur = conn.execute(
        "DELETE FROM logs WHERE created_at < datetime('now', 'localtime', ?)",
        (f"-{days} days",),
    )
    conn.commit()
    return cur.rowcount


# ==================== 设置管理 ====================

def get_setting(key: str, default: str = "") -> str:
    conn = get_conn()
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_settings(values: dict[str, str]) -> None:
    conn = get_conn()
    for k, v in values.items():
        conn.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
            (k, v),
        )
    conn.commit()


def get_all_settings() -> dict[str, str]:
    conn = get_conn()
    rows = conn.execute("SELECT key, value FROM settings").fetchall()
    return {r["key"]: r["value"] for r in rows}


# ==================== 一言库 ====================

def get_yiyan_list(enabled_only: bool = True) -> list[dict]:
    conn = get_conn()
    if enabled_only:
        rows = conn.execute("SELECT * FROM yiyan WHERE enabled = 1 ORDER BY id").fetchall()
    else:
        rows = conn.execute("SELECT * FROM yiyan ORDER BY id").fetchall()
    return [dict(r) for r in rows]


def add_yiyan(hitokoto: str, source: str = "", enabled: bool = True) -> int:
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO yiyan (hitokoto, source, enabled) VALUES (?, ?, ?)",
        (hitokoto, source, 1 if enabled else 0),
    )
    conn.commit()
    return cur.lastrowid


def update_yiyan(yiyan_id: int, **kwargs: Any) -> bool:
    conn = get_conn()
    allowed = {"hitokoto", "source", "enabled"}
    sets = []
    vals = []
    for k, v in kwargs.items():
        if k not in allowed:
            continue
        sets.append(f"{k} = ?")
        vals.append(v)
    if not sets:
        return False
    vals.append(yiyan_id)
    conn.execute(f"UPDATE yiyan SET {', '.join(sets)} WHERE id = ?", vals)
    conn.commit()
    return True


def delete_yiyan(yiyan_id: int) -> None:
    conn = get_conn()
    conn.execute("DELETE FROM yiyan WHERE id = ?", (yiyan_id,))
    conn.commit()


def count_yiyan() -> int:
    conn = get_conn()
    return conn.execute("SELECT COUNT(*) FROM yiyan WHERE enabled = 1").fetchone()[0]


def import_yiyan_batch(entries: list[dict]) -> int:
    """批量导入一言，返回导入数量"""
    conn = get_conn()
    count = 0
    for e in entries:
        conn.execute(
            "INSERT OR IGNORE INTO yiyan (hitokoto, source, enabled) VALUES (?, ?, ?)",
            (e.get("hitokoto", ""), e.get("from", e.get("source", "")), 1),
        )
        count += 1
    conn.commit()
    return count


# ==================== SOCKS5 代理管理 ====================

def add_proxy(data: dict) -> int:
    conn = get_conn()
    cur = conn.execute(
        """INSERT INTO proxies (label, ip, port, username, password, url, geo_country, geo_region, geo_city, geo_country_code, geo_ip, enabled, remark)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            data.get("label", ""),
            data.get("ip", ""),
            data.get("port", 0),
            data.get("username", ""),
            data.get("password", ""),
            data.get("url", ""),
            data.get("geo_country", ""),
            data.get("geo_region", ""),
            data.get("geo_city", ""),
            data.get("geo_country_code", ""),
            data.get("geo_ip", ""),
            1 if data.get("enabled", True) else 0,
            data.get("remark", ""),
        ),
    )
    conn.commit()
    return cur.lastrowid


def update_proxy(proxy_id: int, **kwargs: Any) -> bool:
    conn = get_conn()
    allowed = {"label", "ip", "port", "username", "password", "url", "geo_country", "geo_region", "geo_city", "geo_country_code", "geo_ip", "enabled", "remark", "last_test", "last_latency_ms", "last_test_at", "last_test_message"}
    sets = []
    vals = []
    for k, v in kwargs.items():
        if k not in allowed:
            continue
        sets.append(f"{k} = ?")
        vals.append(v)
    if not sets:
        return False
    sets.append("updated_at = datetime('now', 'localtime')")
    vals.append(proxy_id)
    conn.execute(f"UPDATE proxies SET {', '.join(sets)} WHERE id = ?", vals)
    conn.commit()
    return True


def delete_proxy(proxy_id: int) -> bool:
    conn = get_conn()
    cur = conn.execute("DELETE FROM proxies WHERE id = ?", (proxy_id,))
    conn.commit()
    return cur.rowcount > 0


def get_proxies(include_disabled: bool = False) -> list[dict]:
    conn = get_conn()
    if include_disabled:
        rows = conn.execute("SELECT * FROM proxies ORDER BY id").fetchall()
    else:
        rows = conn.execute("SELECT * FROM proxies WHERE enabled = 1 ORDER BY id").fetchall()
    return [dict(r) for r in rows]


def get_proxy(proxy_id: int) -> dict | None:
    conn = get_conn()
    row = conn.execute("SELECT * FROM proxies WHERE id = ?", (proxy_id,)).fetchone()
    return dict(row) if row else None


def find_proxy_by_url(url: str) -> dict | None:
    """通过完整 url 查找代理节点（用于前端反查 id）。"""
    if not url:
        return None
    conn = get_conn()
    row = conn.execute("SELECT * FROM proxies WHERE url = ? LIMIT 1", (url,)).fetchone()
    if row:
        return dict(row)
    return None


def build_proxy_url(data: dict) -> str:
    """根据字段构建 socks5:// 链接"""
    ip = data.get("ip", "")
    port = data.get("port", 0)
    user = data.get("username", "")
    pwd = data.get("password", "")
    if not ip or not port:
        return data.get("url", "")
    if user:
        return f"socks5://{user}:{pwd}@{ip}:{port}"
    return f"socks5://{ip}:{port}"


# ==================== 代理脱敏 ====================

def mask_proxy_url(url: str) -> str:
    """脱敏代理 URL：socks5://user:pass@host:port → socks5://***@host:port"""
    if not url or "@" not in url:
        return url
    try:
        protocol, rest = url.split("://", 1)
        auth, host_part = rest.rsplit("@", 1)
        return f"{protocol}://***@{host_part}"
    except Exception:
        return url
