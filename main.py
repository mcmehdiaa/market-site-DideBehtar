import os
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

# هدر رسمی مورد تایید فایروال BrsApi (بدون Referer اشتباه)
BRSAPI_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 6.1; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 OPR/106.0.0.0",
    "Accept": "application/json, text/plain, */*",
}

app = FastAPI(title="تحلیل کل بورس (۷۰۰+ نماد) و کل کریپتو (فارسی و انگلیسی)")

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
                    rows = _unwrap_list(r.json())
                    for x in rows:
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
            url = f"https://cdn.tsetmc.com/api/ClosingPrice/GetMarketWatch?market=0&{pt}&showTraded=false&withBestLimits=false&hEven=0&RefID=0"
            r = await client.get(url)
            diag.append(f"TSETMC_MW:{r.status_code}")
            if r.status_code == 200:
                rows = r.json().get("marketwatch") or []
                for x in rows:
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
            diag.append(f"TSETMC_MW_ERR:{type(e).__name__}")

        try:
            r3 = await client.get("https://webgw.tse.ir/InstrumentProvider/api/v1/Instrument/GetMarketWatch")
            diag.append(f"WEBGW:{r3.status_code}")
            if r3.status_code == 200:
                rows = _unwrap_list(r3.json())
                for x in rows:
                    sym = str(x.get("lVal18AFC") or x.get("symbol") or "").strip()
                    t_rial = _f(x.get("pClosing") or x.get("lastPrice"))
                    y_rial = _f(x.get("priceYesterday")) or t_rial
                    if sym and t_rial > 0:
                        nm = str(x.get("lVal30") or sym).strip()
                        items.append({
                            "symbol": sym, "name": nm, "search_key": norm_fa(f"{sym} {nm}"),
                            "market": "BOURSE", "ins_code": str(x.get("insCode") or x.get("InsCode") or x.get("instrumentCode") or ""),
                            "today": round(t_rial / 10.0, 2), "yesterday": round(y_rial / 10.0, 2),
                            "unit": "تومان", "pe": 0, "eps": 0, "tvol": _f(x.get("qTotTran5J"))
                        })
                if len(items) > 50:
                    BOURSE_CACHE.update({"ts": now, "items": items, "source": f"LIVE_WEBGW ({len(items)} نماد)", "key_used": brs_key})
                    return BOURSE_CACHE
        except Exception as e:
            diag.append(f"WEBGW_ERR:{type(e).__name__}")

    BOURSE_CACHE.update({"ts": now, "items": items, "source": " | ".join(diag), "key_used": brs_key})
    return BOURSE_CACHE

async def fetch_180_candles(symbol: str, market: str, item: Dict[str, Any], brs_key_override: str = "") -> Dict[str, Any]:
    brs_key = (brs_key_override or os.getenv("BRSAPI_KEY", "")).strip()
    ckey = f"{market}:{norm_fa(symbol)}:{brs_key[:6]}"
    now = time.time()
    if ckey in CANDLE_CACHE and (now - CANDLE_CACHE[ckey]["ts"] < 300):
        return CANDLE_CACHE[ckey]

    candles = []
    diag = []

    if market == "CRYPTO":
        async with httpx.AsyncClient(timeout=4.5) as client:
            try:
                r = await client.get(f"https://data-api.binance.vision/api/v3/klines?symbol={symbol.upper()}USDT&interval=1d&limit=180")
                if r.status_code == 200 and isinstance(r.json(), list):
                    for k in r.json():
                        candles.append({
                            "date": datetime.fromtimestamp(k[0] / 1000, tz=TEHRAN_TZ).strftime("%m-%d"),
                            "open": float(k[1]), "high": float(k[2]), "low": float(k[3]), "close": float(k[4]), "vol": float(k[5])
                        })
                    if candles:
                        res = {"ts": now, "source": "LIVE_BINANCE_1D", "candles": candles}
                        CANDLE_CACHE[ckey] = res
                        return res
                diag.append(f"BINANCE:{r.status_code}")
            except Exception as e:
                diag.append(f"BINANCE_ERR:{type(e).__name__}")

            try:
                r2 = await client.get(f"https://api.kucoin.com/api/v1/market/candles?symbol={symbol.upper()}-USDT&type=1day")
                if r2.status_code == 200:
                    raw = (r2.json().get("data") or [])
                    for k in reversed(raw[:180]):
                        candles.append({
                            "date": datetime.fromtimestamp(int(k[0]), tz=TEHRAN_TZ).strftime("%m-%d"),
                            "open": float(k[1]), "close": float(k[2]), "high": float(k[3]), "low": float(k[4]), "vol": float(k[5])
                        })
                    if candles:
                        res = {"ts": now, "source": "LIVE_KUCOIN_1D", "candles": candles}
                        CANDLE_CACHE[ckey] = res
                        return res
                diag.append(f"KUCOIN:{r2.status_code}")
            except Exception as e:
                diag.append(f"KUCOIN_ERR:{type(e).__name__}")

    elif market == "BOURSE":
        # ۱) تلاش از طریق Api.BrsApi.ir با پارامتر استاندارد و پارس کامل JSON
        if brs_key:
            try:
                async with httpx.AsyncClient(timeout=7.0, headers=BRSAPI_HEADERS) as client:
                    rh = await client.get("https://Api.BrsApi.ir/Tsetmc/History.php", params={"key": brs_key, "type": "0", "l18": symbol})
                    diag.append(f"BRS_HIST:{rh.status_code}")
                    if rh.status_code == 200:
                        rows = _unwrap_list(rh.json())
                        if len(rows) >= 2:
                            d0 = str(rows[0].get("date") or rows[0].get("dEven") or "")
                            d1 = str(rows[-1].get("date") or rows[-1].get("dEven") or "")
                            if d0 > d1:
                                rows = list(reversed(rows))
                        for row in rows[-180:]:
                            c = _f(row.get("pc") or row.get("pl") or row.get("pClosing") or row.get("close")) / 10.0
                            if c > 0:
                                o = (_f(row.get("pf") or row.get("priceFirst") or row.get("open")) / 10.0) or c
                                h = (_f(row.get("pmax") or row.get("priceMax") or row.get("high")) / 10.0) or c
                                l = (_f(row.get("pmin") or row.get("priceMin") or row.get("low")) / 10.0) or c
                                candles.append({"date": str(row.get("date") or row.get("dEven") or ""), "open": o, "high": h, "low": l, "close": c, "vol": _f(row.get("tvol") or row.get("volume"))})
                        if candles:
                            res = {"ts": now, "source": "LIVE_BRSAPI_1D", "candles": candles}
                            CANDLE_CACHE[ckey] = res
                            return res
                        diag.append("BRS_HIST:EMPTY_LIST")
            except Exception as e:
                diag.append(f"BRS_HIST_ERR:{type(e).__name__}")
        else:
            diag.append("BRS_KEY:EMPTY")

        # ۲) تلاش مستقیم از TSETMC (Search -> GetChartData & GetClosingPriceDailyList)
        async with httpx.AsyncClient(timeout=5.0, headers=TSETMC_HEADERS) as client:
            ins_code = item.get("ins_code")
            if not ins_code:
                try:
                    rs = await client.get(f"https://cdn.tsetmc.com/api/Instrument/GetInstrumentSearch/{symbol}")
                    diag.append(f"TSE_SEARCH:{rs.status_code}")
                    if rs.status_code == 200:
                        hits = rs.json().get("instrumentSearch") or []
                        exact = next((h for h in hits if norm_fa(h.get("lVal18AFC")) == norm_fa(symbol)), hits[0] if hits else None)
                        if exact:
                            ins_code = str(exact.get("insCode"))
                except Exception as e:
                    diag.append(f"TSE_SEARCH_ERR:{type(e).__name__}")

            if ins_code:
                try:
                    rc = await client.get(f"https://cdn.tsetmc.com/api/ClosingPrice/GetChartData/{ins_code}/D")
                    diag.append(f"TSE_CHART:{rc.status_code}")
                    if rc.status_code == 200:
                        rows = rc.json().get("closingPriceChartData") or []
                        for row in rows[-180:]:
                            c = _f(row.get("pClosing")) / 10.0
                            if c > 0:
                                o = (_f(row.get("priceFirst")) / 10.0) or c
                                h = (_f(row.get("priceMax")) / 10.0) or c
                                l = (_f(row.get("priceMin")) / 10.0) or c
                                d_str = str(row.get("dEven") or "")
                                candles.append({"date": f"{d_str[4:6]}-{d_str[6:8]}" if len(d_str) == 8 else d_str, "open": o, "high": h, "low": l, "close": c, "vol": _f(row.get("qTotTran5J"))})
                        if candles:
                            res = {"ts": now, "source": "LIVE_TSETMC_CHART_1D", "candles": candles}
                            CANDLE_CACHE[ckey] = res
                            return res
                except Exception as e:
                    diag.append(f"TSE_CHART_ERR:{type(e).__name__}")

                try:
                    rh = await client.get(f"https://cdn.tsetmc.com/api/ClosingPrice/GetClosingPriceDailyList/{ins_code}/180")
                    diag.append(f"TSE_DAILY:{rh.status_code}")
                    if rh.status_code == 200:
                        rows = rh.json().get("closingPriceDaily") or []
                        for row in reversed(rows):
                            c = _f(row.get("pClosing")) / 10.0
                            if c > 0:
                                o = (_f(row.get("priceFirst")) / 10.0) or c
                                h = (_f(row.get("priceMax")) / 10.0) or c
                                l = (_f(row.get("priceMin")) / 10.0) or c
                                d_str = str(row.get("dEven") or "")
                                candles.append({"date": f"{d_str[4:6]}-{d_str[6:8]}" if len(d_str) == 8 else d_str, "open": o, "high": h, "low": l, "close": c, "vol": _f(row.get("qTotTran5J"))})
                        if candles:
                            res = {"ts": now, "source": "LIVE_TSETMC_DAILY_1D", "candles": candles}
                            CANDLE_CACHE[ckey] = res
                            return res
                except Exception as e:
                    diag.append(f"TSE_DAILY_ERR:{type(e).__name__}")

    return {"ts": now, "source": " | ".join(diag) or "NO_DATA", "candles": []}

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

def analyze_full(symbol: str, market: str, item: Dict[str, Any], candles: List[Dict[str, Any]]):
    n = len(candles)
    closes = [c["close"] for c in candles]
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]
    price = closes[-1] if closes else float(item.get("today") or 0)

    rets = [abs(closes[i] - closes[i - 1]) / closes[i - 1] for i in range(1, len(closes)) if closes[i - 1] > 0]
    daily_vol = max(min((sum(rets[-20:]) / len(rets[-20:])) if rets else 0.02, 0.08), 0.01)

    rsi_s = calc_rsi(closes, 14) if n >= 2 else [50.0]
    rsi_now = rsi_s[-1]
    ema12 = calc_ema(closes, 12) if n >= 2 else [price]
    ema26 = calc_ema(closes, 26) if n >= 2 else [price]
    macd_l = [round(a - b, 6) for a, b in zip(ema12, ema26)]
    sig_l = [round(x, 6) for x in calc_ema(macd_l, 9)]
    hist_l = [round(m - s, 6) for m, s in zip(macd_l, sig_l)]

    sh, sl = (max(highs[-120:]) if highs else price), (min(lows[-120:]) if lows else price)
    diff = sh - sl
    fib = {
        "0.0": round(sh, 6), "0.236": round(sh - 0.236 * diff, 6),
        "0.382": round(sh - 0.382 * diff, 6), "0.500": round(sh - 0.500 * diff, 6),
        "0.618": round(sh - 0.618 * diff, 6), "1.0": round(sl, 6),
    }

    sma20 = sum(closes[-20:]) / len(closes[-20:]) if closes else price
    sma50 = sum(closes[-50:]) / len(closes[-50:]) if closes else price
    if price > sma20 > sma50:
        structure = "روند صعودی قدرتمند (بالای میانگین ۲۰ و ۵۰ روزه)"
    elif price < sma20 < sma50:
        structure = "روند نزولی (زیر میانگین‌ها)"
    else:
        structure = "رنج / نوسانی در محدوده تغییر روند"

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
            elif macd_l[-1] > sig_l[-1] and price > sma20 and rr >= 1.5:
                act = "پیشنهاد خرید / نگهداری صعودی"
            elif price < sma20 and macd_l[-1] < sig_l[-1]:
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
        mood, advice = f"طمع شدید (RSI={rsi_now})", "جو خرید هیجانی؛ خرید روی قله پرریسک است، منتظر پولبک بمانید."
    elif rsi_now <= 32:
        mood, advice = f"ترس شدید (RSI={rsi_now})", "فروش هیجانی در کف؛ ورود پله‌ای فقط با تایید کندل سبز و حد ضرر."
    else:
        mood, advice = f"تعادل روانی (RSI={rsi_now})", "بازار متعادل است؛ مطابق حد سود و حد ضرر تصمیم بگیرید."

    pe, eps = float(item.get("pe") or 0), float(item.get("eps") or 0)
    if market == "BOURSE":
        fund = f"P/E={pe or 'نامشخص'} | EPS={eps or 'نامشخص'} | وضعیت: {'ارزنده' if (eps > 0 and 0 < pe < 8) else ('زیان‌ده' if eps < 0 else 'بررسی گزارش کدال')}"
    else:
        qv = float(item.get("quote_vol") or 0)
        fund = f"حجم معاملات ۲۴ ساعته: {round(qv/1e6, 2)} میلیون دلار | نقدشوندگی: {'عالی' if qv > 1e7 else 'متوسط'}"

    strategies = {
        "past": f"گذشته: نوسان بین کف {fib['1.0']} و سقف {fib['0.0']}؛ بهترین خریدها نزدیک ۰.۶۱۸ ({fib['0.618']}) بوده است.",
        "present": f"حال: قیمت {price} ({structure}). حمایت کلیدی {fib['0.618']} و مقاومت {fib['0.236']}.",
        "future": f"آینده: عبور قطعی از {fib['0.236']} هدف {fib['0.0']} را باز می‌کند؛ شکست {fib['0.618']} نیاز به خروج فوری دارد."
    }

    return {
        "price": price,
        "technical": {
            "dates": [c["date"] for c in candles[-60:]], "closes": closes[-60:],
            "rsi_now": rsi_now, "rsi_series": rsi_s[-60:],
            "macd_series": macd_l[-60:], "signal_series": sig_l[-60:], "hist_series": hist_l[-60:],
            "fib": fib, "structure": structure,
        },
        "fundamental": fund, "psychology": {"mood": mood, "advice": advice},
        "strategies": strategies, "contracts": contracts,
    }

@app.get("/api/system-status")
async def system_status(brs_key: str = ""):
    c_data, b_data = await asyncio.gather(load_all_crypto(), load_all_bourse(brs_key))
    return {
        "timestamp_tehran": datetime.now(TEHRAN_TZ).strftime("%Y-%m-%d %H:%M"),
        "crypto_count": len(c_data["items"]), "crypto_source": c_data["source"],
        "bourse_count": len(b_data["items"]), "bourse_source": b_data["source"],
    }

@app.get("/api/debug-bourse")
async def debug_bourse(symbol: str = "فولاد", brs_key: str = ""):
    b_data = await load_all_bourse(brs_key, force=True)
    item = next((x for x in b_data["items"] if norm_fa(x["symbol"]) == norm_fa(symbol)), {})
    c_res = await fetch_180_candles(symbol, "BOURSE", item, brs_key)
    return {
        "bourse_count": len(b_data["items"]), "bourse_source": b_data["source"],
        "symbol_found": bool(item), "ins_code": item.get("ins_code"),
        "candle_source": c_res["source"], "candles_count": len(c_res["candles"])
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

    analyzed = []
    for item, cres in zip(candidates, candle_results):
        if len(cres["candles"]) >= 10:
            analyzed.append((item, analyze_full(item["symbol"], "CRYPTO", item, cres["candles"])))

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
