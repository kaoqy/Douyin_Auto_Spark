# 抖音自动续火花管理面板 - FastAPI 入口
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from . import auth, database, scheduler, yiyan
from .api.accounts import router as accounts_router
from .api.auth import router as auth_router
from .api.logs import router as logs_router
from .api.settings import router as settings_router
from .api.targets import router as targets_router
from .api.tasks import router as tasks_router
from .api.yiyan import router as yiyan_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("das.main")

STATIC_DIR = Path(__file__).resolve().parent / "static"
DATA_DIR = database.DB_PATH.parent

PUBLIC_API_PREFIXES = (
    "/api/auth/login",
    "/api/auth/me",
    "/api/health",
    "/api/auth/init",
    "/api/auth/needs-init",
)
PUBLIC_STATIC = ("/login.html", "/style.css", "/favicon.ico")


@asynccontextmanager
async def lifespan(app: FastAPI):
    database.init_db()
    yiyan.init_yiyan_if_empty()
    scheduler.start_scheduler()
    log.info("抖音续火花管理面板已就绪（数据库：%s）", database.DB_PATH)
    yield
    scheduler.stop_scheduler()


app = FastAPI(
    title="抖音自动续火花管理面板",
    description="抖音聊天续火 · 多账号 · 定时任务 · SOCKS 代理",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(accounts_router)
app.include_router(targets_router)
app.include_router(tasks_router)
app.include_router(logs_router)
app.include_router(settings_router)
app.include_router(yiyan_router)
app.include_router(auth_router)


@app.get("/api/health")
def health():
    return {
        "ok": True,
        "version": app.version,
        "time": database.get_setting("last_spark_time", "never"),
        "auth_enabled": auth.auth_enabled(),
    }


@app.middleware("http")
async def auth_guard(request: Request, call_next):
    """认证守卫"""
    path = request.url.path

    # 首次部署：无用户则强制到 init 页
    needs_init = database.count_users() == 0
    if needs_init:
        if path in ("/init.html", "/style.css", "/api/auth/init", "/api/auth/needs-init", "/api/health", "/favicon.ico"):
            return await call_next(request)
        if path.startswith("/api/"):
            from fastapi.responses import JSONResponse
            return JSONResponse(status_code=403, content={"detail": "系统未初始化"})
        return RedirectResponse("/init.html", status_code=302)

    # 公开路径放行
    if path.startswith(PUBLIC_API_PREFIXES):
        return await call_next(request)
    if path in PUBLIC_STATIC or path == "/login.html":
        return await call_next(request)

    # 未启用登录则放行
    if not auth.auth_enabled():
        return await call_next(request)

    token = request.cookies.get(auth.COOKIE_NAME, "")
    user = auth.get_current_user(token) if token else None

    if request.url.path.startswith("/api/"):
        if not user:
            from fastapi.responses import JSONResponse
            return JSONResponse(status_code=401, content={"detail": "未登录或会话已过期"})
        return await call_next(request)

    # 页面：未登录重定向
    if not user:
        return RedirectResponse("/login.html", status_code=302)
    return await call_next(request)


# 数据目录挂载
DATA_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/data", StaticFiles(directory=str(DATA_DIR)), name="data")

# 静态资源
if STATIC_DIR.exists():
    app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")


@app.middleware("http")
async def _no_cache_static(request: Request, call_next):
    """静态资源不缓存"""
    resp = await call_next(request)
    req_path = request.url.path
    if req_path.endswith((".html", ".js", ".css")) or req_path in ("/", "/index.html", "/login.html"):
        resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return resp


def cli_spark():
    """命令行直接跑一次续火"""
    database.init_db()
    summary = scheduler.run_spark_task("cli")
    print("\n=== 续火汇总 ===")
    print(f"状态: {summary['status']}")
    print(f"账号: {summary.get('accounts', 0)}")
    print(f"好友: 总数 {summary.get('total', 0)} | 成功 {summary.get('success', 0)} | 失败 {summary.get('fail', 0)}")
    for acc in summary.get("detail", []):
        print(f"  - {acc['name']} [{acc['status']}] ({acc.get('channel')}): {acc.get('message', '')}")
    return summary
