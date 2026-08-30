# 抖音续火花管理面板 - 一键启动
from __future__ import annotations

import argparse
import logging
import os
import sys

# 确保 app 目录在 Python 路径中
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("das.run")


def main():
    parser = argparse.ArgumentParser(description="抖音自动续火花管理面板")
    parser.add_argument("--host", default="0.0.0.0", help="监听地址")
    parser.add_argument("--port", type=int, default=8000, help="监听端口")
    parser.add_argument("--data-dir", default=os.environ.get("DAS_DATA_DIR", "./data"),
                        help="数据目录（SQLite 数据库位置）")
    parser.add_argument("--spark", action="store_true", help="执行一次续火任务后退出（不启动 Web）")
    args = parser.parse_args()

    # 设置数据目录环境变量
    os.environ["DAS_DATA_DIR"] = os.path.abspath(args.data_dir)

    if args.spark:
        # 命令行模式：执行一次续火
        from app.main import cli_spark
        cli_spark()
    else:
        # Web 模式
        import uvicorn
        from app.main import app

        log.info("启动 Web 面板：http://%s:%d", args.host, args.port)
        uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
