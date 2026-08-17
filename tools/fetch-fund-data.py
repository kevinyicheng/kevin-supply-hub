#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
撈富邦投資型基金（DSP5 / TLZ64）最新淨值與每單位月配息，寫入 fund-data.json。
資料來源：invest.fubonlife.com.tw（MoneyDJ / 嘉實資訊）
- 淨值：BCDNavList.djbcd（第一行日期、第二行淨值，取最後一筆）
- 配息：wb05.djhtm（Big5 網頁，取最新一筆 除息日 / 發放日 / 每單位配息）

方案 A：由排程（Mac mini cron / launchd）每日執行，寫檔後 git commit + push，
前端讀同源 JSON，避開瀏覽器 CORS 與富邦反爬限制。

只用 Python 標準函式庫（urllib），不需 pip 安裝。
"""

import json
import re
import ssl
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ── 設定 ──────────────────────────────────────────────
FUND_CODE   = "TLZ64"          # MoneyDJ 基金代碼
FUND_LABEL  = "TLZ64-DSP5"     # 頁面參數 a=
FUND_NAME   = "DSP5"
BASE        = "https://invest.fubonlife.com.tw"
REFERER     = f"{BASE}/w/wb/wb02.djhtm?a={FUND_LABEL}"
TIMEOUT     = 20
TPE         = timezone(timedelta(hours=8))

OUT_PATH = Path(__file__).resolve().parent.parent / "fund-data.json"


def _fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/124.0 Safari/537.36",
        "Referer": REFERER,
        "Accept-Language": "zh-TW,zh;q=0.9",
    })
    ctx = ssl.create_default_context()
    with urllib.request.urlopen(req, timeout=TIMEOUT, context=ctx) as r:
        return r.read()


def fetch_nav() -> tuple[float, str]:
    """回傳 (最新淨值, 淨值日期 YYYY-MM-DD)。"""
    today = datetime.now(TPE).date()
    frm   = today - timedelta(days=45)
    url = (f"{BASE}/w/bcd/BCDNavList.djbcd?a={FUND_CODE}&b=1"
           f"&c={frm.year}-{frm.month}-{frm.day}"
           f"&d={today.year}-{today.month}-{today.day}")
    raw = _fetch(url).decode("utf-8", "ignore").strip()
    # djbcd 格式：日期區塊與淨值區塊以空白分隔（單行），各自逗號分隔
    blocks = raw.split()
    if len(blocks) < 2:
        raise ValueError(f"NAV 資料格式異常：{raw[:120]!r}")
    dates = blocks[0].split(",")
    navs  = blocks[1].split(",")
    d, v = dates[-1].strip(), navs[-1].strip()
    nav_date = f"{d[0:4]}-{d[4:6]}-{d[6:8]}"
    return round(float(v), 4), nav_date


def fetch_payout() -> tuple[float, str, str]:
    """回傳 (每單位配息, 除息日 YYYY-MM-DD, 發放日 YYYY-MM-DD)。取最新一筆。"""
    html = _fetch(f"{BASE}/w/wb/wb05.djhtm?a={FUND_LABEL}").decode("big5", "ignore")
    # 除息日 / 發放日 / 每單位配息金額
    m = re.search(
        r"(\d{4})/(\d{1,2})/(\d{1,2})\D+?(\d{4})/(\d{1,2})/(\d{1,2})\D+?(\d+\.\d+)",
        html)
    if not m:
        raise ValueError("找不到配息紀錄")
    ex  = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    pay = f"{m.group(4)}-{int(m.group(5)):02d}-{int(m.group(6)):02d}"
    return round(float(m.group(7)), 4), ex, pay


def main() -> int:
    try:
        nav, nav_date = fetch_nav()
        payout, ex_date, pay_date = fetch_payout()
    except Exception as e:  # noqa: BLE001
        print(f"[fetch-fund-data] 失敗：{e}", file=sys.stderr)
        return 1

    data = {
        "fund": FUND_NAME,
        "code": FUND_LABEL,
        "nav": nav,
        "nav_date": nav_date,
        "payout": payout,
        "payout_ex_date": ex_date,
        "payout_pay_date": pay_date,
        "updated_at": datetime.now(TPE).isoformat(timespec="seconds"),
        "source": "invest.fubonlife.com.tw",
    }
    OUT_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
    print(f"[fetch-fund-data] OK  淨值 {nav} ({nav_date})  "
          f"配息 {payout} (除息 {ex_date}) → {OUT_PATH.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
