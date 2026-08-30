# 抖音自动续火花管理面板 - 一言管理
from __future__ import annotations

import json
import logging
import random
from pathlib import Path

from . import database

log = logging.getLogger("das.yiyan")

DEFAULT_YIYAN_FILE = Path(__file__).resolve().parent / "assets" / "yiyan.json"


def load_default_yiyan() -> list[dict]:
    """从默认文件加载一言库"""
    if not DEFAULT_YIYAN_FILE.exists():
        log.warning("默认一言文件不存在：%s", DEFAULT_YIYAN_FILE)
        return []
    try:
        with open(DEFAULT_YIYAN_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception as e:
        log.error("加载一言文件失败：%s", e)
        return []


def init_yiyan_if_empty() -> None:
    """如果一言库为空，导入默认数据"""
    if database.count_yiyan() == 0:
        entries = load_default_yiyan()
        if entries:
            count = database.import_yiyan_batch(entries)
            log.info("已导入 %d 条默认一言", count)


def pick_random_yiyan() -> dict | None:
    """随机获取一条启用的一言"""
    items = database.get_yiyan_list(enabled_only=True)
    if not items:
        return None
    return random.choice(items)


def render_message(template: str | None, account_name: str, friend_name: str,
                   yiyan_item: dict | None = None, include_source: bool = True) -> str:
    """渲染消息模板"""
    from datetime import datetime
    now = datetime.now()

    if yiyan_item is None:
        yiyan_item = pick_random_yiyan()

    yiyan_text = yiyan_item.get("hitokoto", "") if yiyan_item else ""
    # 数据库字段是 source，模板占位符是 from
    yiyan_from = yiyan_item.get("source", "") if yiyan_item else ""

    if template:
        # 使用自定义模板
        result = template
        result = result.replace("{{account}}", account_name)
        result = result.replace("{{friend}}", friend_name)
        result = result.replace("{{yiyan}}", yiyan_text)
        result = result.replace("{{from}}", yiyan_from)
        result = result.replace("{{date}}", now.strftime("%Y-%m-%d"))
        result = result.replace("{{time}}", now.strftime("%H:%M"))
        result = result.replace("{{weekday}}", now.strftime("%A"))
        # 支持 \n 换行
        result = result.replace("\\n", "\n")
        return result
    else:
        # 默认格式
        if include_source and yiyan_from:
            return f"{yiyan_text}\n——「{yiyan_from}」"
        return yiyan_text
