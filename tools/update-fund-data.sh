#!/bin/bash
# 每日更新 DSP5 基金淨值/配息並推上 GitHub Pages。
# 由 launchd（見 tools/com.kevin.fund-data.plist）每日呼叫。
# 抓取成功且 fund-data.json 有變動時才 commit + push，避免空提交。
set -euo pipefail

# REPO 由腳本自身位置推導 → 同一份腳本可在 MacBook / Mac mini 兩台通用
REPO="$(cd "$(dirname "$0")/.." && pwd)"
LOG="$REPO/tools/update-fund-data.log"
MARKER="$REPO/tools/.last-run-date"
cd "$REPO"

ts() { date "+%Y-%m-%d %H:%M:%S"; }
TODAY="$(date +%Y-%m-%d)"

# launchd 每日多時段觸發（16/18/20 時）→ 今日已抓到「夠新」的值就跳過，否則同日稍後重試
if [ -f "$MARKER" ] && [ "$(cat "$MARKER")" = "$TODAY" ]; then
  exit 0
fi

# 先同步遠端，避免本機（尤其 Mac mini）落後於其他機器的 commit 導致 push 被拒
git pull --rebase --autostash origin main >>"$LOG" 2>&1 || echo "$(ts) git pull 失敗，仍繼續本次更新" >>"$LOG"

if ! /usr/bin/python3 tools/fetch-fund-data.py >>"$LOG" 2>&1; then
  # 抓取失敗（可能網路還沒真的通）→ 不標記，下個時段再重試
  echo "$(ts) 抓取失敗，略過本次更新（待下個時段重試）" >>"$LOG"
  exit 1
fi

# 境外基金 T 日淨值富邦是 T+1「下午」才補齊；排程太早會抓到舊值且把當天鎖死。
# → 只有抓到「夠新」（最新 nav_date ≥ 昨天）才鎖當日；仍偏舊就不鎖，等 18/20 時段補齊。
FRESH=$(/usr/bin/python3 -c "import json,datetime; d=json.load(open('fund-data.json')); latest=max(x['nav_date'] for x in d['funds']); yday=(datetime.date.today()-datetime.timedelta(days=1)).isoformat(); print('1' if latest>=yday else '0')")
if [ "$FRESH" = "1" ]; then
  echo "$TODAY" >"$MARKER"
else
  echo "$(ts) 最新淨值日期仍偏舊（富邦當天未補齊），不鎖當日，等下個時段重試" >>"$LOG"
fi

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
