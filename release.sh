#!/bin/bash
# 抖音自动续火花管理面板 - 发布脚本
# 用法: bash release.sh v1.0 "发布说明"
set -e

cd "$(dirname "$0")"

VERSION="${1:?用法: bash release.sh v1.0 \"发布说明\"}"
MESSAGE="${2:-Release $VERSION}"

echo "🔥 抖音续火花管理面板 - 发布 $VERSION"
echo "======================================"
echo ""

# 1. 运行测试
echo "📋 运行测试..."
.venv/bin/python -m pytest tests/ -q || { echo "❌ 测试失败"; exit 1; }

# 2. 更新版本号（在 main.py 中）
echo "📝 更新版本号..."
sed -i "s/version=\"[^\"]*\"/version=\"$VERSION\"/" app/main.py

# 3. Git commit
echo "📦 Git commit..."
git add -A
git commit -m "release: $VERSION - $MESSAGE" || true

# 4. 打 tag
echo "🏷️  打 tag..."
git tag -a "$VERSION" -m "$MESSAGE" || true

# 5. 推送
echo "🚀 推送..."
git push origin main --tags || true

# 6. 构建 Docker 镜像
echo "🐳 构建 Docker 镜像..."
docker compose build

# 7. 推送 Docker 镜像（可选）
if [ "${PUSH_DOCKER:-0}" = "1" ]; then
    echo "📤 推送 Docker 镜像..."
    docker push "kaoqy666/douyin-auto-spark:${VERSION}"
    docker push "kaoqy666/douyin-auto-spark:latest"
fi

echo ""
echo "✅ 发布完成！"
echo "   版本: $VERSION"
echo "   说明: $MESSAGE"
