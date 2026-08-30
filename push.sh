#!/bin/bash
# 抖音自动续火花管理面板 - Docker 推送脚本
set -e

cd "$(dirname "$0")"

VERSION="${1:-latest}"

echo "📤 推送 Docker 镜像..."
docker tag "douyin-auto-spark:${VERSION}" "kaoqy666/douyin-auto-spark:${VERSION}"
docker push "kaoqy666/douyin-auto-spark:${VERSION}"

if [ "$VERSION" != "latest" ]; then
    docker tag "douyin-auto-spark:${VERSION}" "kaoqy666/douyin-auto-spark:latest"
    docker push "kaoqy666/douyin-auto-spark:latest"
fi

echo "✅ 推送完成"
