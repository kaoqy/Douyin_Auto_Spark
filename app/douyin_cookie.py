# 抖音 Cookie 类型定义
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

SameSite = Literal["Strict", "Lax", "None", "no_restriction"]


@dataclass
class DouyinCookieItem:
    domain: str
    expirationDate: float | None = None
    hostOnly: bool = False
    httpOnly: bool = False
    name: str = ""
    path: str = "/"
    sameSite: str = "no_restriction"
    secure: bool = True
    session: bool = False
    storeId: str | None = None
    value: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "DouyinCookieItem":
        return cls(
            domain=d.get("domain", ""),
            expirationDate=d.get("expirationDate"),
            hostOnly=d.get("hostOnly", False),
            httpOnly=d.get("httpOnly", False),
            name=d.get("name", ""),
            path=d.get("path", "/"),
            sameSite=d.get("sameSite", "no_restriction"),
            secure=d.get("secure", True),
            session=d.get("session", False),
            storeId=d.get("storeId"),
            value=d.get("value", ""),
        )

    def to_playwright_cookie(self) -> dict:
        """转换为 Playwright addCookies 格式"""
        c = {
            "name": self.name,
            "value": self.value,
            "domain": self.domain,
            "path": self.path,
            "secure": self.secure,
            "httpOnly": self.httpOnly,
        }
        if self.expirationDate is not None:
            c["expires"] = self.expirationDate
        if self.sameSite:
            c["sameSite"] = self.sameSite if self.sameSite in ("Strict", "Lax", "None") else "None"
        return c


def parse_cookie_json(raw: str | list) -> list[DouyinCookieItem]:
    """解析 Cookie JSON 字符串或列表"""
    import json
    if isinstance(raw, str):
        data = json.loads(raw)
    else:
        data = raw
    if not isinstance(data, list):
        raise ValueError("Cookie 必须是 JSON 数组")
    return [DouyinCookieItem.from_dict(d) for d in data]


def cookies_to_json(cookies: list[DouyinCookieItem]) -> str:
    """序列化 Cookie 为 JSON 字符串"""
    import json
    return json.dumps([{
        "domain": c.domain,
        "expirationDate": c.expirationDate,
        "hostOnly": c.hostOnly,
        "httpOnly": c.httpOnly,
        "name": c.name,
        "path": c.path,
        "sameSite": c.sameSite,
        "secure": c.secure,
        "session": c.session,
        "storeId": c.storeId,
        "value": c.value,
    } for c in cookies], ensure_ascii=False)
