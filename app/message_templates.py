"""抖音续火消息模板的校验与渲染。

占位符行为与上游 bling-yshs/douyin-auto-spark 保持一致。
"""
from __future__ import annotations

import re
from datetime import datetime
from zoneinfo import ZoneInfo


SUPPORTED_PLACEHOLDERS = (
    "account",
    "friend",
    "yiyan",
    "from",
    "date",
    "time",
    "weekday",
)
PLACEHOLDER_PATTERN = re.compile(r"\{\{\s*([a-zA-Z]+)\s*\}\}")
SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


def normalize_template(template: str, source_name: str = "message_template") -> str:
    """校验模板占位符，并将字面量 ``\\n`` 转换为换行。"""
    if not isinstance(template, str):
        raise ValueError(f"{source_name} 必须是字符串")

    unknown = sorted(
        {
            match.group(1)
            for match in PLACEHOLDER_PATTERN.finditer(template)
            if match.group(1) not in SUPPORTED_PLACEHOLDERS
        }
    )
    if unknown:
        invalid = "、".join(f"{{{{{name}}}}}" for name in unknown)
        supported = " ".join(f"{{{{{name}}}}}" for name in SUPPORTED_PLACEHOLDERS)
        raise ValueError(
            f"{source_name} 中存在未识别的占位符：{invalid}。"
            f"支持的占位符：{supported}"
        )

    return template.replace("\\n", "\n")


def needs_yiyan(template: str | None) -> bool:
    """模板为空或使用一言相关占位符时，需要获取一言。"""
    if template is None:
        return True
    return any(
        match.group(1) in {"yiyan", "from"}
        for match in PLACEHOLDER_PATTERN.finditer(template)
    )


def render_template(
    template: str,
    account: str,
    friend: str,
    yiyan: dict | None = None,
    now: datetime | None = None,
) -> str:
    """按上海时区渲染已校验的消息模板。"""
    normalized = normalize_template(template)
    current = now or datetime.now(SHANGHAI_TZ)
    if current.tzinfo is None:
        current = current.replace(tzinfo=SHANGHAI_TZ)
    else:
        current = current.astimezone(SHANGHAI_TZ)

    item = yiyan or {}
    source = item.get("from_who") or item.get("source") or item.get("from") or ""
    values = {
        "account": account,
        "friend": friend,
        "yiyan": item.get("hitokoto", ""),
        "from": source,
        "date": current.strftime("%Y-%m-%d"),
        "time": current.strftime("%H:%M"),
        "weekday": current.strftime("%A"),
    }
    return PLACEHOLDER_PATTERN.sub(lambda match: values[match.group(1)], normalized)
