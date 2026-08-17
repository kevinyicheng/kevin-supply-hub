#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
撈富邦投資型基金最新淨值與每單位配息，寫入 fund-data.json（支援多檔）。
資料來源：invest.fubonlife.com.tw（MoneyDJ / 嘉實資訊）
- 淨值：BCDNavList.djbcd（日期區塊與淨值區塊以空白分隔，各自逗號分隔，取最後一筆）
- 配息：wb05.djhtm（Big5 網頁，取最新一筆 除息日 / 發放日 / 每單位配息）

方案 A / B：由排程（launchd）每日執行，寫檔後 git commit + push，
前端讀同源 JSON 並自動生成基金下拉選單，避開瀏覽器 CORS 與富邦反爬限制。

新增基金：在下方 FUNDS 加一行 {"label": "<代碼>-<簡稱>", "name": "顯示名稱"} 即可，
label 取自富邦頁網址 a= 後的值（例：wb05.djhtm?a=JFZN3-JFP11 → "JFZN3-JFP11"）。

只用 Python 標準函式庫（urllib），不需 pip 安裝。
"""

import json
import re
import ssl
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ── 基金清單（唯一來源，前端下拉依此自動生成）────────────────
FUNDS = [
    {"label": "TLZ64-DSP5",  "name": "DSP5"},
    {"label": "JFZN3-JFP11", "name": "JFP11"},
]

BASE     = "https://invest.fubonlife.com.tw"
TIMEOUT  = 20
TPE      = timezone(timedelta(hours=8))
OUT_PATH = Path(__file__).resolve().parent.parent / "fund-data.json"


def _fetch(url: str, referer: str) -> bytes:
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/124.0 Safari/537.36",
        "Referer": referer,
        "Accept-Language": "zh-TW,zh;q=0.9",
    })
    ctx = ssl.create_default_context()
    with urllib.request.urlopen(req, timeout=TIMEOUT, context=ctx) as r:
        return r.read()


def fetch_nav(label: str) -> tuple[float, str]:
    """回傳 (最新淨值, 淨值日期 YYYY-MM-DD)。label 例：TLZ64-DSP5。"""
    code    = label.split("-", 1)[0]
    referer = f"{BASE}/w/wb/wb02.djhtm?a={label}"
    today = datetime.now(TPE).date()
    frm   = today - timedelta(days=45)
    url = (f"{BASE}/w/bcd/BCDNavList.djbcd?a={code}&b=1"
           f"&c={frm.year}-{frm.month}-{frm.day}"
           f"&d={today.year}-{today.month}-{today.day}")
    raw = _fetch(url, referer).decode("utf-8", "ignore").strip()
    # djbcd 格式：日期區塊與淨值區塊以空白分隔（單行），各自逗號分隔
    blocks = raw.split()
    if len(blocks) < 2:
        raise ValueError(f"NAV 資料格式異常：{raw[:120]!r}")
    dates = blocks[0].split(",")
    navs  = blocks[1].split(",")
    d, v = dates[-1].strip(), navs[-1].strip()
    nav_date = f"{d[0:4]}-{d[4:6]}-{d[6:8]}"
    return round(float(v), 4), nav_date


def fetch_payout(label: str):
    """回傳 (每單位配息, 除息日, 發放日) 或 None（無配息記錄）。"""
    referer = f"{BASE}/w/wb/wb02.djhtm?a={label}"
    html = _fetch(f"{BASE}/w/wb/wb05.djhtm?a={label}", referer).decode("big5", "ignore")
    m = re.search(
        r"(\d{4})/(\d{1,2})/(\d{1,2})\D+?(\d{4})/(\d{1,2})/(\d{1,2})\D+?(\d+\.\d+)",
        html)
    if not m:
        return None
    ex  = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    pay = f"{m.group(4)}-{int(m.group(5)):02d}-{int(m.group(6)):02d}"
    return round(float(m.group(7)), 4), ex, pay


def build_fund(cfg: dict) -> dict:
    label, name = cfg["label"], cfg["name"]
    nav, nav_date = fetch_nav(label)
    entry = {
        "code": label,
        "name": name,
        "nav": nav,
        "nav_date": nav_date,
        "url": f"{BASE}/w/wb/wb02.djhtm?a={label}",
    }
    payout = fetch_payout(label)
    if payout:
        entry.update({
            "has_payout": True,
            "payout": payout[0],
            "payout_ex_date": payout[1],
            "payout_pay_date": payout[2],
        })
    else:
        entry["has_payout"] = False
    return entry


def main() -> int:
    funds, errors = [], []
    for cfg in FUNDS:
        try:
            funds.append(build_fund(cfg))
        except Exception as e:  # noqa: BLE001
            errors.append(f"{cfg['label']}：{e}")
            print(f"[fetch-fund-data] {cfg['label']} 失敗：{e}", file=sys.stderr)

    if not funds:
        print("[fetch-fund-data] 全部基金抓取失敗，不寫檔", file=sys.stderr)
        return 1

    # 數字沒變就不改寫檔案（updated_at 只在數據變動時更新），避免每日產生無意義 commit
    if OUT_PATH.exists():
        try:
            old = json.loads(OUT_PATH.read_text(encoding="utf-8")).get("funds")
            if old == funds:
                print("[fetch-fund-data] 淨值/配息與上次相同，不改寫檔案")
                for f in funds:
                    po = (f"配息 {f['payout']} (除息 {f['payout_ex_date']})"
                          if f["has_payout"] else "無配息")
                    print(f"[fetch-fund-data] · {f['name']}：淨值 {f['nav']} ({f['nav_date']})  {po}")
                return 0
        except Exception:  # noqa: BLE001
            pass  # 舊檔壞了就照常改寫

    data = {
        "updated_at": datetime.now(TPE).isoformat(timespec="seconds"),
        "source": "invest.fubonlife.com.tw",
        "funds": funds,
    }
    OUT_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
    for f in funds:
        po = f"配息 {f['payout']} (除息 {f['payout_ex_date']})" if f["has_payout"] else "無配息"
        print(f"[fetch-fund-data] OK  {f['name']}：淨值 {f['nav']} ({f['nav_date']})  {po}")
    if errors:
        # 部分失敗：仍寫檔保留成功的基金，錯誤已進 stderr（排程 log），回 0 讓其正常提交
        print(f"[fetch-fund-data] 注意：{len(errors)} 檔失敗 → {'; '.join(errors)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
