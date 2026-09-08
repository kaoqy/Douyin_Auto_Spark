#!/usr/bin/env bash
# Douyin Auto Spark — 带凭据推送
# PAT 从 /home/node/.openclaw/workspace/Weibo_Auto_Checkin_v1.1.2/.env 读取
# 用完即清：临时 URL 只在 push 期间存在，trap 退出时恢复

set -euo pipefail

ENV_FILE="/home/node/.openclaw/workspace/Weibo_Auto_Checkin_v1.1.2/.env"
REMOTE_URL_BASE="https://github.com/kaoqy/Douyin_Auto_Spark.git"

# 1. 读取 PAT
if [ ! -f "$ENV_FILE" ]; then
  echo "❌ $ENV_FILE 不存在"
  exit 1
fi
set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

if [ -z "${GITHUB_TOKEN:-}" ]; then
  echo "❌ GITHUB_TOKEN 未在 $ENV_FILE 中"
  exit 1
fi

# 2. 临时改 remote URL
ORIG_URL=$(git remote get-url origin)
git remote set-url origin "https://kaoqy:${GITHUB_TOKEN}@github.com/kaoqy/Douyin_Auto_Spark.git"

# 3. 推送（带参数透传），退出时无论成败都恢复
cleanup() {
  git remote set-url origin "$REMOTE_URL_BASE" >/dev/null 2>&1 || true
}
trap cleanup EXIT

git push "$@"
