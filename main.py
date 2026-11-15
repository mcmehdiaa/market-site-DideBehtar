import os
import math
import time
import asyncio
import sqlite3
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional, Tuple

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

app = FastAPI(title="نسخه اصلاح‌شده - باطن دقیق و تست‌پذیر")

def norm_fa(text: str) -> str:
    if not text:
        return ""
    return (
        str(text).strip().upper()
        .replace("ي", "ی").replace("ك", "ک").replace("ة", "ه")
        .replace("\u200c", "").replace("‌", "").replace(" ", "").replace("-", "")
    )

def _f(v) -> Optional[float]:
    try:
        if v is None or str(v).strip() == "":
            return None
        return float(str(v).replace(",", "").strip())
    except Exception:
        return None

def _unwrap_list(payload) -> list:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for k in ("data", "Data", "history", "History", "items", "result", "Result", "symbols"):
            if isinstance(payload.get(k), list):
                return payload[k]
    return []

# تبدیل دقیق تاریخ شمسی به میلادی (بدون جعل تاریخ)
def jalali_to_gregorian(jy: int, jm: int, jd: int) -> Tuple[int, int, int]:
    jy += 1595
    days = -355668 + (365 * jy) + ((jy // 33) * 8) + (((jy % 33) + 3) // 4) + jd
    days += ((jm - 1) * 31) if jm < 7 else (((jm - 7) * 30) + 186)
    gy = 400 * (days // 146097)
    days %= 146097
    if days > 36524:
        days -= 1
        gy += 100 * (days // 36524)
        days %= 36524
        if days >= 365:
            days += 1
    gy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        gy += (days - 1) // 365
        days = (days - 1) % 365
    gd = days + 1
    is_leap = (gy % 4 == 0 and gy % 100 != 0) or (gy % 400 == 0)
    sal_a = [0, 31, 29 if is_leap else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    gm = 0
    while gm < 13 and gd > sal_a[gm]:
        gd -= sal_a[gm]
        gm += 1
    return gy, gm, gd

def parse_candle_timestamp(raw_date) -> Optional[int]:
    """تبدیل تاریخ واقعی (میلادی یا شمسی) به تایم‌استمپ دقیق. در نبود تاریخ معتبر None برمی‌گرداند."""
    if raw_date is None:
        return None
    s = str(raw_date).strip()
    if not s:
        return None
    # فرمت عددی میلادی YYYYMMDD مثل 20261115
    if len(s) == 8 and s.isdigit():
        y = int(s[:4])
        if 1990 <= y <= 2100:
            return int(datetime(y, int(s[4:6]), int(s[6:8]), 12, 0, tzinfo=TEHRAN_TZ).timestamp())
        if 1350 <= y <= 1500:
            gy, gm, gd = jalali_to_gregorian(y, int(s[4:6]), int(s[6:8]))
            return int(datetime(gy, gm, gd, 12, 0, tzinfo=TEHRAN_TZ).timestamp())
    # فرمت YYYY-MM-DD یا YYYY/MM/DD
    clean = s[:10].replace("/", "-")
    parts = clean.split("-")
    if len(parts) == 3 and all(p.isdigit() for p in parts):
        y, m, d = int(parts[0]), int(parts[1]), int(parts[2])
        if 1990 <= y <= 2100:
            return int(datetime(y, m, d, 12, 0, tzinfo=TEHRAN_TZ).timestamp())
        if 1350 <= y <= 1500:
            gy, gm, gd = jalali_to_gregorian(y, m, d)
            return int(datetime(gy, gm, gd, 12, 0, tzinfo=TEHRAN_TZ).timestamp())
    return None

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
    "H1_DAILY":   {"label": "۱) روزانه",   "min_bars": 15,  "vol_scale": 1.4},
    "H2_WEEKLY":  {"label": "۲) هفتگی",    "min_bars": 25,  "vol_scale": 3.2},
    "H3_MONTHLY": {"label": "۳) ماهانه",   "min_bars": 45,  "vol_scale": 6.5},
    "H4_120D":    {"label": "۴) ۱۲۰ روزه", "min_bars": 120, "vol_scale": 12.0},
}

CRYPTO_CACHE: Dict[str, Any] = {"ts": 0, "items": [], "source": "NOT_LOADED"}
BOURSE_CACHE: Dict[str, Any] = {"ts": 0, "items": [], "source": "NOT_LOADED", "key_used": ""}
MACRO_CACHE: Dict[str, Any] = {"ts": 0, "usdt_toman": None, "usdt_source": "NOT_LOADED", "fx_rates": {}, "fx_source": "NOT_LOADED", "fng": None}
CANDLE_CACHE: Dict[str, Dict[str, Any]] = {}

def enrich_comparison(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for it in items:
        t = _f(it.get("today"))
        y = _f(it.get("yesterday"))
        if t is None:
            out.append({**it, "diff": None, "change_pct": None})
            continue
        y_val = y if (y is not None and y > 0) else t
        pct = ((t - y_val) / y_val * 100.0) if y_val > 0 else 0.0
        out.append({**it, "diff": round(t - y_val, 6), "change_pct": round(pct, 2)})
    return out

# ==========================================
# ۱. دریافت داده‌های کلان واقعی (تتر زنده نوبیتکس، ارزهای جهانی، شاخص ترس و طمع)
# ==========================================
async def load_macro_live(force: bool = False):
    now = time.time()
    if not force and MACRO_CACHE["ts"] > 0 and (now - MACRO_CACHE["ts"] < 120):
        return MACRO_CACHE

    async with httpx.AsyncClient(timeout=4.5) as client:
        # الف) قیمت زنده تتر به تومان از نوبیتکس (بدون عدد ثابت ۷۰۲۰۰)
        try:
            r_nb = await client.get("https://api.nobitex.ir/market/stats?srcCurrency=usdt&dstCurrency=rls")
            if r_nb.status_code == 200:
                st = (r_nb.json().get("stats") or {}).get("usdt-rls") or {}
                last_r = _f(st.get("latest"))
                if last_r and last_r > 0:
                    MACRO_CACHE["usdt_toman"] = round(last_r / 10.0, 1)
                    MACRO_CACHE["usdt_source"] = "LIVE_NOBITEX"
        except Exception:
            pass

        # ب) نرخ زنده ارزهای جهانی نسبت به دلار
        try:
            r_fx = await client.get("https://open.er-api.com/v6/latest/USD")
            if r_fx.status_code == 200:
                rates = r_fx.json().get("rates") or {}
                if rates:
                    MACRO_CACHE["fx_rates"] = rates
                    MACRO_CACHE["fx_source"] = "LIVE_OPEN_ER_API"
        except Exception:
            pass

        # پ) شاخص زنده ترس و طمع بازار کریپتو (Alternative.me)
        try:
            r_fg = await client.get("https://api.alternative.me/fng/?limit=2")
            if r_fg.status_code == 200:
                d = r_fg.json().get("data") or []
                if d:
                    MACRO_CACHE["fng"] = {
                        "value": int(d[0]["value"]),
                        "label": d[0]["value_classification"],
                        "yesterday": int(d[1]["value"]) if len(d) > 1 else None
                    }
        except Exception:
            pass

    MACRO_CACHE["ts"] = now
    return MACRO_CACHE

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
                    last_p, prev_p, qvol = _f(row.get("lastPrice")), _f(row.get("prevClosePrice")), _f(row.get("quoteVolume")) or 0.0
                    if last_p and last_p > 0 and qvol > 20000:
                        fa = CRYPTO_FA_NAMES.get(base, "")
                        merged[base] = {
                            "symbol": base, "fa_name": fa, "name": f"{fa.split()[0] + ' - ' if fa else ''}{base}/USDT",
                            "search_key": norm_fa(f"{base} {fa}"), "market": "CRYPTO",
                            "today": last_p, "yesterday": prev_p if (prev_p and prev_p > 0) else last_p, "unit": "دلار", "quote_vol": qvol
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
                    last_p, chg_rate, qvol = _f(row.get("last")), _f(row.get("changeRate")) or 0.0, _f(row.get("volValue")) or 0.0
                    if last_p and last_p > 0 and base not in merged and qvol > 5000:
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

    items, diag = [], []
    if brs_key:
        try:
            async with httpx.AsyncClient(timeout=7.0, headers=BRSAPI_HEADERS) as client:
                r = await client.get("https://Api.BrsApi.ir/Tsetmc/AllSymbols.php", params={"key": brs_key, "type": "1"})
                diag.append(f"BRS_ALL:{r.status_code}")
                if r.status_code == 200:
                    for x in _unwrap_list(r.json()):
                        sym = str(x.get("l18") or "").strip()
                        t_rial = _f(x.get("pl")) or _f(x.get("pc"))
                        y_rial = _f(x.get("py")) or t_rial
                        if sym and t_rial and t_rial > 0:
                            nm = str(x.get("l30") or sym).strip()
                            items.append({
                                "symbol": sym, "name": nm, "search_key": norm_fa(f"{sym} {nm}"),
                                "market": "BOURSE", "ins_code": str(x.get("id") or x.get("insCode") or ""),
                                "cs": str(x.get("cs") or ""), "today": round(t_rial / 10.0, 2),
                                "yesterday": round((y_rial or t_rial) / 10.0, 2), "unit": "تومان",
                                "pe": _f(x.get("pe")), "eps": _f(x.get("eps")), "tvol": _f(x.get("tvol")) or 0.0
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
                    t_rial = _f(x.get("pClosing")) or _f(x.get("pDrCotVal"))
                    y_rial = _f(x.get("priceYesterday")) or t_rial
                    if sym and t_rial and t_rial > 0:
                        nm = str(x.get("lVal30") or sym).strip()
                        items.append({
                            "symbol": sym, "name": nm, "search_key": norm_fa(f"{sym} {nm}"),
                            "market": "BOURSE", "ins_code": str(x.get("insCode") or ""),
                            "cs": "", "today": round(t_rial / 10.0, 2),
                            "yesterday": round((y_rial or t_rial) / 10.0, 2), "unit": "تومان",
                            "pe": None, "eps": None, "tvol": _f(x.get("qTotTran5J")) or 0.0
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
        if c.get("time") and c["close"] > 0 and c["open"] > 0 and c["high"] >= c["low"]:
            by_time[int(c["time"])] = c
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
                        candles.append({"time": int(k[0] / 1000), "open": float(k[1]), "high": float(k[2]), "low": float(k[3]), "close": float(k[4]), "vol": float(k[5])})
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
                    for k in (r2.json().get("data") or [])[:180]:
                        candles.append({"time": int(k[0]), "open": float(k[1]), "close": float(k[2]), "high": float(k[3]), "low": float(k[4]), "vol": float(k[5])})
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
                        for row in _unwrap_list(rh.json()):
                            ts = parse_candle_timestamp(row.get("date_g") or row.get("dEven") or row.get("date") or row.get("d"))
                            c = _f(row.get("pc")) or _f(row.get("pl")) or _f(row.get("pClosing")) or _f(row.get("close"))
                            if ts and c and c > 0:
                                c_t = c / 10.0
                                o_t = (_f(row.get("pf")) or _f(row.get("priceFirst")) or _f(row.get("open")) or c) / 10.0
                                h_t = (_f(row.get("pmax")) or _f(row.get("priceMax")) or _f(row.get("high")) or c) / 10.0
                                l_t = (_f(row.get("pmin")) or _f(row.get("priceMin")) or _f(row.get("low")) or c) / 10.0
                                candles.append({"time": ts, "open": o_t, "high": max(h_t, o_t, c_t), "low": min(l_t, o_t, c_t), "close": c_t, "vol": _f(row.get("tvol")) or 0.0})
                        candles = _clean_sort_candles(candles)[-180:]
                        if candles:
                            res = {"ts": now, "source": "LIVE_BRSAPI_1D", "candles": candles}
                            CANDLE_CACHE[ckey] = res
                            return res
                        diag.append("BRS_HIST:NO_VALID_DATED_BARS")
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
                        for row in (rh.json().get("closingPriceDaily") or []):
                            ts = parse_candle_timestamp(row.get("dEven"))
                            c = _f(row.get("pClosing"))
                            if ts and c and c > 0:
                                c_t = c / 10.0
                                o_t = (_f(row.get("priceFirst")) or c) / 10.0
                                h_t = (_f(row.get("priceMax")) or c) / 10.0
                                l_t = (_f(row.get("priceMin")) or c) / 10.0
                                candles.append({"time": ts, "open": o_t, "high": max(h_t, o_t, c_t), "low": min(l_t, o_t, c_t), "close": c_t, "vol": _f(row.get("qTotTran5J")) or 0.0})
                        candles = _clean_sort_candles(candles)[-180:]
                        if candles:
                            res = {"ts": now, "source": "LIVE_TSETMC_1D", "candles": candles}
                            CANDLE_CACHE[ckey] = res
                            return res
                except Exception as e:
                    diag.append(f"TSE_ERR:{type(e).__name__}")

    return {"ts": now, "source": " | ".join(diag) or "NO_DATA", "candles": []}

# ==========================================
# اصلاح ریاضی ۱: فرمول دقیق Wilder's RMA RSI مطابق TradingView
# ==========================================
def calc_ema(vals: List[float], period: int) -> List[float]:
    k = 2.0 / (period + 1)
    out = [vals[0]]
    for v in vals[1:]:
        out.append(v * k + out[-1] * (1.0 - k))
    return out

def calc_wilder_rsi_points(candles: List[Dict[str, Any]], period: int = 14) -> List[Dict[str, Any]]:
    """
    محاسبه دقیق RSI با روش Wilder Smoothing (استاندارد تریدینگ‌ویو).
    خروجی فقط از کندل index >= period برگردانده می‌شود تا عدد جعلی در دوره warmup رسم نشود.
    """
    n = len(candles)
    if n <= period:
        return []
    closes = [c["close"] for c in candles]
    gains, losses = [], []
    for i in range(1, n):
        d = closes[i] - closes[i - 1]
        gains.append(max(d, 0.0))
        losses.append(max(-d, 0.0))

    avg_g = sum(gains[:period]) / period
    avg_l = sum(losses[:period]) / period

    def _to_rsi(ag, al):
        if al == 0.0:
            return 100.0 if ag > 0.0 else 50.0
        rs = ag / al
        return round(100.0 - (100.0 / (1.0 + rs)), 2)

    pts = [{"time": candles[period]["time"], "value": _to_rsi(avg_g, avg_l)}]
    for k in range(period, len(gains)):
        avg_g = (avg_g * (period - 1) + gains[k]) / period
        avg_l = (avg_l * (period - 1) + losses[k]) / period
        pts.append({"time": candles[k + 1]["time"], "value": _to_rsi(avg_g, avg_l)})
    return pts

def calc_bollinger(closes: List[float], period: int = 20, mult: float = 2.0):
    upper, lower = [], []
    for i in range(len(closes)):
        win = closes[max(0, i - period + 1):i + 1]
        mean = sum(win) / len(win)
        sd = math.sqrt(sum((x - mean) ** 2 for x in win) / len(win))
        upper.append(round(mean + mult * sd, 6))
        lower.append(round(mean - mult * sd, 6))
    return upper, lower

def detect_price_action(candles: List[Dict[str, Any]]):
    markers = []
    n = len(candles)
    last_ph, last_pl = None, None
    sup_lvls, res_lvls = [], []

    for i in range(2, n - 2):
        h, l = candles[i]["high"], candles[i]["low"]
        if h > candles[i-1]["high"] and h > candles[i-2]["high"] and h > candles[i+1]["high"] and h > candles[i+2]["high"]:
            lbl = "HH" if (last_ph is None or h > last_ph) else "LH"
            last_ph = h
            res_lvls.append(h)
            markers.append({"time": candles[i]["time"], "position": "aboveBar", "color": "#fbbf24", "shape": "circle", "text": lbl})
        if l < candles[i-1]["low"] and l < candles[i-2]["low"] and l < candles[i+1]["low"] and l < candles[i+2]["low"]:
            lbl = "HL" if (last_pl is None or l > last_pl) else "LL"
            last_pl = l
            sup_lvls.append(l)
            markers.append({"time": candles[i]["time"], "position": "belowBar", "color": "#38bdf8", "shape": "circle", "text": lbl})

    for i in range(1, n):
        c, p = candles[i], candles[i - 1]
        body = abs(c["close"] - c["open"])
        rng = max(c["high"] - c["low"], 1e-12)
        up_w, lo_w = c["high"] - max(c["open"], c["close"]), min(c["open"], c["close"]) - c["low"]
        if lo_w > body * 2.1 and up_w < rng * 0.25 and body > 0:
            markers.append({"time": c["time"], "position": "belowBar", "color": "#10b981", "shape": "arrowUp", "text": "Pin+"})
        elif up_w > body * 2.1 and lo_w < rng * 0.25 and body > 0:
            markers.append({"time": c["time"], "position": "aboveBar", "color": "#ef4444", "shape": "arrowDown", "text": "Pin-"})
        elif c["close"] > c["open"] and p["close"] < p["open"] and c["close"] > p["open"] and c["open"] <= p["close"]:
            markers.append({"time": c["time"], "position": "belowBar", "color": "#22c55e", "shape": "arrowUp", "text": "Eng+"})
        elif c["close"] < c["open"] and p["close"] > p["open"] and c["close"] < p["open"] and c["open"] >= p["close"]:
            markers.append({"time": c["time"], "position": "aboveBar", "color": "#f43f5e", "shape": "arrowDown", "text": "Eng-"})

    markers.sort(key=lambda m: m["time"])
    major_sup = round(sup_lvls[-1], 6) if sup_lvls else round(min(x["low"] for x in candles[-30:]), 6)
    major_res = round(res_lvls[-1], 6) if res_lvls else round(max(x["high"] for x in candles[-30:]), 6)
    return markers[-35:], major_sup, major_res

def analyze_full(symbol: str, market: str, item: Dict[str, Any], candles: List[Dict[str, Any]], fng_data: Optional[dict] = None):
    n = len(candles)
    closes = [c["close"] for c in candles]
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]
    vols = [c["vol"] for c in candles]
    price = closes[-1]

    rets = [abs(closes[i] - closes[i - 1]) / closes[i - 1] for i in range(1, n) if closes[i - 1] > 0]
    daily_vol = max(min((sum(rets[-20:]) / len(rets[-20:])) if rets else 0.02, 0.08), 0.01)

    rsi_pts = calc_wilder_rsi_points(candles, 14)
    rsi_now = rsi_pts[-1]["value"] if rsi_pts else None

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

    # ۴ بازه دقیق: روزانه تا ۱۲۰ روزه با رعایت قفل عدم جعل عدد در نبود دیتا
    fee_pct = 1.25 if market == "BOURSE" else 0.20
    contracts = {}
    for hk, spec in HORIZON_SPECS.items():
        if n < spec["min_bars"] or price <= 0 or rsi_now is None:
            contracts[hk] = {
                "horizon": hk, "label": spec["label"], "evaluatable": False,
                "available_bars": n, "required_min_bars": spec["min_bars"],
                "action": "قابل ارزیابی نیست (کمبود تاریخچه)",
                "target": None, "stop": None, "net_return_pct": None, "net_risk_pct": None, "rr": None
            }
        else:
            atr_tp = price * (1.0 + min(daily_vol * spec["vol_scale"] * 1.45, 0.65))
            atr_sl = price * (1.0 - min(daily_vol * spec["vol_scale"] * 0.72, 0.28))
            # لنگر زدن حد ضرر به حمایت واقعی پرایس اکشن در بازه‌های کوتاه/میان‌مدت
            if hk in ("H1_DAILY", "H2_WEEKLY") and 0 < pa_sup < price:
                sl_v = round(max(atr_sl, pa_sup * 0.992), 6)
            else:
                sl_v = round(atr_sl, 6)
            tp = round(atr_tp, 6)
            net_ret = round(((tp - price) / price * 100.0) - fee_pct, 2)
            net_rsk = round(((price - sl_v) / price * 100.0) + fee_pct, 2)
            rr = round(net_ret / net_rsk, 2) if net_rsk > 0 else 0.0

            if rsi_now >= 75:
                act = "سیو سود / انتظار اصلاح (اشباع خرید)"
            elif rsi_now <= 32 and price <= fib["0.500"]:
                act = "پیشنهاد خرید پله‌ای روی حمایت"
            elif macd_l[-1] > sig_l[-1] and price > ema20[-1] and rr >= 1.3:
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

    # روانشناسی چندعاملی (Wilder RSI + نسبت حجم + فاصله از EMA20 + شاخص ترس و طمع زنده)
    avg_vol20 = sum(vols[-21:-1]) / max(len(vols[-21:-1]), 1) if len(vols) > 2 else (vols[-1] or 1.0)
    vol_ratio = round(vols[-1] / avg_vol20, 2) if avg_vol20 > 0 else 1.0
    ext_pct = round(((price - ema20[-1]) / ema20[-1]) * 100.0, 2) if ema20[-1] > 0 else 0.0
    fng_txt = f" | شاخص کل ترس/طمع کریپتو: {fng_data['value']}/100 ({fng_data['label']})" if (market == "CRYPTO" and fng_data) else ""

    if rsi_now is not None and rsi_now >= 70 and vol_ratio >= 1.5:
        mood = f"اوج هیجان و طمع (RSI={rsi_now}، حجم {vol_ratio}x، فاصله از EMA20: +{ext_pct}%){fng_txt}"
        advice = "جهش حجم همراه با اشباع خرید نشانه فومو (FOMO) است؛ از تعقیب قیمت در سقف خودداری کنید."
    elif rsi_now is not None and rsi_now <= 32 and vol_ratio >= 1.4:
        mood = f"ترس شدید و تسلیم فروشندگان (RSI={rsi_now}، حجم {vol_ratio}x، فاصله: {ext_pct}%){fng_txt}"
        advice = "حجم بالا در کف قیمتی می‌تواند نشانه تخلیه فروش هیجانی باشد؛ فقط با تایید کندل سبز پله‌ای عمل کنید."
    else:
        mood = f"تعادل روانی (RSI={rsi_now}، نسبت حجم {vol_ratio}x، انحراف از EMA20: {ext_pct}%){fng_txt}"
        advice = "هیجان افراطی دیده نمی‌شود؛ پایبندی به حمایت و مقاومت چارت اولویت دارد."

    pe, eps = _f(item.get("pe")), _f(item.get("eps"))
    if market == "BOURSE":
        if pe is None and eps is None:
            fund = "دیتای بنیادی (P/E و EPS) از درگاه فعلی دریافت نشد؛ برای تحلیل بنیادی به کدال مراجعه شود."
        else:
            st_f = "ارزنده" if (eps and eps > 0 and pe and 0 < pe < 8) else ("زیان‌ده" if (eps is not None and eps < 0) else "متعادل")
            fund = f"P/E={pe if pe is not None else 'نامشخص'} | EPS={eps if eps is not None else 'نامشخص'} | وضعیت: {st_f}"
    else:
        qv = float(item.get("quote_vol") or 0)
        fund = f"حجم معاملات ۲۴ ساعته: {round(qv/1e6, 2)} میلیون دلار | نقدشوندگی: {'عالی' if qv > 1e7 else 'متوسط'}"

    strategies = {
        "past": f"گذشته: نوسان بین کف {fib['1.0 (کف)']} و سقف {fib['0.0 (سقف)']}؛ تراز ۰.۶۱۸ ({fib['0.618 (طلایی)']}) کف کلیدی بوده است.",
        "present": f"حال: {structure}. حمایت پرایس اکشن: {pa_sup} | مقاومت پرایس اکشن: {pa_res}.",
        "future": f"آینده: شکست بالای {pa_res} هدف {fib['0.0 (سقف)']} را فعال می‌کند؛ شکست {pa_sup} به پایین هشدار خروج است."
    }

    chart_payload = {
        "candles": [{"time": c["time"], "open": c["open"], "high": c["high"], "low": c["low"], "close": c["close"]} for c in candles],
        "volume": [{"time": c["time"], "value": c["vol"], "color": "rgba(16,185,129,0.35)" if c["close"] >= c["open"] else "rgba(239,68,68,0.35)"} for c in candles],
        "ema20": [{"time": candles[i]["time"], "value": ema20[i]} for i in range(n)],
        "ema50": [{"time": candles[i]["time"], "value": ema50[i]} for i in range(n)],
        "bb_upper": [{"time": candles[i]["time"], "value": bb_up[i]} for i in range(n)],
        "bb_lower": [{"time": candles[i]["time"], "value": bb_lo[i]} for i in range(n)],
        "rsi": rsi_pts,
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
        "price": price, "chart": chart_payload, "fundamental": fund,
        "psychology": {"mood": mood, "advice": advice}, "strategies": strategies, "contracts": contracts,
    }

# ==========================================
# اندپوینت خودآزمون دقیق (Self-Test) برای تایید صحت ریاضی و دیتای زنده
# ==========================================
@app.get("/api/self-test")
async def run_self_test(brs_key: str = ""):
    checks = []

    # تست ۱: رفرنس ریاضی استاندارد StockCharts برای Wilder's RSI(14)
    ref_closes = [44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42, 45.84, 46.08, 45.89, 46.03, 45.61, 46.28, 46.28, 46.00]
    ref_candles = [{"time": 1700000000 + i * 86400, "open": c, "high": c, "low": c, "close": c, "vol": 100} for i, c in enumerate(ref_closes)]
    rsi_out = calc_wilder_rsi_points(ref_candles, 14)
    rsi_ok = len(rsi_out) == 2 and abs(rsi_out[0]["value"] - 70.46) < 0.1 and abs(rsi_out[1]["value"] - 66.25) < 0.1
    checks.append({"name": "Wilder RSI(14) Reference Math", "passed": rsi_ok, "detail": f"got={rsi_out}, expected=[70.46, 66.25]"})

    # تست ۲: تبدیل تاریخ شمسی به میلادی واقعی
    g1 = jalali_to_gregorian(1403, 1, 1)
    g2 = jalali_to_gregorian(1405, 8, 24)
    j_ok = (g1 == (2024, 3, 20)) and (g2 == (2026, 11, 15))
    checks.append({"name": "Jalali-to-Gregorian Calendar Math", "passed": j_ok, "detail": f"1403/1/1->{g1}, 1405/8/24->{g2}"})

    # تست ۳: گیت عدم جعل عدد در دیتای کم (کمتر از ۱۵ کندل)
    short_res = analyze_full("TEST", "CRYPTO", {"quote_vol": 0}, ref_candles[:8])
    gate_ok = all(not c["evaluatable"] and c["target"] is None and c["stop"] is None for c in short_res["contracts"].values())
    checks.append({"name": "Insufficient Data No-Fabrication Gate", "passed": gate_ok, "detail": "8 bars -> all 4 horizons locked to None"})

    # تست ۴: اتصال زنده به منابع واقعی
    c_data, b_data, macro = await asyncio.gather(load_all_crypto(), load_all_bourse(brs_key), load_macro_live())
    checks.append({"name": "Live Crypto Universe (>=300 coins)", "passed": len(c_data["items"]) >= 300, "detail": f"count={len(c_data['items'])}, src={c_data['source']}"})
    checks.append({"name": "Live USDT-Toman (Nobitex, no hardcoded 70200)", "passed": macro["usdt_toman"] is not None, "detail": f"usdt={macro['usdt_toman']}, src={macro['usdt_source']}"})
    checks.append({"name": "Live Global FX Rates", "passed": len(macro["fx_rates"]) >= 10, "detail": f"src={macro['fx_source']}"})
    checks.append({"name": "Live Iran Bourse (>=500 symbols)", "passed": len(b_data["items"]) >= 500, "detail": f"count={len(b_data['items'])}, src={b_data['source']}"})

    all_math_ok = all(x["passed"] for x in checks[:3])
    return {"all_math_tests_passed": all_math_ok, "checks": checks}

@app.get("/api/system-status")
async def system_status(brs_key: str = ""):
    c_data, b_data, macro = await asyncio.gather(load_all_crypto(), load_all_bourse(brs_key), load_macro_live())
    return {
        "timestamp_tehran": datetime.now(TEHRAN_TZ).strftime("%Y-%m-%d %H:%M"),
        "crypto_count": len(c_data["items"]), "crypto_source": c_data["source"],
        "bourse_count": len(b_data["items"]), "bourse_source": b_data["source"],
        "usdt_toman": macro["usdt_toman"], "usdt_source": macro["usdt_source"],
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
    c_data, b_data, macro = await asyncio.gather(load_all_crypto(), load_all_bourse(brs_key), load_macro_live())

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

    full = analyze_full(item["symbol"], mkt_u, item, c_res["candles"], macro.get("fng"))
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
    analyzed = [(it, analyze_full(it["symbol"], "CRYPTO", it, cr["candles"])) for it, cr in zip(candidates, candle_results) if len(cr["candles"]) >= 16]
    top5 = {}
    for hk in HORIZON_SPECS:
        valid = [(it, a["contracts"][hk]) for it, a in analyzed if a["contracts"][hk]["evaluatable"] and ("خرید" in a["contracts"][hk]["action"] or "نگهداری" in a["contracts"][hk]["action"])]
        valid.sort(key=lambda z: z[1]["net_return_pct"] or 0, reverse=True)
        top5[hk] = [{"symbol": it["symbol"], "name": it["name"], "net_return_pct": c["net_return_pct"], "rr": c["rr"]} for it, c in valid[:5]]
    return top5

@app.get("/api/watchlists")
async def watchlists(brs_key: str = ""):
    c_data, b_data, macro = await asyncio.gather(load_all_crypto(), load_all_bourse(brs_key), load_macro_live())
    usdt_t = macro["usdt_toman"]
    fx_rates = macro["fx_rates"]

    # ساخت جدول زنده ارزهای کشورها از API واقعی open.er-api + تتر نوبیتکس (بدون عدد ثابت فیک)
    fx_names = [("USD", "دلار آمریکا"), ("EUR", "یورو اروپا"), ("GBP", "پوند انگلیس"), ("AED", "درهم امارات"),
                ("TRY", "لیر ترکیه"), ("CNY", "یوان چین"), ("CAD", "دلار کانادا"), ("AUD", "دلار استرالیا"),
                ("CHF", "فرانک سوئیس"), ("JPY", "ین ژاپن"), ("SAR", "ریال عربستان"), ("RUB", "روبل روسیه"),
                ("IQD", "دینار عراق"), ("KRW", "وون کره"), ("INR", "روپیه هند")]
    forex_list = []
    for code, fa in fx_names:
        rate_per_usd = fx_rates.get(code)
        if rate_per_usd and usdt_t:
            t_val = round(usdt_t / float(rate_per_usd), 2)
            forex_list.append({"symbol": code, "name": fa, "today": t_val, "yesterday": None, "unit": "تومان (زنده)"})
        elif rate_per_usd:
            forex_list.append({"symbol": code, "name": fa, "today": round(float(rate_per_usd), 4), "yesterday": None, "unit": "نسبت به USD"})

    # انس طلا و نقره/مس یا پکس‌گلد زنده از کریپتو
    paxg = next((x for x in c_data["items"] if x["symbol"] == "PAXG"), None)
    metals_list = []
    if paxg:
        metals_list.append({"symbol": "PAXG/XAU", "name": "انس جهانی طلا (معادل توکن طلا)", "today": paxg["today"], "yesterday": paxg["yesterday"], "unit": "دلار (زنده)"})
        if usdt_t:
            gram18 = round((paxg["today"] * usdt_t / 31.1035) * 0.75, 0)
            metals_list.append({"symbol": "GOLD18_EST", "name": "طلای ۱۸ عیار تئوری (بر مبنای انس و تتر زنده)", "today": gram18, "yesterday": None, "unit": "تومان"})

    # صندوق‌های واقعی از بورس در صورت اتصال
    etf_keywords = ("صندوق", "درآمد", "اهرم", "طلا", "عیار", "کهربا", "کمند", "کیان", "آگاس")
    etf_list = [x for x in b_data["items"] if any(k in x["name"] or k in x["symbol"] for k in etf_keywords)][:15]

    return {
        "bourse": enrich_comparison(b_data["items"][:15]),
        "crypto": enrich_comparison(c_data["items"][:15]),
        "metals": enrich_comparison(metals_list),
        "etfs": enrich_comparison(etf_list),
        "forex": enrich_comparison(forex_list),
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
    c_data, b_data, macro = await asyncio.gather(load_all_crypto(), load_all_bourse(brs_key), load_macro_live())
    usdt_t = macro["usdt_toman"]
    conn = get_conn()
    rows = conn.execute("SELECT id, symbol, market, quantity, avg_buy_price_toman FROM portfolio").fetchall()
    conn.close()
    out = []
    for pid, sym, mkt, qty, buy_p in rows:
        pool = b_data["items"] if mkt == "BOURSE" else c_data["items"]
        m = next((x for x in pool if norm_fa(x["symbol"]) == norm_fa(sym)), None)
        if not m:
            cur_p, pnl, sig = None, None, "نماد در منبع زنده یافت نشد"
        elif mkt == "CRYPTO" and usdt_t is None:
            cur_p, pnl, sig = None, None, "نرخ تتر زنده در دسترس نیست"
        else:
            cur_p = float(m["today"]) * (usdt_t if mkt == "CRYPTO" else 1.0)
            pnl = ((cur_p - buy_p) / buy_p * 100.0) if buy_p > 0 else 0.0
            sig = "فروش (حد ضرر)" if pnl <= -6 else ("سیو سود" if pnl >= 15 else "نگهداری / پایش")
            cur_p, pnl = round(cur_p, 2), round(pnl, 2)
        out.append({"id": pid, "symbol": sym, "market": mkt, "quantity": qty, "buy_price": buy_p,
                    "current_price": cur_p, "pnl_pct": pnl, "signal": sig, "storage": "EPHEMERAL_TMP_ON_VERCEL"})
    return out

@app.get("/", response_class=HTMLResponse)
def home():
    with open(os.path.join(BASE_DIR, "index.html"), "r", encoding="utf-8") as f:
        return f.read()

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
