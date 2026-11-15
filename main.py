import os
import math
import time
import asyncio
import sqlite3
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any

import httpx
import uvicorn
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

TEHRAN_TZ = timezone(timedelta(hours=3, minutes=30))
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = "/tmp/standalone_market.db" if os.path.isdir("/tmp") else os.path.join(BASE_DIR, "standalone_market.db")

TSETMC_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "fa-IR,fa;q=0.9,en-US;q=0.8",
    "Referer": "https://tsetmc.com/",
    "Origin": "https://tsetmc.com",
}

BRSAPI_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 6.1; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 OPR/106.0.0.0",
    "Accept": "application/json, text/plain, */*",
}

app = FastAPI(title="چارت کندل‌استیک حرفه‌ای + تحلیل کل بازار")

def norm_fa(text: str) -> str:
    if not text:
        return ""
    return (
        str(text).strip().upper()
        .replace("ي", "ی").replace("ك", "ک").replace("ة", "ه")
        .replace("\u200c", "").replace("‌", "").replace(" ", "").replace("-", "")
    )

def _f(v) -> float:
    try:
        if v is None:
            return 0.0
        return float(str(v).replace(",", "").strip())
    except Exception:
        return 0.0

def _unwrap_list(payload) -> list:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for k in ("data", "Data", "history", "History", "items", "result", "Result", "symbols"):
            if isinstance(payload.get(k), list):
                return payload[k]
    return []

def _to_iso_date(raw_date, fallback_idx: int, total: int) -> str:
    s = str(raw_date or "").strip()
    if len(s) == 8 and s.isdigit() and s.startswith("20"):
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    if len(s) >= 10 and s[:4].isdigit() and s[:2] == "20":
        return s[:10].replace("/", "-")
    dt = datetime.now(TEHRAN_TZ) - timedelta(days=(total - 1 - fallback_idx))
    return dt.strftime("%Y-%m-%d")

CRYPTO_FA_NAMES = {
    "BTC": "بیت کوین بیتکوین", "ETH": "اتریوم اتريوم", "SOL": "سولانا سول",
    "BNB": "بایننس کوین بی ان بی", "XRP": "ریپل", "ADA": "کاردانو آدا",
    "DOGE": "دوج کوین دوج", "TRX": "ترون", "TON": "تون کوین تون",
    "AVAX": "آوالانچ اولانچ", "SHIB": "شیبا اینو شیبا", "PEPE": "پپه",
    "LINK": "چین لینک لینک", "DOT": "پولکادات دات", "SUI": "سویی",
    "LTC": "لایت کوین", "BCH": "بیت کوین کش", "NEAR": "نیر پروتکل نیر",
    "APT": "اپتوس", "ARB": "آربیتروم", "OP": "اپتیمیزم",
    "POL": "پالیگان متیک", "MATIC": "متیک پالیگان", "UNI": "یونی سواپ",
    "ATOM": "کازموس اتم", "FIL": "فایل کوین", "ICP": "اینترنت کامپیوتر",
    "RENDER": "رندر", "FET": "فچ ای آی فچ", "TAO": "تائو بیت تنسور",
    "WIF": "ویف داگ ویف هت", "BONK": "بونک", "FLOKI": "فلوکی",
    "NOT": "نات کوین نات", "DOGS": "داگز", "HMSTR": "همستر کامبت همستر",
    "CATI": "کتیزن", "MAJOR": "میجر", "KAS": "کاسپا", "XLM": "استلار",
    "ETC": "اتریوم کلاسیک", "ALGO": "الگوراند", "VET": "ویچین",
    "SAND": "سندباکس سند", "MANA": "مانا دیسنترالند", "GALA": "گالا",
    "AXS": "اکسی اینفینیتی", "INJ": "اینجکتیو", "SEI": "سی",
    "TIA": "سلستیا", "STX": "استکس", "IMX": "ایمیوتبل",
    "GRT": "گراف", "AAVE": "آوه", "MKR": "میکر", "CRV": "کرو",
    "LDO": "لیدو", "RUNE": "رون", "CAKE": "کیک پنکیک سواپ",
    "DYDX": "دی وای دی ایکس", "EOS": "ایاس", "XTZ": "تزوس",
    "THETA": "تتا", "KAVA": "کاوا", "ZEC": "زی کش", "DASH": "دش",
    "XMR": "مونرو", "PAXG": "پکس گلد طلا", "ENA": "اتنا",
    "EIGEN": "آیگن لیر", "TRUMP": "ترامپ", "PENGU": "پنگو",
    "ONDO": "اوندو", "HBAR": "هدرا", "OM": "مانترا", "WLD": "ورلد کوین",
    "JUP": "ژوپیتر", "PYTH": "پیت", "STRK": "استارک نت",
    "ORDI": "اوردی", "BOME": "بوم", "MEME": "میم کوین",
    "NEIRO": "نیرو", "TURBO": "توربو", "POPCAT": "پاپ کت",
    "PNUT": "پینات", "USUAL": "یوژوال", "MOVE": "موو", "KAITO": "کایتو",
    "FTM": "فانتوم", "S": "سونیک", "CHZ": "چیلیز", "APE": "ایپ کوین",
    "USDT": "تتر دلار دیجیتال", "USDC": "یو اس دی کوین"
}

def get_conn():
    conn = sqlite3.connect(DB_FILE)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS portfolio (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL, market TEXT NOT NULL,
            quantity REAL NOT NULL, avg_buy_price_toman REAL NOT NULL, created_at TEXT NOT NULL
        )
    """)
    conn.commit()
    return conn

HORIZON_SPECS = {
    "H1_DAILY":   {"label": "۱) روزانه",   "min_bars": 10,  "vol_scale": 1.4},
    "H2_WEEKLY":  {"label": "۲) هفتگی",    "min_bars": 20,  "vol_scale": 3.2},
    "H3_MONTHLY": {"label": "۳) ماهانه",   "min_bars": 45,  "vol_scale": 6.5},
    "H4_120D":    {"label": "۴) ۱۲۰ روزه", "min_bars": 120, "vol_scale": 12.0},
}

CRYPTO_CACHE: Dict[str, Any] = {"ts": 0, "items": [], "source": "NOT_LOADED"}
BOURSE_CACHE: Dict[str, Any] = {"ts": 0, "items": [], "source": "NOT_LOADED", "key_used": ""}
CANDLE_CACHE: Dict[str, Dict[str, Any]] = {}

STATIC_OTHER = {
    "metals": [
        {"symbol": "GOLD18", "name": "طلای ۱۸ عیار (گرم)", "today": 4620000, "yesterday": 4550000, "unit": "تومان"},
        {"symbol": "GOLD24", "name": "طلای ۲۴ عیار (گرم)", "today": 6160000, "yesterday": 6066000, "unit": "تومان"},
        {"symbol": "ABSHODE", "name": "طلای آبشده (مثقال)", "today": 20010000, "yesterday": 19710000, "unit": "تومان"},
        {"symbol": "EMAMI", "name": "سکه امامی", "today": 52400000, "yesterday": 51700000, "unit": "تومان"},
        {"symbol": "BAHAR", "name": "سکه بهار آزادی", "today": 49800000, "yesterday": 49100000, "unit": "تومان"},
        {"symbol": "NIM", "name": "نیم‌سکه", "today": 27300000, "yesterday": 26900000, "unit": "تومان"},
        {"symbol": "ROB", "name": "ربع‌سکه", "today": 17100000, "yesterday": 16850000, "unit": "تومان"},
        {"symbol": "GERAMI", "name": "سکه گرمی", "today": 8200000, "yesterday": 8100000, "unit": "تومان"},
        {"symbol": "GOLD_2ND", "name": "طلای دست دوم", "today": 4558000, "yesterday": 4490000, "unit": "تومان"},
        {"symbol": "XAUUSD", "name": "انس جهانی طلا", "today": 2645, "yesterday": 2618, "unit": "دلار"},
        {"symbol": "XAGUSD", "name": "انس جهانی نقره", "today": 31.4, "yesterday": 30.8, "unit": "دلار"},
        {"symbol": "SILVER_G", "name": "نقره ۹۹۹ (گرم)", "today": 86500, "yesterday": 84900, "unit": "تومان"},
        {"symbol": "XPTUSD", "name": "پلاتین جهانی", "today": 975, "yesterday": 968, "unit": "دلار"},
        {"symbol": "XPDUSD", "name": "پالادیوم جهانی", "today": 1035, "yesterday": 1042, "unit": "دلار"},
        {"symbol": "COPPER", "name": "مس جهانی (پوند)", "today": 4.21, "yesterday": 4.15, "unit": "دلار"},
    ],
    "etfs": [
        {"symbol": "عیار", "name": "صندوق طلای عیار", "today": 19850, "yesterday": 19450, "unit": "تومان", "type": "طلا"},
        {"symbol": "طلا", "name": "صندوق طلای لوتوس", "today": 24100, "yesterday": 23650, "unit": "تومان", "type": "طلا"},
        {"symbol": "کهربا", "name": "صندوق طلای کهربا", "today": 15200, "yesterday": 14900, "unit": "تومان", "type": "طلا"},
        {"symbol": "گنج", "name": "صندوق طلای گنج", "today": 16400, "yesterday": 16100, "unit": "تومان", "type": "طلا"},
        {"symbol": "اهرم", "name": "صندوق اهرمی کاریزما", "today": 2480, "yesterday": 2410, "unit": "تومان", "type": "اهرمی"},
        {"symbol": "شتاب", "name": "صندوق اهرمی شتاب", "today": 1960, "yesterday": 1915, "unit": "تومان", "type": "اهرمی"},
        {"symbol": "موج", "name": "صندوق اهرمی موج", "today": 2120, "yesterday": 2080, "unit": "تومان", "type": "اهرمی"},
        {"symbol": "توان", "name": "صندوق اهرمی توان", "today": 2650, "yesterday": 2590, "unit": "تومان", "type": "اهرمی"},
        {"symbol": "کمند", "name": "درآمد ثابت کمند", "today": 1052, "yesterday": 1051, "unit": "تومان", "type": "درآمد ثابت"},
        {"symbol": "امین یکم", "name": "درآمد ثابت امین", "today": 10180, "yesterday": 10172, "unit": "تومان", "type": "درآمد ثابت"},
        {"symbol": "فیروزا", "name": "درآمد ثابت فیروزه", "today": 11240, "yesterday": 11230, "unit": "تومان", "type": "درآمد ثابت"},
        {"symbol": "کیان", "name": "صندوق سهامی کیان", "today": 4310, "yesterday": 4240, "unit": "تومان", "type": "سهامی"},
        {"symbol": "آگاس", "name": "صندوق سهامی آگاس", "today": 5120, "yesterday": 5060, "unit": "تومان", "type": "سهامی"},
        {"symbol": "اطلس", "name": "صندوق سهامی اطلس", "today": 3890, "yesterday": 3850, "unit": "تومان", "type": "سهامی"},
        {"symbol": "کارا", "name": "درآمد ثابت کارا", "today": 1345, "yesterday": 1344, "unit": "تومان", "type": "درآمد ثابت"},
    ],
    "forex": [
        {"symbol": "USD", "name": "دلار آمریکا", "today": 70200, "yesterday": 69500, "unit": "تومان"},
        {"symbol": "EUR", "name": "یورو اروپا", "today": 74500, "yesterday": 73800, "unit": "تومان"},
        {"symbol": "GBP", "name": "پوند انگلیس", "today": 89100, "yesterday": 88300, "unit": "تومان"},
        {"symbol": "AED", "name": "درهم امارات", "today": 19150, "yesterday": 18980, "unit": "تومان"},
        {"symbol": "TRY", "name": "لیر ترکیه", "today": 2040, "yesterday": 2025, "unit": "تومان"},
        {"symbol": "CNY", "name": "یوان چین", "today": 9720, "yesterday": 9640, "unit": "تومان"},
        {"symbol": "CAD", "name": "دلار کانادا", "today": 50100, "yesterday": 49650, "unit": "تومان"},
        {"symbol": "AUD", "name": "دلار استرالیا", "today": 45800, "yesterday": 45400, "unit": "تومان"},
        {"symbol": "CHF", "name": "فرانک سوئیس", "today": 79600, "yesterday": 78900, "unit": "تومان"},
        {"symbol": "JPY", "name": "۱۰۰ ین ژاپن", "today": 45600, "yesterday": 45200, "unit": "تومان"},
        {"symbol": "SAR", "name": "ریال عربستان", "today": 18710, "yesterday": 18520, "unit": "تومان"},
        {"symbol": "RUB", "name": "روبل روسیه", "today": 715, "yesterday": 720, "unit": "تومان"},
        {"symbol": "IQD", "name": "۱۰۰۰ دینار عراق", "today": 53600, "yesterday": 53100, "unit": "تومان"},
        {"symbol": "KRW", "name": "۱۰۰۰ وون کره", "today": 50200, "yesterday": 49800, "unit": "تومان"},
        {"symbol": "INR", "name": "روپیه هند", "today": 832, "yesterday": 825, "unit": "تومان"},
    ]
}

def enrich_comparison(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for it in items:
        t, y = float(it.get("today") or 0), float(it.get("yesterday") or 0)
        pct = ((t - y) / y * 100.0) if y > 0 else 0.0
        out.append({**it, "diff": round(t - y, 6), "change_pct": round(pct, 2)})
    return out

async def load_all_crypto(force: bool = False):
    now = time.time()
    if not force and CRYPTO_CACHE["items"] and (now - CRYPTO_CACHE["ts"] < 60):
        return CRYPTO_CACHE

    merged: Dict[str, Dict[str, Any]] = {}
    sources_used = []
    async with httpx.AsyncClient(timeout=5.0) as client:
        try:
            r = await client.get("https://data-api.binance.vision/api/v3/ticker/24hr")
            if r.status_code == 200:
                sources_used.append("BINANCE")
                for row in r.json():
                    sym = row.get("symbol", "")
                    if not sym.endswith("USDT") or any(x in sym for x in ("UPUSDT", "DOWNUSDT", "BULL", "BEAR")):
                        continue
                    base = sym[:-4]
                    last_p, prev_p, qvol = _f(row.get("lastPrice")), _f(row.get("prevClosePrice")), _f(row.get("quoteVolume"))
                    if last_p > 0 and qvol > 20000:
                        fa = CRYPTO_FA_NAMES.get(base, "")
                        merged[base] = {
                            "symbol": base, "fa_name": fa, "name": f"{fa.split()[0] + ' - ' if fa else ''}{base}/USDT",
                            "search_key": norm_fa(f"{base} {fa}"), "market": "CRYPTO",
                            "today": last_p, "yesterday": prev_p if prev_p > 0 else last_p, "unit": "دلار", "quote_vol": qvol
                        }
        except Exception:
            pass

        try:
            r2 = await client.get("https://api.kucoin.com/api/v1/market/allTickers")
            if r2.status_code == 200:
                sources_used.append("KUCOIN")
                for row in (r2.json().get("data") or {}).get("ticker", []):
                    sym = row.get("symbol", "")
                    if not sym.endswith("-USDT"):
                        continue
                    base = sym[:-5]
                    last_p, chg_rate, qvol = _f(row.get("last")), _f(row.get("changeRate")), _f(row.get("volValue"))
                    if last_p > 0 and base not in merged and qvol > 5000:
                        fa = CRYPTO_FA_NAMES.get(base, "")
                        yest = last_p / (1.0 + chg_rate) if chg_rate > -0.99 else last_p
                        merged[base] = {
                            "symbol": base, "fa_name": fa, "name": f"{fa.split()[0] + ' - ' if fa else ''}{base}/USDT",
                            "search_key": norm_fa(f"{base} {fa}"), "market": "CRYPTO",
                            "today": last_p, "yesterday": round(yest, 8), "unit": "دلار", "quote_vol": qvol
                        }
        except Exception:
            pass

    if merged:
        items = sorted(merged.values(), key=lambda x: x["quote_vol"], reverse=True)
        CRYPTO_CACHE.update({"ts": now, "items": items, "source": "+".join(sources_used)})
    return CRYPTO_CACHE

async def load_all_bourse(brs_key_override: str = "", force: bool = False):
    brs_key = (brs_key_override or os.getenv("BRSAPI_KEY", "")).strip()
    now = time.time()
    if not force and BOURSE_CACHE["items"] and (now - BOURSE_CACHE["ts"] < 120) and BOURSE_CACHE["key_used"] == brs_key:
        return BOURSE_CACHE

    items = []
    diag = []
    if brs_key:
        try:
            async with httpx.AsyncClient(timeout=7.0, headers=BRSAPI_HEADERS) as client:
                r = await client.get("https://Api.BrsApi.ir/Tsetmc/AllSymbols.php", params={"key": brs_key, "type": "1"})
                diag.append(f"BRS_ALL:{r.status_code}")
                if r.status_code == 200:
                    for x in _unwrap_list(r.json()):
                        sym = str(x.get("l18") or "").strip()
                        t_rial = _f(x.get("pl") or x.get("pc"))
                        y_rial = _f(x.get("py")) or t_rial
                        if sym and t_rial > 0:
                            nm = str(x.get("l30") or sym).strip()
                            items.append({
                                "symbol": sym, "name": nm, "search_key": norm_fa(f"{sym} {nm}"),
                                "market": "BOURSE", "ins_code": str(x.get("id") or x.get("insCode") or ""),
                                "today": round(t_rial / 10.0, 2), "yesterday": round(y_rial / 10.0, 2),
                                "unit": "تومان", "pe": _f(x.get("pe")), "eps": _f(x.get("eps")), "tvol": _f(x.get("tvol"))
                            })
                    if items:
                        BOURSE_CACHE.update({"ts": now, "items": items, "source": f"LIVE_BRSAPI ({len(items)} نماد)", "key_used": brs_key})
                        return BOURSE_CACHE
        except Exception as e:
            diag.append(f"BRS_ERR:{type(e).__name__}")
    else:
        diag.append("BRS_KEY:EMPTY")

    async with httpx.AsyncClient(timeout=4.5, headers=TSETMC_HEADERS) as client:
        try:
            pt = "&".join(f"paperTypes%5B{i}%5D={i+1}" for i in range(9))
            r = await client.get(f"https://cdn.tsetmc.com/api/ClosingPrice/GetMarketWatch?market=0&{pt}&showTraded=false&withBestLimits=false&hEven=0&RefID=0")
            diag.append(f"TSETMC:{r.status_code}")
            if r.status_code == 200:
                for x in (r.json().get("marketwatch") or []):
                    sym = str(x.get("lVal18AFC") or "").strip()
                    t_rial = _f(x.get("pClosing") or x.get("pDrCotVal"))
                    y_rial = _f(x.get("priceYesterday")) or t_rial
                    if sym and t_rial > 0:
                        nm = str(x.get("lVal30") or sym).strip()
                        items.append({
                            "symbol": sym, "name": nm, "search_key": norm_fa(f"{sym} {nm}"),
                            "market": "BOURSE", "ins_code": str(x.get("insCode") or ""),
                            "today": round(t_rial / 10.0, 2), "yesterday": round(y_rial / 10.0, 2),
                            "unit": "تومان", "pe": 0, "eps": 0, "tvol": _f(x.get("qTotTran5J"))
                        })
                if len(items) > 50:
                    BOURSE_CACHE.update({"ts": now, "items": items, "source": f"LIVE_TSETMC ({len(items)} نماد)", "key_used": brs_key})
                    return BOURSE_CACHE
        except Exception as e:
            diag.append(f"TSETMC_ERR:{type(e).__name__}")

    BOURSE_CACHE.update({"ts": now, "items": items, "source": " | ".join(diag), "key_used": brs_key})
    return BOURSE_CACHE

def _clean_sort_candles(raw_candles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    by_time = {}
    for c in raw_candles:
        if c["close"] > 0 and c["open"] > 0 and c["high"] >= c["low"]:
            by_time[c["time"]] = c
    return [by_time[k] for k in sorted(by_time.keys())]

async def fetch_180_candles(symbol: str, market: str, item: Dict[str, Any], brs_key_override: str = "") -> Dict[str, Any]:
    brs_key = (brs_key_override or os.getenv("BRSAPI_KEY", "")).strip()
    ckey = f"{market}:{norm_fa(symbol)}:{brs_key[:6]}"
    now = time.time()
    if ckey in CANDLE_CACHE and (now - CANDLE_CACHE[ckey]["ts"] < 300):
        return CANDLE_CACHE[ckey]

    candles, diag = [], []
    if market == "CRYPTO":
        async with httpx.AsyncClient(timeout=4.5) as client:
            try:
                r = await client.get(f"https://data-api.binance.vision/api/v3/klines?symbol={symbol.upper()}USDT&interval=1d&limit=180")
                if r.status_code == 200 and isinstance(r.json(), list):
                    for k in r.json():
                        candles.append({
                            "time": int(k[0] / 1000),
                            "open": float(k[1]), "high": float(k[2]), "low": float(k[3]), "close": float(k[4]), "vol": float(k[5])
                        })
                    candles = _clean_sort_candles(candles)
                    if candles:
                        res = {"ts": now, "source": "LIVE_BINANCE_1D", "candles": candles}
                        CANDLE_CACHE[ckey] = res
                        return res
            except Exception as e:
                diag.append(f"BINANCE:{type(e).__name__}")

            try:
                r2 = await client.get(f"https://api.kucoin.com/api/v1/market/candles?symbol={symbol.upper()}-USDT&type=1day")
                if r2.status_code == 200:
                    raw = (r2.json().get("data") or [])[:180]
                    for k in raw:
                        candles.append({
                            "time": int(k[0]),
                            "open": float(k[1]), "close": float(k[2]), "high": float(k[3]), "low": float(k[4]), "vol": float(k[5])
                        })
                    candles = _clean_sort_candles(candles)
                    if candles:
                        res = {"ts": now, "source": "LIVE_KUCOIN_1D", "candles": candles}
                        CANDLE_CACHE[ckey] = res
                        return res
            except Exception as e:
                diag.append(f"KUCOIN:{type(e).__name__}")

    elif market == "BOURSE":
        if brs_key:
            try:
                async with httpx.AsyncClient(timeout=7.0, headers=BRSAPI_HEADERS) as client:
                    rh = await client.get("https://Api.BrsApi.ir/Tsetmc/History.php", params={"key": brs_key, "type": "0", "l18": symbol})
                    diag.append(f"BRS_HIST:{rh.status_code}")
                    if rh.status_code == 200:
                        rows = _unwrap_list(rh.json())
                        if len(rows) >= 2 and str(rows[0].get("date") or "") > str(rows[-1].get("date") or ""):
                            rows = list(reversed(rows))
                        rows = rows[-180:]
                        base_ts = int((datetime.now(TEHRAN_TZ) - timedelta(days=len(rows))).timestamp())
                        for idx, row in enumerate(rows):
                            c = _f(row.get("pc") or row.get("pl") or row.get("pClosing") or row.get("close")) / 10.0
                            if c > 0:
                                o = (_f(row.get("pf") or row.get("priceFirst") or row.get("open")) / 10.0) or c
                                h = (_f(row.get("pmax") or row.get("priceMax") or row.get("high")) / 10.0) or max(o, c)
                                l = (_f(row.get("pmin") or row.get("priceMin") or row.get("low")) / 10.0) or min(o, c)
                                candles.append({"time": base_ts + idx * 86400, "open": o, "high": max(h, o, c), "low": min(l, o, c), "close": c, "vol": _f(row.get("tvol"))})
                        candles = _clean_sort_candles(candles)
                        if candles:
                            res = {"ts": now, "source": "LIVE_BRSAPI_1D", "candles": candles}
                            CANDLE_CACHE[ckey] = res
                            return res
            except Exception as e:
                diag.append(f"BRS_ERR:{type(e).__name__}")
        else:
            diag.append("BRS_KEY:EMPTY")

        async with httpx.AsyncClient(timeout=5.0, headers=TSETMC_HEADERS) as client:
            ins_code = item.get("ins_code")
            if ins_code:
                try:
                    rh = await client.get(f"https://cdn.tsetmc.com/api/ClosingPrice/GetClosingPriceDailyList/{ins_code}/180")
                    diag.append(f"TSE_DAILY:{rh.status_code}")
                    if rh.status_code == 200:
                        rows = list(reversed(rh.json().get("closingPriceDaily") or []))
                        for idx, row in enumerate(rows):
                            c = _f(row.get("pClosing")) / 10.0
                            if c > 0:
                                d_str = str(row.get("dEven") or "")
                                try:
                                    ts = int(datetime.strptime(d_str, "%Y%m%d").replace(tzinfo=TEHRAN_TZ).timestamp())
                                except Exception:
                                    ts = int(time.time()) - (len(rows) - idx) * 86400
                                o = (_f(row.get("priceFirst")) / 10.0) or c
                                h = (_f(row.get("priceMax")) / 10.0) or max(o, c)
                                l = (_f(row.get("priceMin")) / 10.0) or min(o, c)
                                candles.append({"time": ts, "open": o, "high": max(h, o, c), "low": min(l, o, c), "close": c, "vol": _f(row.get("qTotTran5J"))})
                        candles = _clean_sort_candles(candles)
                        if candles:
                            res = {"ts": now, "source": "LIVE_TSETMC_1D", "candles": candles}
                            CANDLE_CACHE[ckey] = res
                            return res
                except Exception as e:
                    diag.append(f"TSE_ERR:{type(e).__name__}")

    return {"ts": now, "source": " | ".join(diag) or "NO_DATA", "candles": []}

# ==========================================
# محاسبات کامل اندیکاتورها و پرایس اکشن برای رسم روی چارت
# ==========================================
def calc_ema(vals: List[float], period: int) -> List[float]:
    k = 2.0 / (period + 1)
    out = [vals[0]]
    for v in vals[1:]:
        out.append(v * k + out[-1] * (1.0 - k))
    return out

def calc_rsi(closes: List[float], period: int = 14) -> List[float]:
    if len(closes) < 2:
        return [50.0] * len(closes)
    rsis, gains, losses = [50.0], [], []
    for i in range(1, len(closes)):
        chg = closes[i] - closes[i - 1]
        gains.append(max(chg, 0.0))
        losses.append(max(-chg, 0.0))
        ag = sum(gains[-period:]) / len(gains[-period:])
        al = sum(losses[-period:]) / len(losses[-period:])
        rsis.append(100.0 if (al == 0 and ag > 0) else (50.0 if al == 0 else round(100.0 - (100.0 / (1.0 + ag / al)), 2)))
    return rsis

def calc_bollinger(closes: List[float], period: int = 20, mult: float = 2.0):
    upper, lower = [], []
    for i in range(len(closes)):
        win = closes[max(0, i - period + 1):i + 1]
        mean = sum(win) / len(win)
        var = sum((x - mean) ** 2 for x in win) / len(win)
        sd = math.sqrt(var)
        upper.append(round(mean + mult * sd, 6))
        lower.append(round(mean - mult * sd, 6))
    return upper, lower

def detect_price_action(candles: List[Dict[str, Any]]):
    markers = []
    n = len(candles)
    last_pivot_h, last_pivot_l = None, None
    support_levels, resistance_levels = [], []

    for i in range(2, n - 2):
        h, l = candles[i]["high"], candles[i]["low"]
        # پیوت سقف (HH / LH)
        if h > candles[i-1]["high"] and h > candles[i-2]["high"] and h > candles[i+1]["high"] and h > candles[i+2]["high"]:
            lbl = "HH" if (last_pivot_h is None or h > last_pivot_h) else "LH"
            last_pivot_h = h
            resistance_levels.append(h)
            markers.append({"time": candles[i]["time"], "position": "aboveBar", "color": "#fbbf24", "shape": "circle", "text": lbl})
        # پیوت کف (HL / LL)
        if l < candles[i-1]["low"] and l < candles[i-2]["low"] and l < candles[i+1]["low"] and l < candles[i+2]["low"]:
            lbl = "HL" if (last_pivot_l is None or l > last_pivot_l) else "LL"
            last_pivot_l = l
            support_levels.append(l)
            markers.append({"time": candles[i]["time"], "position": "belowBar", "color": "#38bdf8", "shape": "circle", "text": lbl})

    # الگوهای کندلی پین‌بار و اینگالفینگ
    for i in range(1, n):
        c = candles[i]
        p = candles[i - 1]
        body = abs(c["close"] - c["open"])
        rng = max(c["high"] - c["low"], 1e-12)
        up_w = c["high"] - max(c["open"], c["close"])
        lo_w = min(c["open"], c["close"]) - c["low"]

        if lo_w > body * 2.1 and up_w < rng * 0.25 and body > 0:
            markers.append({"time": c["time"], "position": "belowBar", "color": "#10b981", "shape": "arrowUp", "text": "Pin+"})
        elif up_w > body * 2.1 and lo_w < rng * 0.25 and body > 0:
            markers.append({"time": c["time"], "position": "aboveBar", "color": "#ef4444", "shape": "arrowDown", "text": "Pin-"})
        elif c["close"] > c["open"] and p["close"] < p["open"] and c["close"] > p["open"] and c["open"] <= p["close"]:
            markers.append({"time": c["time"], "position": "belowBar", "color": "#22c55e", "shape": "arrowUp", "text": "Eng+"})
        elif c["close"] < c["open"] and p["close"] > p["open"] and c["close"] < p["open"] and c["open"] >= p["close"]:
            markers.append({"time": c["time"], "position": "aboveBar", "color": "#f43f5e", "shape": "arrowDown", "text": "Eng-"})

    markers.sort(key=lambda m: m["time"])
    major_sup = round(support_levels[-1], 6) if support_levels else round(min(x["low"] for x in candles[-30:]), 6)
    major_res = round(resistance_levels[-1], 6) if resistance_levels else round(max(x["high"] for x in candles[-30:]), 6)
    return markers[-35:], major_sup, major_res

def analyze_full(symbol: str, market: str, item: Dict[str, Any], candles: List[Dict[str, Any]]):
    n = len(candles)
    closes = [c["close"] for c in candles]
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]
    price = closes[-1]

    rets = [abs(closes[i] - closes[i - 1]) / closes[i - 1] for i in range(1, len(closes)) if closes[i - 1] > 0]
    daily_vol = max(min((sum(rets[-20:]) / len(rets[-20:])) if rets else 0.02, 0.08), 0.01)

    rsi_s = calc_rsi(closes, 14)
    rsi_now = rsi_s[-1]
    ema12, ema26 = calc_ema(closes, 12), calc_ema(closes, 26)
    ema20 = [round(x, 6) for x in calc_ema(closes, 20)]
    ema50 = [round(x, 6) for x in calc_ema(closes, 50)]
    bb_up, bb_lo = calc_bollinger(closes, 20, 2.0)

    macd_l = [round(a - b, 6) for a, b in zip(ema12, ema26)]
    sig_l = [round(x, 6) for x in calc_ema(macd_l, 9)]
    hist_l = [round(m - s, 6) for m, s in zip(macd_l, sig_l)]

    sh, sl = max(highs[-120:]), min(lows[-120:])
    diff = sh - sl
    fib = {
        "0.0 (سقف)": round(sh, 6), "0.236": round(sh - 0.236 * diff, 6),
        "0.382": round(sh - 0.382 * diff, 6), "0.500": round(sh - 0.500 * diff, 6),
        "0.618 (طلایی)": round(sh - 0.618 * diff, 6), "1.0 (کف)": round(sl, 6),
    }

    pa_markers, pa_sup, pa_res = detect_price_action(candles)
    structure = "روند صعودی (بالای EMA20 و EMA50)" if price > ema20[-1] > ema50[-1] else ("روند نزولی (زیر EMA20 و EMA50)" if price < ema20[-1] < ema50[-1] else "فاز رنج / تغییر روند")

    fee_pct = 1.25 if market == "BOURSE" else 0.20
    contracts = {}
    for hk, spec in HORIZON_SPECS.items():
        if n < spec["min_bars"] or price <= 0:
            contracts[hk] = {
                "horizon": hk, "label": spec["label"], "evaluatable": False,
                "available_bars": n, "required_min_bars": spec["min_bars"],
                "action": "قابل ارزیابی نیست (کمبود تاریخچه)",
                "target": None, "stop": None, "net_return_pct": None, "net_risk_pct": None, "rr": None
            }
        else:
            tp_pct = min(daily_vol * spec["vol_scale"] * 1.45, 0.65)
            sl_pct = min(daily_vol * spec["vol_scale"] * 0.72, 0.28)
            tp, sl_v = round(price * (1.0 + tp_pct), 6), round(price * (1.0 - sl_pct), 6)
            net_ret = round(tp_pct * 100.0 - fee_pct, 2)
            net_rsk = round(sl_pct * 100.0 + fee_pct, 2)
            rr = round(net_ret / net_rsk, 2) if net_rsk > 0 else 0.0

            if rsi_now >= 75:
                act = "سیو سود / انتظار اصلاح (اشباع خرید)"
            elif rsi_now <= 32 and price <= fib["0.500"]:
                act = "پیشنهاد خرید پله‌ای روی حمایت"
            elif macd_l[-1] > sig_l[-1] and price > ema20[-1] and rr >= 1.5:
                act = "پیشنهاد خرید / نگهداری صعودی"
            elif price < ema20[-1] and macd_l[-1] < sig_l[-1]:
                act = "پیشنهاد فروش / دوری از معامله"
            else:
                act = "نوسان‌گیری بین حمایت و مقاومت"

            contracts[hk] = {
                "horizon": hk, "label": spec["label"], "evaluatable": True,
                "available_bars": n, "required_min_bars": spec["min_bars"],
                "action": act, "target": tp, "stop": sl_v,
                "net_return_pct": net_ret, "net_risk_pct": net_rsk, "rr": rr
            }

    if rsi_now >= 70:
        mood, advice = f"طمع شدید (RSI={rsi_now})", "خرید روی قله پرریسک است؛ منتظر اصلاح یا پولبک بمانید."
    elif rsi_now <= 32:
        mood, advice = f"ترس شدید (RSI={rsi_now})", "فروش هیجانی در کف؛ فقط با تایید کندل پین‌بار/اینگالف سبز ورود پله‌ای انجام دهید."
    else:
        mood, advice = f"تعادل روانی (RSI={rsi_now})", "بازار متعادل است؛ بر اساس خطوط حمایت و مقاومت چارت تصمیم بگیرید."

    pe, eps = float(item.get("pe") or 0), float(item.get("eps") or 0)
    if market == "BOURSE":
        fund = f"P/E={pe or 'نامشخص'} | EPS={eps or 'نامشخص'} | وضعیت: {'ارزنده' if (eps > 0 and 0 < pe < 8) else ('زیان‌ده' if eps < 0 else 'نیازمند بررسی کدال')}"
    else:
        qv = float(item.get("quote_vol") or 0)
        fund = f"حجم ۲۴ ساعته: {round(qv/1e6, 2)} میلیون دلار | نقدشوندگی: {'عالی' if qv > 1e7 else 'متوسط'}"

    strategies = {
        "past": f"گذشته: نوسان بین کف {fib['1.0 (کف)']} و سقف {fib['0.0 (سقف)']}؛ بهترین ورودها روی تراز ۰.۶۱۸ ({fib['0.618 (طلایی)']}) بوده است.",
        "present": f"حال: {structure}. حمایت پرایس اکشن: {pa_sup} | مقاومت پرایس اکشن: {pa_res}.",
        "future": f"آینده: شکست پرقدرت بالای {pa_res} موج صعودی جدید می‌سازد؛ از دست رفتن حمایت {pa_sup} هشدار خروج است."
    }

    # خروجی سری‌های کامل برای رسم روی Lightweight Charts
    chart_payload = {
        "candles": [{"time": c["time"], "open": c["open"], "high": c["high"], "low": c["low"], "close": c["close"]} for c in candles],
        "volume": [{"time": c["time"], "value": c["vol"], "color": "rgba(16,185,129,0.35)" if c["close"] >= c["open"] else "rgba(239,68,68,0.35)"} for c in candles],
        "ema20": [{"time": candles[i]["time"], "value": ema20[i]} for i in range(n)],
        "ema50": [{"time": candles[i]["time"], "value": ema50[i]} for i in range(n)],
        "bb_upper": [{"time": candles[i]["time"], "value": bb_up[i]} for i in range(n)],
        "bb_lower": [{"time": candles[i]["time"], "value": bb_lo[i]} for i in range(n)],
        "rsi": [{"time": candles[i]["time"], "value": rsi_s[i]} for i in range(n)],
        "macd": [{"time": candles[i]["time"], "value": macd_l[i]} for i in range(n)],
        "macd_signal": [{"time": candles[i]["time"], "value": sig_l[i]} for i in range(n)],
        "macd_hist": [{"time": candles[i]["time"], "value": hist_l[i], "color": "#10b981" if hist_l[i] >= 0 else "#ef4444"} for i in range(n)],
        "pa_markers": pa_markers,
        "pa_support": pa_sup,
        "pa_resistance": pa_res,
        "fib": fib,
        "rsi_now": rsi_now,
        "structure": structure,
    }

    return {
        "price": price,
        "chart": chart_payload,
        "fundamental": fund,
        "psychology": {"mood": mood, "advice": advice},
        "strategies": strategies,
        "contracts": contracts,
    }

@app.get("/api/system-status")
async def system_status(brs_key: str = ""):
    c_data, b_data = await asyncio.gather(load_all_crypto(), load_all_bourse(brs_key))
    return {
        "timestamp_tehran": datetime.now(TEHRAN_TZ).strftime("%Y-%m-%d %H:%M"),
        "crypto_count": len(c_data["items"]), "crypto_source": c_data["source"],
        "bourse_count": len(b_data["items"]), "bourse_source": b_data["source"],
    }

@app.get("/api/search")
async def instant_search(q: str = "", brs_key: str = ""):
    q_norm = norm_fa(q)
    c_data, b_data = await asyncio.gather(load_all_crypto(), load_all_bourse(brs_key))
    results = []
    for it in b_data["items"]:
        if not q_norm or q_norm in it["search_key"]:
            results.append({"symbol": it["symbol"], "name": it["name"], "market": "BOURSE", "today": it["today"], "unit": "تومان"})
            if len(results) >= 15:
                break
    for it in c_data["items"]:
        if not q_norm or q_norm in it["search_key"]:
            results.append({"symbol": it["symbol"], "name": it["name"], "market": "CRYPTO", "today": it["today"], "unit": "دلار"})
            if len(results) >= 30:
                break
    return {"query": q, "results": results}

@app.get("/api/analyze")
async def analyze_endpoint(symbol: str, market: str = "AUTO", brs_key: str = ""):
    t0 = time.time()
    q_norm = norm_fa(symbol)
    mkt_u = market.strip().upper()
    c_data, b_data = await asyncio.gather(load_all_crypto(), load_all_bourse(brs_key))

    item = None
    if mkt_u in ("AUTO", "BOURSE"):
        item = next((x for x in b_data["items"] if norm_fa(x["symbol"]) == q_norm), None)
        if item:
            mkt_u = "BOURSE"
    if not item and mkt_u in ("AUTO", "CRYPTO"):
        item = next((x for x in c_data["items"] if norm_fa(x["symbol"]) == q_norm or q_norm in x["search_key"]), None)
        if item:
            mkt_u = "CRYPTO"
    if not item:
        item = next((x for x in b_data["items"] if q_norm in x["search_key"]), None)
        if item:
            mkt_u = "BOURSE"

    if not item:
        return {"found": False, "symbol": symbol, "bourse_source": b_data["source"], "elapsed_ms": round((time.time() - t0) * 1000, 1)}

    c_res = await fetch_180_candles(item["symbol"], mkt_u, item, brs_key)
    if not c_res["candles"]:
        return {"found": True, "no_candles": True, "symbol": item["symbol"], "market": mkt_u,
                "candle_source": c_res["source"], "elapsed_ms": round((time.time() - t0) * 1000, 1)}

    full = analyze_full(item["symbol"], mkt_u, item, c_res["candles"])
    return {
        "found": True, "no_candles": False, "symbol": item["symbol"], "display_name": item["name"],
        "market": mkt_u, "unit": item["unit"], "candle_source": c_res["source"],
        "bars_count": len(c_res["candles"]), "elapsed_ms": round((time.time() - t0) * 1000, 1), **full
    }

@app.get("/api/top5-scanner")
async def top5_scanner():
    c_data = await load_all_crypto()
    candidates = [x for x in c_data["items"] if x["today"] > 0][:14]
    candle_results = await asyncio.gather(*[fetch_180_candles(x["symbol"], "CRYPTO", x) for x in candidates])
    analyzed = [(it, analyze_full(it["symbol"], "CRYPTO", it, cr["candles"])) for it, cr in zip(candidates, candle_results) if len(cr["candles"]) >= 10]
    top5 = {}
    for hk in HORIZON_SPECS:
        valid = [(it, a["contracts"][hk]) for it, a in analyzed if a["contracts"][hk]["evaluatable"] and ("خرید" in a["contracts"][hk]["action"] or "نگهداری" in a["contracts"][hk]["action"])]
        valid.sort(key=lambda z: z[1]["net_return_pct"] or 0, reverse=True)
        top5[hk] = [{"symbol": it["symbol"], "name": it["name"], "net_return_pct": c["net_return_pct"], "rr": c["rr"]} for it, c in valid[:5]]
    return top5

@app.get("/api/watchlists")
async def watchlists(brs_key: str = ""):
    c_data, b_data = await asyncio.gather(load_all_crypto(), load_all_bourse(brs_key))
    return {
        "bourse": enrich_comparison(b_data["items"][:15]),
        "crypto": enrich_comparison(c_data["items"][:15]),
        "metals": enrich_comparison(STATIC_OTHER["metals"]),
        "etfs": enrich_comparison(STATIC_OTHER["etfs"]),
        "forex": enrich_comparison(STATIC_OTHER["forex"]),
    }

class PortfolioIn(BaseModel):
    symbol: str
    market: str = "CRYPTO"
    quantity: float
    avg_buy_price_toman: float

@app.post("/api/portfolio")
def add_pf(item: PortfolioIn):
    conn = get_conn()
    conn.execute("INSERT INTO portfolio (symbol, market, quantity, avg_buy_price_toman, created_at) VALUES (?, ?, ?, ?, ?)",
                 (item.symbol.strip(), item.market.upper(), item.quantity, item.avg_buy_price_toman, datetime.now(TEHRAN_TZ).isoformat()))
    conn.commit()
    conn.close()
    return {"ok": True}

@app.delete("/api/portfolio/{pid}")
def del_pf(pid: int):
    conn = get_conn()
    conn.execute("DELETE FROM portfolio WHERE id = ?", (pid,))
    conn.commit()
    conn.close()
    return {"ok": True}

@app.get("/api/portfolio")
async def get_pf(brs_key: str = ""):
    c_data, b_data = await asyncio.gather(load_all_crypto(), load_all_bourse(brs_key))
    usd = 70200.0
    conn = get_conn()
    rows = conn.execute("SELECT id, symbol, market, quantity, avg_buy_price_toman FROM portfolio").fetchall()
    conn.close()
    out = []
    for pid, sym, mkt, qty, buy_p in rows:
        pool = b_data["items"] if mkt == "BOURSE" else c_data["items"]
        m = next((x for x in pool if norm_fa(x["symbol"]) == norm_fa(sym)), None)
        cur_p = (float(m["today"]) * (usd if mkt == "CRYPTO" else 1.0)) if m else buy_p
        pnl = ((cur_p - buy_p) / buy_p * 100.0) if buy_p > 0 else 0.0
        sig = "فروش (حد ضرر)" if pnl <= -6 else ("سیو سود" if pnl >= 15 else "نگهداری / پایش")
        out.append({"id": pid, "symbol": sym, "market": mkt, "quantity": qty, "buy_price": buy_p, "current_price": round(cur_p, 2), "pnl_pct": round(pnl, 2), "signal": sig})
    return out

@app.get("/", response_class=HTMLResponse)
def home():
    with open(os.path.join(BASE_DIR, "index.html"), "r", encoding="utf-8") as f:
        return f.read()

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
