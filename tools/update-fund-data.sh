#!/bin/bash
# 每日更新 DSP5 基金淨值/配息並推上 GitHub Pages。
# 由 launchd（見 tools/com.kevin.fund-data.plist）每日呼叫。
# 抓取成功且 fund-data.json 有變動時才 commit + push，避免空提交。
set -euo pipefail

REPO="/Users/yichengsmbp2017/Desktop/Keri-Workspace/Ai工作區/kevin-supply-hub"
LOG="$REPO/tools/update-fund-data.log"
cd "$REPO"

ts() { date "+%Y-%m-%d %H:%M:%S"; }

if ! /usr/bin/python3 tools/fetch-fund-data.py >>"$LOG" 2>&1; then
  echo "$(ts) 抓取失敗，略過本次更新" >>"$LOG"
  exit 1
fi

if git diff --quiet -- fund-data.json; then
  echo "$(ts) 淨值/配息無變動，不提交" >>"$LOG"
  exit 0
fi

NAV=$(/usr/bin/python3 -c "import json;print(json.load(open('fund-data.json'))['nav'])")
git add fund-data.json
git commit -m "chore: 更新 DSP5 淨值/配息（自動排程 NAV ${NAV}）" >>"$LOG" 2>&1
if git push origin main >>"$LOG" 2>&1; then
  echo "$(ts) 已更新並推送 NAV ${NAV}" >>"$LOG"
else
  echo "$(ts) commit 完成但 push 失敗（可能需重新登入 git 認證）" >>"$LOG"
  exit 1
fi
