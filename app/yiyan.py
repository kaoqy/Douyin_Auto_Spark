# 抖音续火花管理面板 - 一言（hitokoto.cn）
from __future__ import annotations

import json
import logging
import urllib.request

log = logging.getLogger("das.yiyan")


def fetch_yiyan_from_api() -> dict | None:
    """从 hitokoto.cn 获取随机一言"""
    try:
        req = urllib.request.Request(
            "https://v1.hitokoto.cn/?c=a&c=b&c=c&c=d&c=e&c=f&c=g&c=h&c=i&c=j&c=k&c=l&encode=json",
            headers={"User-Agent": "Mozilla/5.0 (Douyin-Auto-Spark)"},
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        return {
            "hitokoto": data.get("hitokoto", ""),
            "source": data.get("from", ""),
            "from_who": data.get("from_who", ""),
        }
    except Exception as e:
        log.error("请求一言 API 失败: %s", e)
        return None


def render_message(template: str | None, account_name: str, friend_name: str,
                   yiyan_item: dict | None = None, include_source: bool = True) -> str:
    """渲染消息模板"""
    from datetime import datetime
    now = datetime.now()

    if yiyan_item is None:
        yiyan_item = fetch_yiyan_from_api() or {}
    if not yiyan_item:
        yiyan_item = {}

    yiyan_text = yiyan_item.get("hitokoto", "")
    yiyan_from = yiyan_item.get("from_who") or yiyan_item.get("source", "")

    if template:
        result = template
        result = result.replace("{{account}}", account_name)
        result = result.replace("{{friend}}", friend_name)
        result = result.replace("{{yiyan}}", yiyan_text)
        result = result.replace("{{from}}", yiyan_from)
        result = result.replace("{{date}}", now.strftime("%Y-%m-%d"))
        result = result.replace("{{time}}", now.strftime("%H:%M"))
        result = result.replace("{{weekday}}", now.strftime("%A"))
        result = result.replace("\\n", "\n")
        return result
    else:
        if include_source and yiyan_from:
            return f"{yiyan_text}\n——「{yiyan_from}」"
        return yiyan_text
