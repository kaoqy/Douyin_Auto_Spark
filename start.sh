#!/bin/bash
# 抖音续火花管理面板 - 启动脚本
set -e

cd "$(dirname "$0")"

# 默认配置
export DAS_DATA_DIR="${DAS_DATA_DIR:-./data}"
export APP_HOST="${APP_HOST:-0.0.0.0}"
export APP_PORT="${APP_PORT:-8000}"

# 管理员配置（首次部署）
export DAS_ADMIN_USER="${DAS_ADMIN_USER:-admin}"
export DAS_ADMIN_PASSWORD="${DAS_ADMIN_PASSWORD:-}"

echo "🔥 抖音续火花管理面板"
echo "   数据目录: $DAS_DATA_DIR"
echo "   监听地址: $APP_HOST:$APP_PORT"
echo ""

exec python run.py --host "$APP_HOST" --port "$APP_PORT" --data-dir "$DAS_DATA_DIR"
