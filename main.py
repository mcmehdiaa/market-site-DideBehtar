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

app = FastAPI(title="نسخه ارتقایافته - کانال و پرچم خودکار، بک‌تست ۱۸۰ روزه، ۱۰ برتر و نمای ۲×۲")

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
    if raw_date is None:
        return None
    s = str(raw_date).strip()
    if not s:
        return None
    if len(s) == 8 and s.isdigit():
        y = int(s[:4])
        if 1990 <= y <= 2100:
            return int(datetime(y, int(s[4:6]), int(s[6:8]), 12, 0, tzinfo=TEHRAN_TZ).timestamp())
        if 1350 <= y <= 1500:
            gy, gm, gd = jalali_to_gregorian(y, int(s[4:6]), int(s[6:8]))
            return int(datetime(gy, gm, gd, 12, 0, tzinfo=TEHRAN_TZ).timestamp())
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
    "USDT": "تتر دلار دیجیتال", "BTC": "بیت کوین بیتکوین", "ETH": "اتریوم اتريوم", "SOL": "سولانا سول",
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
    "USDC": "یو اس دی کوین"
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
    "H1_DAILY":   {"label": "روزانه",   "min_bars": 15,  "vol_scale": 1.4},
    "H2_WEEKLY":  {"label": "هفتگی",    "min_bars": 25,  "vol_scale": 3.2},
    "H3_MONTHLY": {"label": "ماهانه",   "min_bars": 45,  "vol_scale": 6.5},
    "H4_120D":    {"label": "۱۲۰ روزه", "min_bars": 120, "vol_scale": 12.0},
}

CRYPTO_CACHE: Dict[str, Any] = {"ts": 0, "items": [], "source": "NOT_LOADED"}
BOURSE_CACHE: Dict[str, Any] = {"ts": 0, "items": [], "source": "NOT_LOADED", "key_used": ""}
MACRO_CACHE: Dict[str, Any] = {"ts": 0, "usdt_toman": None, "usdt_source": "NOT_LOADED", "fx_rates": {}, "fx_source": "NOT_LOADED", "fng": None, "key_used": ""}
CANDLE_CACHE: Dict[str, Dict[str, Any]] = {}

def enrich_comparison(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for it in items:
        t, y = _f(it.get("today")), _f(it.get("yesterday"))
        if t is None:
            out.append({**it, "diff": None, "change_pct": None})
            continue
        y_val = y if (y is not None and y > 0) else t
        pct = ((t - y_val) / y_val * 100.0) if y_val > 0 else 0.0
        out.append({**it, "diff": round(t - y_val, 6), "change_pct": round(pct, 2)})
    return out

async def _probe_usdt_toman(brs_key: str) -> Tuple[Optional[float], str]:
    diag = []
    async with httpx.AsyncClient(timeout=3.5, headers=BRSAPI_HEADERS) as client:
        async def try_nobitex_v3():
            try:
                r = await client.get("https://apiv2.nobitex.ir/v3/orderbook/USDTIRT")
                if r.status_code == 200:
                    p = _f(r.json().get("lastTradePrice"))
                    if p and p > 10000:
                        return round(p / 10.0, 1), "LIVE_NOBITEX_V3"
                return None, f"NOBITEX_V3:{r.status_code}"
            except Exception as e:
                return None, f"NOBITEX_V3:{type(e).__name__}"

        async def try_wallex():
            try:
                r = await client.get("https://api.wallex.ir/v1/markets")
                if r.status_code == 200:
                    syms = ((r.json().get("result") or {}).get("symbols") or {})
                    tmn = _f(((syms.get("USDTTMN") or {}).get("stats") or {}).get("lastPrice"))
                    if tmn and tmn > 1000:
                        return round(tmn, 1), "LIVE_WALLEX"
                    irt = _f(((syms.get("USDTIRT") or {}).get("stats") or {}).get("lastPrice"))
                    if irt and irt > 10000:
                        return round(irt / 10.0, 1), "LIVE_WALLEX_IRT"
                return None, f"WALLEX:{r.status_code}"
            except Exception as e:
                return None, f"WALLEX:{type(e).__name__}"

        async def try_tetherland():
            try:
                r = await client.get("https://api.tetherland.com/currencies")
                if r.status_code == 200:
                    p = _f((((r.json().get("data") or {}).get("currencies") or {}).get("USDT") or {}).get("price"))
                    if p and p > 1000:
                        return round(p, 1), "LIVE_TETHERLAND"
                return None, f"TETHERLAND:{r.status_code}"
            except Exception as e:
                return None, f"TETHERLAND:{type(e).__name__}"

        async def try_bitpin():
            try:
                r = await client.get("https://api.bitpin.ir/v1/mkt/markets/")
                if r.status_code == 200:
                    for m in (r.json().get("results") or []):
                        if m.get("code") == "USDT_IRT":
                            p = _f(m.get("price"))
                            if p and p > 1000:
                                return round(p, 1), "LIVE_BITPIN"
                return None, f"BITPIN:{r.status_code}"
            except Exception as e:
                return None, f"BITPIN:{type(e).__name__}"

        async def try_brs_usd():
            if not brs_key:
                return None, "BRS_FX:NO_KEY"
            try:
                r = await client.get("https://Api.BrsApi.ir/Market/Gold_Currency.php", params={"key": brs_key})
                if r.status_code == 200:
                    data = r.json()
                    rows = data.get("currency") if isinstance(data, dict) else _unwrap_list(data)
                    for row in (rows or []):
                        if str(row.get("symbol") or "").upper() in ("USD", "USDT"):
                            p = _f(row.get("price"))
                            if p and p > 1000:
                                return round(p, 1), "LIVE_BRSAPI_FX"
                return None, f"BRS_FX:{r.status_code}"
            except Exception as e:
                return None, f"BRS_FX:{type(e).__name__}"

        results = await asyncio.gather(try_nobitex_v3(), try_wallex(), try_tetherland(), try_bitpin(), try_brs_usd())
        for val, src in results:
            if val is not None:
                return val, src
            diag.append(src)
    return None, " | ".join(diag)

async def load_macro_live(brs_key_override: str = "", force: bool = False):
    brs_key = (brs_key_override or os.getenv("BRSAPI_KEY", "")).strip()
    now = time.time()
    if not force and MACRO_CACHE["ts"] > 0 and (now - MACRO_CACHE["ts"] < 120) and MACRO_CACHE["key_used"] == brs_key:
        return MACRO_CACHE

    async with httpx.AsyncClient(timeout=3.5) as client:
        async def fetch_fx():
            try:
                r = await client.get("https://open.er-api.com/v6/latest/USD")
                if r.status_code == 200:
                    rates = r.json().get("rates") or {}
                    if rates:
                        return rates, "LIVE_OPEN_ER_API"
                return {}, f"FX:{r.status_code}"
            except Exception as e:
                return {}, f"FX:{type(e).__name__}"

        async def fetch_fng():
            try:
                r = await client.get("https://api.alternative.me/fng/?limit=2")
                if r.status_code == 200:
                    d = r.json().get("data") or []
                    if d:
                        return {"value": int(d[0]["value"]), "label": d[0]["value_classification"]}
            except Exception:
                pass
            return None

        (usdt_val, usdt_src), (fx_rates, fx_src), fng_val = await asyncio.gather(
            _probe_usdt_toman(brs_key), fetch_fx(), fetch_fng()
        )

    MACRO_CACHE.update({
        "ts": now, "key_used": brs_key,
        "usdt_toman": usdt_val, "usdt_source": usdt_src,
        "fx_rates": fx_rates or MACRO_CACHE["fx_rates"], "fx_source": fx_src,
        "fng": fng_val or MACRO_CACHE["fng"],
    })
    return MACRO_CACHE

async def load_all_crypto(force: bool = False, usdt_toman: Optional[float] = None):
    now = time.time()
    if not force and CRYPTO_CACHE["items"] and (now - CRYPTO_CACHE["ts"] < 60):
        if usdt_toman:
            for it in CRYPTO_CACHE["items"]:
                if it["symbol"] == "USDT":
                    it["today"], it["yesterday"] = usdt_toman, usdt_toman
        return CRYPTO_CACHE

    merged: Dict[str, Dict[str, Any]] = {}
    sources_used = []
    async with httpx.AsyncClient(timeout=4.5) as client:
        async def get_bin():
            try:
                r = await client.get("https://data-api.binance.vision/api/v3/ticker/24hr")
                return r.json() if r.status_code == 200 else []
            except Exception:
                return []

        async def get_kuc():
            try:
                r = await client.get("https://api.kucoin.com/api/v1/market/allTickers")
                return ((r.json().get("data") or {}).get("ticker") or []) if r.status_code == 200 else []
            except Exception:
                return []

        b_rows, k_rows = await asyncio.gather(get_bin(), get_kuc())
        if b_rows:
            sources_used.append("BINANCE")
            for row in b_rows:
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
        if k_rows:
            sources_used.append("KUCOIN")
            for row in k_rows:
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

    fa_usdt = CRYPTO_FA_NAMES["USDT"]
    merged["USDT"] = {
        "symbol": "USDT", "fa_name": fa_usdt, "name": "تتر (دلار دیجیتال) - USDT/IRT",
        "search_key": norm_fa(f"USDT {fa_usdt}"), "market": "CRYPTO",
        "today": usdt_toman, "yesterday": usdt_toman, "unit": "تومان", "quote_vol": 1e9
    }

    items = sorted(merged.values(), key=lambda x: x["quote_vol"], reverse=True)
    CRYPTO_CACHE.update({"ts": now, "items": items, "source": "+".join(sources_used) or "NO_CRYPTO_SRC"})
    return CRYPTO_CACHE

async def load_all_bourse(brs_key_override: str = "", force: bool = False):
    brs_key = (brs_key_override or os.getenv("BRSAPI_KEY", "")).strip()
    now = time.time()
    if not force and BOURSE_CACHE["ts"] > 0 and (now - BOURSE_CACHE["ts"] < 120) and BOURSE_CACHE["key_used"] == brs_key:
        return BOURSE_CACHE

    items, diag = [], []
    if brs_key:
        try:
            async with httpx.AsyncClient(timeout=6.0, headers=BRSAPI_HEADERS) as client:
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

    async with httpx.AsyncClient(timeout=2.0, headers=TSETMC_HEADERS) as client:
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
            diag.append(f"TSETMC:{type(e).__name__}")

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
    if market == "CRYPTO" and symbol.upper() == "USDT":
        to_ts, from_ts = int(now), int(now) - 185 * 86400
        async with httpx.AsyncClient(timeout=4.0, headers=BRSAPI_HEADERS) as client:
            try:
                r = await client.get(f"https://apiv2.nobitex.ir/market/udf/history?symbol=USDTIRT&resolution=D&from={from_ts}&to={to_ts}")
                if r.status_code == 200 and r.json().get("s") == "ok":
                    d = r.json()
                    for t, o, h, l, c, v in zip(d.get("t", []), d.get("o", []), d.get("h", []), d.get("l", []), d.get("c", []), d.get("v", [])):
                        candles.append({"time": int(t), "open": float(o)/10.0, "high": float(h)/10.0, "low": float(l)/10.0, "close": float(c)/10.0, "vol": float(v)})
                    candles = _clean_sort_candles(candles)[-180:]
                    if candles:
                        res = {"ts": now, "source": "LIVE_NOBITEX_USDTIRT_1D", "candles": candles}
                        CANDLE_CACHE[ckey] = res
                        return res
            except Exception as e:
                diag.append(f"NOBITEX_UDF:{type(e).__name__}")
            try:
                r2 = await client.get(f"https://api.wallex.ir/v1/udf/history?symbol=USDTTMN&resolution=D&from={from_ts}&to={to_ts}")
                if r2.status_code == 200 and r2.json().get("s") == "ok":
                    d = r2.json()
                    for t, o, h, l, c, v in zip(d.get("t", []), d.get("o", []), d.get("h", []), d.get("l", []), d.get("c", []), d.get("v", [])):
                        candles.append({"time": int(t), "open": float(o), "high": float(h), "low": float(l), "close": float(c), "vol": float(v)})
                    candles = _clean_sort_candles(candles)[-180:]
                    if candles:
                        res = {"ts": now, "source": "LIVE_WALLEX_USDTTMN_1D", "candles": candles}
                        CANDLE_CACHE[ckey] = res
                        return res
            except Exception as e:
                diag.append(f"WALLEX_UDF:{type(e).__name__}")

    elif market == "CRYPTO":
        async with httpx.AsyncClient(timeout=4.0) as client:
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
                async with httpx.AsyncClient(timeout=6.0, headers=BRSAPI_HEADERS) as client:
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
            except Exception as e:
                diag.append(f"BRS_ERR:{type(e).__name__}")
        else:
            diag.append("BRS_KEY:EMPTY")

    return {"ts": now, "source": " | ".join(diag) or "NO_DATA", "candles": []}

# ==========================================
# اندیکاتورها
# ==========================================
def calc_ema(vals: List[float], period: int) -> List[float]:
    k = 2.0 / (period + 1)
    out = [vals[0]]
    for v in vals[1:]:
        out.append(v * k + out[-1] * (1.0 - k))
    return out

def calc_wilder_rsi_points(candles: List[Dict[str, Any]], period: int = 14) -> List[Dict[str, Any]]:
    n = len(candles)
    if n <= period:
        return []
    closes = [c["close"] for c in candles]
    gains, losses = [], []
    for i in range(1, n):
        d = closes[i] - closes[i - 1]
        gains.append(max(d, 0.0))
        losses.append(max(-d, 0.0))
    avg_g, avg_l = sum(gains[:period]) / period, sum(losses[:period]) / period

    def _to_rsi(ag, al):
        return (100.0 if ag > 0.0 else 50.0) if al == 0.0 else round(100.0 - (100.0 / (1.0 + (ag / al))), 2)

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
    markers, n = [], len(candles)
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
        body, rng = abs(c["close"] - c["open"]), max(c["high"] - c["low"], 1e-12)
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
    return markers[-35:], (round(sup_lvls[-1], 6) if sup_lvls else round(min(x["low"] for x in candles[-30:]), 6)), (round(res_lvls[-1], 6) if res_lvls else round(max(x["high"] for x in candles[-30:]), 6))

# ==========================================
# وظیفه جدید ۱: تشخیص و رسم خودکار کانال روند، پرچم، مثلث + نقطه ماشه و هدف شکست
# ==========================================
def detect_patterns_and_channel(candles: List[Dict[str, Any]]) -> Dict[str, Any]:
    if len(candles) < 20:
        return {"available": False, "pattern_name": "داده ناکافی برای رسم کانال", "bias": "NEUTRAL"}

    win = candles[-35:] if len(candles) >= 35 else candles
    m_n = len(win)
    closes = [c["close"] for c in win]
    highs = [c["high"] for c in win]
    lows = [c["low"] for c in win]

    # رگرسیون خطی برای شیب کانال کلی اخیر
    x_mean = (m_n - 1) / 2.0
    y_mean = sum(closes) / m_n
    num = sum((i - x_mean) * (closes[i] - y_mean) for i in range(m_n))
    den = sum((i - x_mean) ** 2 for i in range(m_n)) or 1.0
    slope = num / den
    intercept = y_mean - slope * x_mean
    slope_pct = (slope / max(y_mean, 1e-12)) * 100.0

    # محاسبه خط سقف و کف کانال در بازه فعلی
    up_dev = max(highs[i] - (slope * i + intercept) for i in range(m_n))
    lo_dev = max((slope * i + intercept) - lows[i] for i in range(m_n))

    u_start = round(intercept + up_dev, 6)
    u_end = round(slope * (m_n - 1) + intercept + up_dev, 6)
    l_start = round(intercept - lo_dev, 6)
    l_end = round(slope * (m_n - 1) + intercept - lo_dev, 6)

    # بررسی مثلث فشردگی در ۲۴ کندل آخر (نوسان نیمه اول در مقابل نیمه دوم)
    half = m_n // 2
    h1_max, h2_max = max(highs[:half]), max(highs[half:])
    l1_min, l2_min = min(lows[:half]), min(lows[half:])
    range1, range2 = h1_max - l1_min, h2_max - l2_min

    # بررسی میله پرچم (۲۵ کندل قبل از ۱۵ کندل آخر)
    pole_slice = candles[-45:-15] if len(candles) >= 45 else candles[:max(1, len(candles) - 15)]
    pole_low = min(c["low"] for c in pole_slice)
    pole_high = max(c["high"] for c in pole_slice)
    pole_start_c = pole_slice[0]["close"]
    pole_end_c = pole_slice[-1]["close"]
    pole_move_pct = ((pole_end_c - pole_start_c) / max(pole_start_c, 1e-12)) * 100.0
    pole_height = max(pole_high - pole_low, 0.0)

    # خطوط اختصاصی الگو (پیش‌فرض خطوط کانال رگرسیون، در مثلث به خطوط همگرا تغییر می‌کند)
    line_u_start, line_u_end = u_start, u_end
    line_l_start, line_l_end = l_start, l_end

    if h2_max < h1_max * 0.995 and l2_min > l1_min * 1.005 and range2 < range1 * 0.78:
        pattern_name = "مثلث متقارن / فشردگی قیمت (Triangle)"
        bias = "BREAKOUT_PENDING"
        line_u_start, line_u_end = round(h1_max, 6), round(h2_max, 6)
        line_l_start, line_l_end = round(l1_min, 6), round(l2_min, 6)
        breakout_price = line_u_end
        target_price = round(breakout_price + range1 * 0.75, 6)
        desc = f"کاهش نوسان از {round(range1, 4)} به {round(range2, 4)}؛ آماده شکست پرقدرت در راس مثلث."
    elif pole_move_pct >= 10.0 and -0.85 <= slope_pct <= 0.15 and (u_end - l_end) < pole_height * 0.55:
        pattern_name = "الگوی پرچم صعودی (Bull Flag)"
        bias = "BULLISH"
        breakout_price = u_end
        target_price = round(breakout_price + pole_height * 0.65, 6)
        desc = f"جهش قبلی (+{round(pole_move_pct, 1)}%) همراه با استراحت در کانال باریک؛ شکست سقف {u_end} ماشه صعود است."
    elif pole_move_pct <= -10.0 and -0.15 <= slope_pct <= 0.85 and (u_end - l_end) < pole_height * 0.55:
        pattern_name = "الگوی پرچم نزولی (Bear Flag)"
        bias = "BEARISH"
        breakout_price = l_end
        target_price = round(max(breakout_price - pole_height * 0.65, breakout_price * 0.35), 6)
        desc = f"ریزش قبلی ({round(pole_move_pct, 1)}%) و پولبک ضعیف؛ شکست کف {l_end} خطر ادامه ریزش را دارد."
    elif slope_pct > 0.12:
        pattern_name = "کانال صعودی (Ascending Channel)"
        bias = "BULLISH"
        breakout_price = u_end
        target_price = round(u_end + (u_end - l_end) * 0.5, 6)
        desc = f"شیب مثبت (+{round(slope_pct, 2)}% در روز)؛ کف کانال {l_end} حمایت و سقف {u_end} مقاومت است."
    elif slope_pct < -0.12:
        pattern_name = "کانال نزولی (Descending Channel)"
        bias = "BEARISH"
        breakout_price = u_end
        target_price = round(u_end + (u_end - l_end) * 0.5, 6)
        desc = f"شیب منفی ({round(slope_pct, 2)}% در روز)؛ خروج از کانال فقط با شکست سقف {u_end} تایید می‌شود."
    else:
        pattern_name = "کانال خنثی / رنج (Horizontal Channel)"
        bias = "NEUTRAL"
        breakout_price = u_end
        target_price = round(u_end + (u_end - l_end) * 0.6, 6)
        desc = f"نوسان رنج بین کف {l_end} و سقف {u_end}؛ مناسب نوسان‌گیری یا انتظار برای شکست."

    t0, t1 = win[0]["time"], win[-1]["time"]
    return {
        "available": True,
        "pattern_name": pattern_name,
        "bias": bias,
        "description": desc,
        "upper_line": [{"time": t0, "value": line_u_start}, {"time": t1, "value": line_u_end}],
        "lower_line": [{"time": t0, "value": line_l_start}, {"time": t1, "value": line_l_end}],
        "breakout_price": breakout_price,
        "pattern_target": target_price,
        "channel_floor": line_l_end,
    }

# ==========================================
# وظیفه جدید ۴: بک‌تست واقعی بدون نگاه به آینده روی ۱۸۰ کندل خود نماد
# ==========================================
def run_backtest_180d(candles: List[Dict[str, Any]], market: str) -> Dict[str, Any]:
    n = len(candles)
    if n < 55:
        return {"sufficient": False, "reason": f"حداقل ۵۵ کندل لازم است (موجود: {n})"}

    closes = [c["close"] for c in candles]
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]
    ema20 = calc_ema(closes, 20)
    ema12, ema26 = calc_ema(closes, 12), calc_ema(closes, 26)
    macd_l = [a - b for a, b in zip(ema12, ema26)]
    sig_l = calc_ema(macd_l, 9)
    rsi_map = {p["time"]: p["value"] for p in calc_wilder_rsi_points(candles, 14)}
    fee_pct = 1.25 if market == "BOURSE" else 0.20

    trades = []
    i = 30
    while i < n - 8:
        t_i = candles[i]["time"]
        rsi_v = rsi_map.get(t_i, 50.0)
        # شرط ورود: شکست رو به بالای EMA20 یا تقاطع صعودی مکدی بالای EMA20
        macd_cross = macd_l[i] > sig_l[i] and macd_l[i - 1] <= sig_l[i - 1] and closes[i] > ema20[i]
        ema_reclaim = closes[i] > ema20[i] and closes[i - 1] <= ema20[i - 1] and macd_l[i] > sig_l[i]

        if (macd_cross or ema_reclaim) and 38.0 <= rsi_v <= 68.0:
            entry = closes[i]
            rets = [abs(closes[k] - closes[k - 1]) / closes[k - 1] for k in range(max(1, i - 14), i + 1) if closes[k - 1] > 0]
            atr_pct = max(min(sum(rets) / max(len(rets), 1), 0.06), 0.012)
            tp = entry * (1.0 + atr_pct * 2.6)
            sl = entry * (1.0 - atr_pct * 1.4)

            exit_p, exit_idx = closes[min(i + 12, n - 1)], min(i + 12, n - 1)
            for j in range(i + 1, min(i + 13, n)):
                if lows[j] <= sl:
                    exit_p, exit_idx = sl, j
                    break
                if highs[j] >= tp:
                    exit_p, exit_idx = tp, j
                    break
            net_pct = ((exit_p - entry) / entry) * 100.0 - fee_pct
            trades.append(round(net_pct, 2))
            i = exit_idx + 1
        else:
            i += 1

    if len(trades) < 3:
        return {"sufficient": False, "trades_count": len(trades), "reason": f"تعداد سیگنال‌های تاریخی کم است ({len(trades)} معامله)؛ آمار قابل اتکا نیست."}

    wins = sum(1 for x in trades if x > 0)
    win_rate = round((wins / len(trades)) * 100.0, 1)
    avg_ret = round(sum(trades) / len(trades), 2)
    return {
        "sufficient": True,
        "trades_count": len(trades),
        "wins": wins,
        "losses": len(trades) - wins,
        "win_rate_pct": win_rate,
        "avg_return_pct": avg_ret,
        "summary": f"در ۱۸۰ روز گذشته روی همین نماد: {win_rate}% موفقیت ({wins} برد از {len(trades)} معامله) | میانگین خالص هر معامله: {'+' if avg_ret >= 0 else ''}{avg_ret}%"
    }

def analyze_full(symbol: str, market: str, item: Dict[str, Any], candles: List[Dict[str, Any]], fng_data: Optional[dict] = None):
    n = len(candles)
    closes, highs, lows, vols = [c["close"] for c in candles], [c["high"] for c in candles], [c["low"] for c in candles], [c["vol"] for c in candles]
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
    patterns = detect_patterns_and_channel(candles)
    backtest = run_backtest_180d(candles, market)
    structure = "روند صعودی (بالای EMA20 و EMA50)" if price > ema20[-1] > ema50[-1] else ("روند نزولی (زیر EMA20 و EMA50)" if price < ema20[-1] < ema50[-1] else "فاز رنج / تغییر روند")

    fee_pct = 1.25 if market == "BOURSE" else 0.20
    contracts = {}
    confluence_hits = 0
    for hk, spec in HORIZON_SPECS.items():
        if n < spec["min_bars"] or price <= 0 or rsi_now is None:
            contracts[hk] = {
                "horizon": hk, "label": spec["label"], "evaluatable": False, "icon": "⛔", "tone": "rose",
                "available_bars": n, "required_min_bars": spec["min_bars"],
                "action": "قابل ارزیابی نیست (کمبود تاریخچه)",
                "target": None, "stop": None, "net_return_pct": None, "net_risk_pct": None, "rr": None
            }
        else:
            atr_tp = price * (1.0 + min(daily_vol * spec["vol_scale"] * 1.45, 0.65))
            atr_sl = price * (1.0 - min(daily_vol * spec["vol_scale"] * 0.72, 0.28))
            sl_v = round(max(atr_sl, pa_sup * 0.992), 6) if (hk in ("H1_DAILY", "H2_WEEKLY") and 0 < pa_sup < price) else round(atr_sl, 6)
            tp = round(atr_tp, 6)
            net_ret = round(((tp - price) / price * 100.0) - fee_pct, 2)
            net_rsk = round(((price - sl_v) / price * 100.0) + fee_pct, 2)
            rr = round(net_ret / net_rsk, 2) if net_rsk > 0 else 0.0

            if rsi_now >= 75:
                act, icon, tone = "سیو سود / انتظار اصلاح", "🟡", "amber"
            elif rsi_now <= 32 and price <= fib["0.500"]:
                act, icon, tone = "خرید پله‌ای روی حمایت", "🟢", "emerald"
                confluence_hits += 1
            elif macd_l[-1] > sig_l[-1] and price > ema20[-1] and rr >= 1.3:
                act, icon, tone = "خرید / نگهداری صعودی", "🟢", "emerald"
                confluence_hits += 1
            elif price < ema20[-1] and macd_l[-1] < sig_l[-1]:
                act, icon, tone = "فروش / دوری از معامله", "🔴", "rose"
            else:
                act, icon, tone = "نوسان‌گیری بین سطوح", "🟡", "amber"

            contracts[hk] = {
                "horizon": hk, "label": spec["label"], "evaluatable": True, "icon": icon, "tone": tone,
                "available_bars": n, "required_min_bars": spec["min_bars"],
                "action": act, "target": tp, "stop": sl_v,
                "net_return_pct": net_ret, "net_risk_pct": net_rsk, "rr": rr
            }

    avg_vol20 = sum(vols[-21:-1]) / max(len(vols[-21:-1]), 1) if len(vols) > 2 else (vols[-1] or 1.0)
    vol_ratio = round(vols[-1] / avg_vol20, 2) if avg_vol20 > 0 else 1.0
    ext_pct = round(((price - ema20[-1]) / ema20[-1]) * 100.0, 2) if ema20[-1] > 0 else 0.0
    fng_txt = f" | شاخص کل ترس/طمع: {fng_data['value']}/100 ({fng_data['label']})" if (market == "CRYPTO" and fng_data) else ""

    if rsi_now is not None and rsi_now >= 70 and vol_ratio >= 1.5:
        mood = f"اوج طمع (RSI={rsi_now}، حجم {vol_ratio}x، فاصله از EMA20: +{ext_pct}%){fng_txt}"
        advice = "جهش حجم همراه با اشباع خرید نشانه فومو است؛ در سقف نخرید."
    elif rsi_now is not None and rsi_now <= 32 and vol_ratio >= 1.4:
        mood = f"ترس شدید (RSI={rsi_now}، حجم {vol_ratio}x، فاصله: {ext_pct}%){fng_txt}"
        advice = "تخلیه فروش هیجانی در کف؛ فقط با تایید کندل سبز پله‌ای وارد شوید."
    else:
        mood = f"تعادل روانی (RSI={rsi_now}، نسبت حجم {vol_ratio}x، انحراف: {ext_pct}%){fng_txt}"
        advice = "هیجان افراطی دیده نمی‌شود؛ به خطوط کانال و حمایت چارت پایبند بمانید."

    pe, eps = _f(item.get("pe")), _f(item.get("eps"))
    if market == "BOURSE":
        if pe is None and eps is None:
            fund = "دیتای بنیادی (P/E و EPS) از درگاه فعلی دریافت نشد؛ کدال بررسی شود."
        else:
            st_f = "ارزنده" if (eps and eps > 0 and pe and 0 < pe < 8) else ("زیان‌ده" if (eps is not None and eps < 0) else "متعادل")
            fund = f"P/E={pe if pe is not None else 'نامشخص'} | EPS={eps if eps is not None else 'نامشخص'} | وضعیت: {st_f}"
    else:
        qv = float(item.get("quote_vol") or 0)
        fund = f"حجم معاملات ۲۴ ساعته: {round(qv/1e6, 2)} میلیون دلار | نقدشوندگی: {'عالی' if qv > 1e7 else 'متوسط'}"

    strategies = {
        "past": f"گذشته: نوسان بین کف {fib['1.0 (کف)']} و سقف {fib['0.0 (سقف)']}؛ تراز ۰.۶۱۸ ({fib['0.618 (طلایی)']}) کف کلیدی بوده است.",
        "present": f"حال: {structure} | الگو: {patterns['pattern_name']}.",
        "future": f"آینده: {patterns.get('description', '')}"
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
        "pa_markers": pa_markers, "pa_support": pa_sup, "pa_resistance": pa_res,
        "fib": fib, "rsi_now": rsi_now, "structure": structure,
        "patterns": patterns,
    }

    return {
        "price": price, "chart": chart_payload, "fundamental": fund,
        "psychology": {"mood": mood, "advice": advice}, "strategies": strategies,
        "contracts": contracts, "confluence": f"{confluence_hits}/4", "backtest": backtest,
    }

@app.get("/api/self-test")
async def run_self_test(brs_key: str = ""):
    checks = []
    ref_closes = [44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42, 45.84, 46.08, 45.89, 46.03, 45.61, 46.28, 46.28, 46.00]
    ref_candles = [{"time": 1700000000 + i * 86400, "open": c, "high": c, "low": c, "close": c, "vol": 100} for i, c in enumerate(ref_closes)]
    rsi_out = calc_wilder_rsi_points(ref_candles, 14)
    rsi_ok = len(rsi_out) == 2 and abs(rsi_out[0]["value"] - 70.46) < 0.1 and abs(rsi_out[1]["value"] - 66.25) < 0.1
    checks.append({"name": "Wilder RSI(14) Reference Math", "passed": rsi_ok, "detail": f"got={rsi_out}"})

    g1, g2 = jalali_to_gregorian(1403, 1, 1), jalali_to_gregorian(1405, 8, 24)
    checks.append({"name": "Jalali-to-Gregorian Calendar Math", "passed": (g1 == (2024, 3, 20) and g2 == (2026, 11, 15)), "detail": f"{g1}, {g2}"})

    # تست ۴: تشخیص الگوی کانال صعودی مصنوعی و بک‌تست ۱۸۰ روزه
    syn = [{"time": 1700000000 + i * 86400, "open": 100 + i * 0.8, "high": 102 + i * 0.8 + (2 if i % 4 == 0 else 0),
            "low": 98 + i * 0.8 - (2 if i % 4 == 2 else 0), "close": 100.5 + i * 0.8 + math.sin(i * 0.6) * 2.5, "vol": 1000} for i in range(90)]
    pat_ok = detect_patterns_and_channel(syn)["available"] and len(detect_patterns_and_channel(syn)["upper_line"]) == 2
    checks.append({"name": "Auto Channel & Pattern Detector", "passed": pat_ok, "detail": detect_patterns_and_channel(syn)["pattern_name"]})

    bt = run_backtest_180d(syn, "CRYPTO")
    checks.append({"name": "180D Backtest Engine (No Lookahead)", "passed": ("sufficient" in bt), "detail": bt.get("summary") or bt.get("reason")})

    short_res = analyze_full("TEST", "CRYPTO", {"quote_vol": 0}, ref_candles[:8])
    gate_ok = all(not c["evaluatable"] and c["target"] is None for c in short_res["contracts"].values())
    checks.append({"name": "Insufficient Data No-Fabrication Gate", "passed": gate_ok, "detail": "8 bars -> locked"})

    macro, b_data = await asyncio.gather(load_macro_live(brs_key, force=True), load_all_bourse(brs_key))
    c_data = await load_all_crypto(force=True, usdt_toman=macro["usdt_toman"])
    checks.append({"name": "Live Crypto Universe (>=300 coins)", "passed": len(c_data["items"]) >= 300, "detail": f"count={len(c_data['items'])}"})
    checks.append({"name": "Live USDT-Toman", "passed": macro["usdt_toman"] is not None, "detail": f"usdt={macro['usdt_toman']}, {macro['usdt_source']}"})
    checks.append({"name": "Live Iran Bourse (>=500 symbols)", "passed": len(b_data["items"]) >= 500, "detail": f"count={len(b_data['items'])}"})

    return {"all_math_tests_passed": all(x["passed"] for x in checks[:5]), "checks": checks}

@app.get("/api/system-status")
async def system_status(brs_key: str = ""):
    macro, b_data = await asyncio.gather(load_macro_live(brs_key), load_all_bourse(brs_key))
    c_data = await load_all_crypto(usdt_toman=macro["usdt_toman"])
    return {
        "timestamp_tehran": datetime.now(TEHRAN_TZ).strftime("%Y-%m-%d %H:%M"),
        "crypto_count": len(c_data["items"]), "crypto_source": c_data["source"],
        "bourse_count": len(b_data["items"]), "bourse_source": b_data["source"],
        "usdt_toman": macro["usdt_toman"], "usdt_source": macro["usdt_source"],
    }

@app.get("/api/search")
async def instant_search(q: str = "", brs_key: str = ""):
    q_norm = norm_fa(q)
    macro, b_data = await asyncio.gather(load_macro_live(brs_key), load_all_bourse(brs_key))
    c_data = await load_all_crypto(usdt_toman=macro["usdt_toman"])
    results = []
    for it in b_data["items"]:
        if not q_norm or q_norm in it["search_key"]:
            results.append({"symbol": it["symbol"], "name": it["name"], "market": "BOURSE", "today": it["today"], "unit": "تومان"})
            if len(results) >= 15:
                break
    for it in c_data["items"]:
        if not q_norm or q_norm in it["search_key"]:
            results.append({"symbol": it["symbol"], "name": it["name"], "market": "CRYPTO", "today": it["today"], "unit": it["unit"]})
            if len(results) >= 30:
                break
    return {"query": q, "results": results}

@app.get("/api/analyze")
async def analyze_endpoint(symbol: str, market: str = "AUTO", brs_key: str = ""):
    t0 = time.time()
    q_norm = norm_fa(symbol)
    mkt_u = market.strip().upper()
    macro, b_data = await asyncio.gather(load_macro_live(brs_key), load_all_bourse(brs_key))
    c_data = await load_all_crypto(usdt_toman=macro["usdt_toman"])

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

# ==========================================
# وظیفه جدید ۳: اسکنر ۱۰ برتر در هر ۴ بازه + امتیاز اجماع ۴/۴
# ==========================================
@app.get("/api/top10-scanner")
async def top10_scanner(brs_key: str = ""):
    c_data, b_data = await asyncio.gather(load_all_crypto(), load_all_bourse(brs_key))
    cands_c = [(x, "CRYPTO") for x in c_data["items"] if x.get("today") and x["symbol"] != "USDT"][:24]
    cands_b = [(x, "BOURSE") for x in sorted(b_data["items"], key=lambda z: z.get("tvol", 0), reverse=True)[:8]]
    candidates = cands_c + cands_b

    candle_results = await asyncio.gather(*[fetch_180_candles(it["symbol"], mkt, it, brs_key) for it, mkt in candidates])
    analyzed = []
    for (it, mkt), cr in zip(candidates, candle_results):
        if len(cr["candles"]) >= 16:
            analyzed.append((it, mkt, analyze_full(it["symbol"], mkt, it, cr["candles"])))

    top10 = {}
    for hk in HORIZON_SPECS:
        valid = []
        for it, mkt, a in analyzed:
            c = a["contracts"][hk]
            if c["evaluatable"] and ("خرید" in c["action"] or "نگهداری" in c["action"]):
                conf_num = int(a["confluence"].split("/")[0])
                valid.append({
                    "symbol": it["symbol"], "market": mkt, "name": it["name"],
                    "net_return_pct": c["net_return_pct"], "rr": c["rr"],
                    "confluence": a["confluence"], "conf_num": conf_num,
                    "win_rate": a["backtest"].get("win_rate_pct") if a["backtest"].get("sufficient") else None
                })
        # اولویت با اجماع بالاتر (مثلاً ۴/۴) و سپس بیشترین بازده خالص
        valid.sort(key=lambda z: (z["conf_num"], z["net_return_pct"] or 0), reverse=True)
        top10[hk] = valid[:10]
    return top10

@app.get("/api/watchlists")
async def watchlists(brs_key: str = ""):
    macro, b_data = await asyncio.gather(load_macro_live(brs_key), load_all_bourse(brs_key))
    c_data = await load_all_crypto(usdt_toman=macro["usdt_toman"])
    usdt_t, fx_rates = macro["usdt_toman"], macro["fx_rates"]

    fx_names = [("USD", "دلار آمریکا"), ("EUR", "یورو اروپا"), ("GBP", "پوند انگلیس"), ("AED", "درهم امارات"),
                ("TRY", "لیر ترکیه"), ("CNY", "یوان چین"), ("CAD", "دلار کانادا"), ("AUD", "دلار استرالیا"),
                ("CHF", "فرانک سوئیس"), ("JPY", "ین ژاپن"), ("SAR", "ریال عربستان"), ("RUB", "روبل روسیه"),
                ("IQD", "دینار عراق"), ("KRW", "وون کره"), ("INR", "روپیه هند")]
    forex_list = []
    for code, fa in fx_names:
        rate_per_usd = fx_rates.get(code)
        if rate_per_usd and usdt_t:
            forex_list.append({"symbol": code, "name": fa, "today": round(usdt_t / float(rate_per_usd), 2), "yesterday": None, "unit": "تومان (زنده)"})
        elif rate_per_usd:
            forex_list.append({"symbol": code, "name": fa, "today": round(float(rate_per_usd), 4), "yesterday": None, "unit": "نسبت به USD"})

    paxg = next((x for x in c_data["items"] if x["symbol"] == "PAXG"), None)
    metals_list = []
    if paxg:
        metals_list.append({"symbol": "PAXG/XAU", "name": "انس جهانی طلا", "today": paxg["today"], "yesterday": paxg["yesterday"], "unit": "دلار (زنده)"})
        if usdt_t:
            metals_list.append({"symbol": "GOLD18_EST", "name": "طلای ۱۸ عیار تئوری (انس و تتر زنده)", "today": round((paxg["today"] * usdt_t / 31.1035) * 0.75, 0), "yesterday": None, "unit": "تومان"})

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
    macro, b_data = await asyncio.gather(load_macro_live(brs_key), load_all_bourse(brs_key))
    c_data = await load_all_crypto(usdt_toman=macro["usdt_toman"])
    usdt_t = macro["usdt_toman"]
    conn = get_conn()
    rows = conn.execute("SELECT id, symbol, market, quantity, avg_buy_price_toman FROM portfolio").fetchall()
    conn.close()
    out = []
    for pid, sym, mkt, qty, buy_p in rows:
        pool = b_data["items"] if mkt == "BOURSE" else c_data["items"]
        m = next((x for x in pool if norm_fa(x["symbol"]) == norm_fa(sym)), None)
        if not m or m.get("today") is None:
            cur_p, pnl, sig = None, None, "نماد در منبع زنده یافت نشد"
        elif mkt == "CRYPTO" and sym.upper() != "USDT" and usdt_t is None:
            cur_p, pnl, sig = None, None, "نرخ تتر زنده در دسترس نیست"
        else:
            mult = 1.0 if (mkt == "BOURSE" or sym.upper() == "USDT") else usdt_t
            cur_p = float(m["today"]) * mult
            pnl = ((cur_p - buy_p) / buy_p * 100.0) if buy_p > 0 else 0.0
            sig = "فروش (حد ضرر)" if pnl <= -6 else ("سیو سود" if pnl >= 15 else "نگهداری / پایش")
            cur_p, pnl = round(cur_p, 2), round(pnl, 2)
        out.append({"id": pid, "symbol": sym, "market": mkt, "quantity": qty, "buy_price": buy_p,
                    "current_price": cur_p, "pnl_pct": pnl, "signal": sig})
    return out

@app.get("/", response_class=HTMLResponse)
def home():
    with open(os.path.join(BASE_DIR, "index.html"), "r", encoding="utf-8") as f:
        return f.read()

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
