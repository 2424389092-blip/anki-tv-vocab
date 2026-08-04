#!/usr/bin/env bash
# git-sync.sh — anki-tv-vocab 一键同步到 GitHub
# 用法：
#   首次（带 remote）：  REMOTE_URL=https://github.com/用户名/仓库名.git ./git-sync.sh
#   之后：               ./git-sync.sh
# 说明：自动 git init（若需要）、add、commit（消息带日期）；若已配 remote 则一并 push。
#       没配 remote 也能先本地提交，只是不推送。
set -euo pipefail

# 进入脚本所在目录（skill 根目录），保证从任意位置调用都操作本仓库
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# 1. 初始化仓库（如果没有 .git）
if [ ! -d .git ]; then
  echo "▶ 未检测到 git 仓库，执行 git init ..."
  git init -q
  git branch -M main 2>/dev/null || true
fi

# 2. 暂存全部改动（受 .gitignore 约束，不会提交 *.apkg / *.mp3 等）
git add -A

# 3. 无改动则跳过提交
if git diff --cached --quiet; then
  echo "✓ 没有需要提交的改动。"
else
  MSG="chore: sync $(date +%Y-%m-%d)"
  git commit -m "$MSG"
  echo "▶ 已提交：$MSG"
fi

# 4. 推送（需要已配置 remote origin）
if ! git remote get-url origin >/dev/null 2>&1; then
  if [ -n "${REMOTE_URL:-}" ]; then
    git remote add origin "$REMOTE_URL"
    echo "▶ 已添加 remote origin -> $REMOTE_URL"
  else
    echo "✓ 本地已提交，但还没配置 remote，未推送到 GitHub。"
    echo "  配置方式（二选一）："
    echo "    a) 手动：  git remote add origin <你的GitHub仓库URL>"
    echo "    b) 重跑：  REMOTE_URL=<你的GitHub仓库URL> ./git-sync.sh"
    exit 0
  fi
fi

BRANCH="$(git rev-parse --abbrev-ref HEAD)"
git push -u origin "$BRANCH"
echo "✓ 已推送到 origin/$BRANCH"
