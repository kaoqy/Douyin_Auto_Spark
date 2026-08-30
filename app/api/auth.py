# 抖音自动续火花管理面板 - 认证 API
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request, Response

from .. import auth, database

log = logging.getLogger("das.api.auth")
router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login")
def login(body: dict, response: Response):
    username = body.get("username", "")
    password = body.get("password", "")
    token = auth.login(username, password)
    if not token:
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    # 设置 Cookie
    response.set_cookie(
        key=auth.COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        max_age=auth.SESSION_DAYS * 86400,
    )
    return {"message": "登录成功", "token": token}


@router.post("/logout")
def logout(request: Request, response: Response):
    token = request.cookies.get(auth.COOKIE_NAME, "")
    auth.logout(token)
    response.delete_cookie(auth.COOKIE_NAME)
    return {"message": "已退出登录"}


@router.get("/me")
def get_me(request: Request):
    token = request.cookies.get(auth.COOKIE_NAME, "")
    user = auth.get_current_user(token)
    if not user:
        raise HTTPException(status_code=401, detail="未登录或会话已过期")
    return {"user": {"id": user["user_id"], "username": user["username"]}}


@router.post("/init")
def init_admin(body: dict, response: Response):
    """首次部署创建管理员"""
    if database.count_users() > 0:
        raise HTTPException(status_code=400, detail="系统已初始化")

    username = (body.get("username") or "admin").strip()
    password = body.get("password", "")
    if len(password) < 6:
        raise HTTPException(status_code=400, detail="密码至少 6 位")

    database.create_user(username, auth.hash_password(password))
    token = auth.login(username, password)
    response.set_cookie(
        key=auth.COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        max_age=auth.SESSION_DAYS * 86400,
    )
    return {"message": "管理员创建成功", "username": username}


@router.get("/needs-init")
def needs_init():
    return {"needs_init": database.count_users() == 0}


@router.post("/change-password")
def change_password(body: dict, request: Request):
    token = request.cookies.get(auth.COOKIE_NAME, "")
    user = auth.get_current_user(token)
    if not user:
        raise HTTPException(status_code=401, detail="未登录")

    old_password = body.get("old_password", "")
    new_password = body.get("new_password", "")

    if not auth.verify_password(old_password, database.get_user_by_id(user["user_id"])["password_hash"]):
        raise HTTPException(status_code=400, detail="原密码错误")
    if len(new_password) < 6:
        raise HTTPException(status_code=400, detail="新密码至少 6 位")

    auth.change_password(user["user_id"], new_password)
    # 使旧会话失效
    auth.logout(token)
    return {"message": "密码修改成功，请重新登录"}
