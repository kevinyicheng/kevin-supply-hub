#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
撈富邦投資型基金最新淨值與每單位配息，寫入 fund-data.json（支援多檔）。
資料來源：invest.fubonlife.com.tw 新版 Nuxt 站的同源 JSON API
- 淨值：POST /api/fund/getFundNavs      body {assetFbCode, startDate, endDate}
- 配息：POST /api/fund/getFundDividends body {assetFbCode}
  兩者回 {"returnCode":"0000","data":[...]}，data 依日期新到舊，取 data[0]。

※ 2026-10-19 富邦改版：舊的 BCDNavList.djbcd / wb05.djhtm 已廢。新 API 必須打
  「自家 origin」invest.fubonlife.com.tw/api/fund/*（Nuxt 伺服器代理到 moneydj），
  直連 fubonliferwd.moneydj.com 會被 WAF 擋（R002 SQL Filter）。瀏覽器端有 CORS，
  但本腳本是 server-side，無 CORS 限制，可直接 POST。

方案 A / B：由排程（launchd）每日執行，寫檔後 git commit + push，
前端讀同源 JSON 並自動生成基金下拉選單。

新增基金：在下方 FUNDS 加一行 {"code": "<代碼>", "cat": "<分類序號>", "name_zh": "顯示名稱"}。
code 與 cat 都取自富邦基金頁網址，例：
  https://invest.fubonlife.com.tw/funds/overview/WFUND/25/DSP5 → cat="25", code="DSP5"
  code 即新 API 的 assetFbCode；cat 是 WFUND 後的分類序號，逐檔不同（DSP5=25、JFP11=39、MLE20=27），
  只影響前端「查看來源」連結，抓數據的 API 不吃它。

只用 Python 標準函式庫（urllib），不需 pip 安裝。
"""

import json
import ssl
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ── 基金清單（唯一來源，前端下拉依此自動生成）────────────────
FUNDS = [
    {"code": "DSP5",  "cat": "25", "name_zh": "安聯收益成長基金-AM穩定月收類股(美元)"},
    {"code": "JFP11", "cat": "39", "name_zh": "摩根多重收益基金(美元對沖)-A股(穩定月配)"},
    {"code": "MLE20", "cat": "27", "name_zh": "貝萊德全球智慧數據股票入息基金A6美元(穩定配息)"},
    {"code": "SCP6",  "cat": "29", "name_zh": "施羅德環球基金系列-環球收益成長(美元)A-月配固定2"},
    {"code": "ACE17", "cat": "40", "name_zh": "聯博-美國成長基金AP(總報酬月配)級別美元"},
]

BASE     = "https://invest.fubonlife.com.tw"
API      = f"{BASE}/api/fund"
TIMEOUT  = 20
TPE      = timezone(timedelta(hours=8))
OUT_PATH = Path(__file__).resolve().parent.parent / "fund-data.json"


def fund_url(code: str, cat: str = "25") -> str:
    """基金詳情頁（前端「查看來源」連結）。cat = 富邦 WFUND 分類序號，逐檔不同。"""
    return f"{BASE}/funds/overview/WFUND/{cat}/{code}"


def _post(endpoint: str, payload: dict, referer: str) -> dict:
    """POST JSON 給同源 API，回傳解析後的 dict（含 data 陣列）。"""
    req = urllib.request.Request(
        f"{API}/{endpoint}",
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Origin": BASE,
            "Referer": referer,
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/124.0 Safari/537.36",
            "Accept-Language": "zh-TW,zh;q=0.9",
        })
    ctx = ssl.create_default_context()
    with urllib.request.urlopen(req, timeout=TIMEOUT, context=ctx) as r:
        obj = json.loads(r.read().decode("utf-8", "ignore"))
    if obj.get("returnCode") != "0000":
        raise ValueError(f"{endpoint} 回傳失敗：{obj.get('returnCode')} {obj.get('message')}")
    return obj


def _ymd(s: str) -> str:
    """'2026/10/16' → '2026-10-16'。"""
    return s.strip().replace("/", "-")


def fetch_nav(code: str, referer: str) -> tuple[float, str]:
    """回傳 (最新淨值, 淨值日期 YYYY-MM-DD)。"""
    today = datetime.now(TPE).date()
    frm   = today - timedelta(days=45)
    obj = _post("getFundNavs", {
        "assetFbCode": code,
        "startDate": frm.isoformat(),
        "endDate": today.isoformat(),
    }, referer)
    data = obj.get("data") or []
    if not data:
        raise ValueError("NAV data 為空")
    latest = max(data, key=lambda x: x["date"])  # 取日期最新一筆，不依賴排序
    return round(float(latest["nav"]), 4), _ymd(latest["date"])


def fetch_payout(code: str, referer: str):
    """回傳 (每單位配息, 除息日, 發放日) 或 None（無有效配息記錄）。"""
    obj = _post("getFundDividends", {"assetFbCode": code}, referer)
    data = obj.get("data") or []
    # 只取真正有配息（status=配息 且金額 > 0）的最新一筆
    valid = [d for d in data
             if d.get("status") == "配息" and float(d.get("dividendPerUnit") or 0) > 0]
    if not valid:
        return None
    latest = max(valid, key=lambda x: x["recordDate"])
    return (round(float(latest["dividendPerUnit"]), 4),
            _ymd(latest["recordDate"]),    # 除息日
            _ymd(latest["dividendDate"]))  # 發放日


def build_fund(cfg: dict) -> dict:
    code = cfg["code"]
    url = fund_url(code, cfg.get("cat", "25"))
    nav, nav_date = fetch_nav(code, url)
    entry = {
        "code": code,
        "name": code,
        "name_zh": cfg.get("name_zh", code),
        "nav": nav,
        "nav_date": nav_date,
        "url": url,
    }
    payout = fetch_payout(code, url)
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
            errors.append(f"{cfg['code']}：{e}")
            print(f"[fetch-fund-data] {cfg['code']} 失敗：{e}", file=sys.stderr)

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
