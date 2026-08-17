#!/bin/bash
# 每日更新 DSP5 基金淨值/配息並推上 GitHub Pages。
# 由 launchd（見 tools/com.kevin.fund-data.plist）每日呼叫。
# 抓取成功且 fund-data.json 有變動時才 commit + push，避免空提交。
set -euo pipefail

REPO="/Users/yichengsmbp2017/Desktop/Keri-Workspace/Ai工作區/kevin-supply-hub"
LOG="$REPO/tools/update-fund-data.log"
MARKER="$REPO/tools/.last-run-date"
cd "$REPO"

ts() { date "+%Y-%m-%d %H:%M:%S"; }
TODAY="$(date +%Y-%m-%d)"

# 由「網路連上」事件觸發，一天可能被叫很多次 → 今日已成功執行過就跳過
if [ -f "$MARKER" ] && [ "$(cat "$MARKER")" = "$TODAY" ]; then
  exit 0
fi

if ! /usr/bin/python3 tools/fetch-fund-data.py >>"$LOG" 2>&1; then
  # 抓取失敗（可能網路還沒真的通）→ 不標記，下次網路事件再重試
  echo "$(ts) 抓取失敗，略過本次更新（待下次網路事件重試）" >>"$LOG"
  exit 1
fi

# 當日抓取成功 → 標記今日已執行，避免重複觸發
echo "$TODAY" >"$MARKER"

if git diff --quiet -- fund-data.json; then
  echo "$(ts) 淨值/配息無變動，不提交" >>"$LOG"
  exit 0
fi

SUMMARY=$(/usr/bin/python3 -c "import json;d=json.load(open('fund-data.json'));print('、'.join(f\"{x['name']} {x['nav']}\" for x in d['funds']))")
git add fund-data.json
git commit -m "chore: 更新基金淨值/配息（自動排程：${SUMMARY}）" >>"$LOG" 2>&1
if git push origin main >>"$LOG" 2>&1; then
  echo "$(ts) 已更新並推送：${SUMMARY}" >>"$LOG"
else
  echo "$(ts) commit 完成但 push 失敗（可能需重新登入 git 認證）" >>"$LOG"
  exit 1
fi
