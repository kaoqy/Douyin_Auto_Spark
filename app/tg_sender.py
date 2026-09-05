# 抖音自动续火花管理面板 - Telegram 推送
from __future__ import annotations

import json
import logging
import urllib.request

from . import database

log = logging.getLogger("das.tg")


def _send_tg_message(bot_token: str, chat_id: str, text: str, silent: bool = False) -> bool:
    """发送 TG 消息"""
    if not bot_token or not chat_id:
        return False

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    data = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_notification": silent,
    }

    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(data).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            if result.get("ok"):
                log.info("TG 消息发送成功")
                return True
            else:
                log.error("TG API 返回错误: %s", result)
                return False
    except Exception as e:
        log.error("TG 消息发送失败: %s", e)
        return False


def push_summary(summary: dict) -> bool:
    """推送续火汇总到 TG"""
    enabled = database.get_setting("tg_enabled", "0") == "1"
    if not enabled:
        return False

    bot_token = database.get_setting("tg_bot_token", "")
    chat_id = database.get_setting("tg_user_id", "")
    only_on_change = database.get_setting("tg_only_on_change", "0") == "1"
    silent = database.get_setting("tg_silent", "0") == "1"

    if not bot_token or not chat_id:
        log.warning("TG 未配置，跳过推送")
        return False

    # 仅异常时推送：如果任务成功且没有失败，则不推
    if only_on_change:
        status = summary.get("status", "")
        fail = summary.get("fail", 0)
        if status == "success" and fail == 0:
            log.info("仅异常时推送：任务成功，跳过")
            return False

    # 构建消息
    status = summary.get("status", "unknown")
    accounts = summary.get("accounts", 0)
    total = summary.get("total", 0)
    success = summary.get("success", 0)
    fail = summary.get("fail", 0)
    time_str = summary.get("time", "")
    trigger_type = summary.get("trigger_type", "manual")

    status_emoji = {"success": "✅", "partial": "⚠️", "failed": "❌"}.get(status, "❓")
    trigger_label = {"manual": "手动", "schedule": "定时", "cli": "CLI"}.get(trigger_type, trigger_type)

    lines = [
        f"<b>{status_emoji} 抖音续火 {trigger_label}</b>",
        f"",
        f"📊 账号：{accounts} 个",
        f"💬 好友：{total} 个",
        f"✅ 成功：{success}",
        f"❌ 失败：{fail}",
        f"⏰ 时间：{time_str}",
    ]

    # 如果有失败，列出失败详情
    if fail > 0:
        lines.append("")
        lines.append("<b>失败详情：</b>")
        for acc in summary.get("detail", []):
            if acc.get("fail", 0) > 0:
                lines.append(f"• {acc['name']}：{acc.get('message', '')}")

    text = "\n".join(lines)
    return _send_tg_message(bot_token, chat_id, text, silent)


def push_quote(yiyan_text: str, source: str = "", from_who: str = "") -> bool:
    """推送每日一言到 TG"""
    enabled = database.get_setting("tg_enabled", "0") == "1"
    quote_enabled = database.get_setting("tg_quote_enabled", "1") == "1"
    if not enabled or not quote_enabled:
        return False

    bot_token = database.get_setting("tg_bot_token", "")
    chat_id = database.get_setting("tg_user_id", "")
    silent = database.get_setting("tg_silent", "0") == "1"

    if not bot_token or not chat_id:
        return False

    text = f"📝 <b>每日一言</b>\n\n{yiyan_text}"
    if from_who:
        text += f"\n\n—— {from_who}"
    elif source:
        text += f"\n\n——「{source}」"

    return _send_tg_message(bot_token, chat_id, text, silent)


def test_push() -> dict:
    """发送测试消息"""
    enabled = database.get_setting("tg_enabled", "0") == "1"
    if not enabled:
        return {"ok": False, "message": "TG 推送未启用"}

    bot_token = database.get_setting("tg_bot_token", "")
    chat_id = database.get_setting("tg_user_id", "")

    if not bot_token:
        return {"ok": False, "message": "Bot Token 未配置"}
    if not chat_id:
        return {"ok": False, "message": "Chat/User ID 未配置"}

    text = "🧪 <b>测试消息</b>\n\n抖音续火花管理面板 TG 推送配置成功！"
    ok = _send_tg_message(bot_token, chat_id, text, silent=False)

    if ok:
        return {"ok": True, "message": "测试消息已发送"}
    else:
        return {"ok": False, "message": "发送失败，请检查 Token 和 Chat ID"}
