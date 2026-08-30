#!/bin/bash
# 抖音自动续火花管理面板 - Docker 部署脚本
set -e

cd "$(dirname "$0")"

# 配置
IMAGE_NAME="${DAS_IMAGE:-douyin-auto-spark:latest}"
PORT="${DAS_PORT:-8000}"
ADMIN_USER="${DAS_ADMIN_USER:-admin}"
ADMIN_PASSWORD="${DAS_ADMIN_PASSWORD:-}"

echo "🔥 抖音续火花管理面板 - 部署脚本"
echo "=============================="
echo ""

# 检查 Docker
if ! command -v docker &> /dev/null; then
    echo "❌ Docker 未安装"
    exit 1
fi

# 检查 docker compose
if ! docker compose version &> /dev/null; then
    echo "❌ Docker Compose 未安装"
    exit 1
fi

# 创建数据目录
mkdir -p data

# 构建镜像
echo "📦 构建 Docker 镜像..."
docker compose build

# 启动
echo "🚀 启动服务..."
docker compose up -d

echo ""
echo "✅ 部署完成！"
echo "   访问地址: http://localhost:${PORT}"
echo "   管理员: ${ADMIN_USER}"
if [ -n "${ADMIN_PASSWORD}" ]; then
    echo "   密码: ${ADMIN_PASSWORD}"
else
    echo "   密码: admin123（默认，建议修改）"
fi
echo ""
echo "查看日志: docker compose logs -f"
echo "停止服务: docker compose down"
