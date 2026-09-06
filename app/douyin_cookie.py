# 抖音 Cookie 类型定义
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

SameSite = Literal["Strict", "Lax", "None", "no_restriction"]

# Playwright 接收 cookie 时，domain 不能为空（与 url 二选一）。
# 抖音聊天页是 https://www.douyin.com，所以这里默认补全。
DEFAULT_COOKIE_DOMAIN = ".douyin.com"
DEFAULT_COOKIE_PATH = "/"

# Playwright 识别的 sameSite 枚举
_VALID_SAME_SITE = {"Strict", "Lax", "None", "no_restriction"}


@dataclass
class DouyinCookieItem:
    domain: str = ""
    expirationDate: float | None = None
    hostOnly: bool = False
    httpOnly: bool = False
    name: str = ""
    path: str = ""
    sameSite: str = "Lax"
    secure: bool = True
    session: bool = False
    storeId: str | None = None
    url: str = ""
    value: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "DouyinCookieItem":
        # 同名字段不同拼写
        domain = d.get("domain") or d.get("Domain") or ""
        path = d.get("path") or d.get("Path") or ""
        same_site = d.get("sameSite") or d.get("sameSite") or d.get("SameSite") or ""
        # 如果用户传了 url，也带上
        url = d.get("url") or d.get("Url") or ""
        name = d.get("name") or d.get("Name") or ""
        value = d.get("value") or d.get("Value") or ""
        item = cls(
            domain=domain,
            path=path,
            url=url,
            name=name,
            value=value,
            expirationDate=d.get("expirationDate") or d.get("expiration_date"),
            hostOnly=bool(d.get("hostOnly") or d.get("host_only")),
            httpOnly=bool(d.get("httpOnly") or d.get("http_only")),
            sameSite=same_site,
            secure=bool(d.get("secure")),
            session=bool(d.get("session")),
            storeId=d.get("storeId") or d.get("store_id"),
        )
        item.normalize()
        return item

    def normalize(self) -> None:
        """补全缺失的 domain/path/sameSite。"""
        if not self.domain and not self.url:
            self.domain = DEFAULT_COOKIE_DOMAIN
        if not self.path and not self.url:
            self.path = DEFAULT_COOKIE_PATH
        if not self.sameSite:
            self.sameSite = "Lax"
        if self.sameSite not in _VALID_SAME_SITE:
            # 降级到 None
            self.sameSite = "None"

    def to_playwright_cookie(self) -> dict:
        """转换为 Playwright addCookies 格式。
        至少需要传 url 或 domain/path。"""
        self.normalize()
        c: dict = {
            "name": self.name,
            "value": self.value,
        }
        if self.url:
            c["url"] = self.url
        else:
            c["domain"] = self.domain
            c["path"] = self.path or DEFAULT_COOKIE_PATH
        c["secure"] = self.secure
        c["httpOnly"] = self.httpOnly
        if self.expirationDate is not None:
            try:
                c["expires"] = float(self.expirationDate)
            except (TypeError, ValueError):
                c["expires"] = -1
        else:
            c["expires"] = -1
        c["sameSite"] = self.sameSite
        return c


def parse_cookie_json(raw: str | list) -> list[DouyinCookieItem]:
    """解析 Cookie JSON 字符串或列表。
    对于只粘贴了 name/value 的简化 cookie，会自动补全 domain=.douyin.com。
    """
    import json
    if isinstance(raw, str):
        data = json.loads(raw)
    else:
        data = raw
    if not isinstance(data, list):
        raise ValueError("Cookie 必须是 JSON 数组")
    items: list[DouyinCookieItem] = []
    for d in data:
        if not isinstance(d, dict):
            continue
        item = DouyinCookieItem.from_dict(d)
        item.normalize()
        items.append(item)
    return items


def cookies_to_json(cookies: list[DouyinCookieItem]) -> str:
    """序列化 Cookie 为 JSON 字符串"""
    import json
    return json.dumps([{
        "domain": c.domain,
        "path": c.path,
        "url": c.url,
        "name": c.name,
        "value": c.value,
        "expirationDate": c.expirationDate,
        "httpOnly": c.httpOnly,
        "secure": c.secure,
        "sameSite": c.sameSite,
        "session": c.session,
    } for c in cookies], ensure_ascii=False)
