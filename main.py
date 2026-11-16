import os, math, time, asyncio, sqlite3
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional, Tuple
import httpx, uvicorn
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

TEHRAN_TZ = timezone(timedelta(hours=3, minutes=30))
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = "/tmp/standalone_market.db" if os.path.isdir("/tmp") else os.path.join(BASE_DIR, "standalone_market.db")
TSETMC_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/131.0.0.0 Safari/537.36", "Accept": "application/json", "Referer": "https://tsetmc.com/"}
BRSAPI_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 6.1; Win64; x64) Chrome/131.0.0.0 Safari/537.36 OPR/106.0.0.0", "Accept": "application/json"}

app = FastAPI(title="فاز ۲ - واگرایی، کندل‌شناسی، پول هوشمند و یکپارچگی")

def norm_fa(t: str) -> str:
    return str(t or "").strip().upper().replace("ي", "ی").replace("ك", "ک").replace("ة", "ه").replace("\u200c", "").replace("‌", "").replace(" ", "").replace("-", "")

def _f(v) -> Optional[float]:
    try:
        return None if (v is None or str(v).strip() == "") else float(str(v).replace(",", "").strip())
    except Exception:
        return None

def _unwrap_list(p) -> list:
    if isinstance(p, list): return p
    if isinstance(p, dict):
        for k in ("data", "Data", "history", "History", "items", "result", "Result"):
            if isinstance(p.get(k), list): return p[k]
    return []

def jalali_to_gregorian(jy: int, jm: int, jd: int) -> Tuple[int, int, int]:
    jy += 1595
    days = -355668 + (365 * jy) + ((jy // 33) * 8) + (((jy % 33) + 3) // 4) + jd + (((jm - 1) * 31) if jm < 7 else (((jm - 7) * 30) + 186))
    gy = 400 * (days // 146097); days %= 146097
    if days > 36524:
        days -= 1; gy += 100 * (days // 36524); days %= 36524
        if days >= 365: days += 1
    gy += 4 * (days // 1461); days %= 1461
    if days > 365: gy += (days - 1) // 365; days = (days - 1) % 365
    gd = days + 1
    leap = (gy % 4 == 0 and gy % 100 != 0) or (gy % 400 == 0)
    sal = [0, 31, 29 if leap else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    gm = 0
    while gm < 13 and gd > sal[gm]: gd -= sal[gm]; gm += 1
    return gy, gm, gd

def parse_candle_timestamp(raw) -> Optional[int]:
    if raw is None: return None
    s = str(raw).strip()
    if len(s) == 8 and s.isdigit():
        y = int(s[:4])
        if 1990 <= y <= 2100: return int(datetime(y, int(s[4:6]), int(s[6:8]), 12, 0, tzinfo=TEHRAN_TZ).timestamp())
        if 1350 <= y <= 1500:
            gy, gm, gd = jalali_to_gregorian(y, int(s[4:6]), int(s[6:8]))
            return int(datetime(gy, gm, gd, 12, 0, tzinfo=TEHRAN_TZ).timestamp())
    parts = s[:10].replace("/", "-").split("-")
    if len(parts) == 3 and all(p.isdigit() for p in parts):
        y, m, d = int(parts[0]), int(parts[1]), int(parts[2])
        if 1990 <= y <= 2100: return int(datetime(y, m, d, 12, 0, tzinfo=TEHRAN_TZ).timestamp())
        if 1350 <= y <= 1500:
            gy, gm, gd = jalali_to_gregorian(y, m, d)
            return int(datetime(gy, gm, gd, 12, 0, tzinfo=TEHRAN_TZ).timestamp())
    return None

CRYPTO_FA_NAMES = {
    "USDT": "تتر دلار دیجیتال", "BTC": "بیت کوین بیتکوین", "ETH": "اتریوم اتريوم", "SOL": "سولانا سول",
    "BNB": "بایننس کوین", "XRP": "ریپل", "ADA": "کاردانو آدا", "DOGE": "دوج کوین دوج",
    "TRX": "ترون", "TON": "تون کوین تون", "AVAX": "آوالانچ اولانچ", "SHIB": "شیبا اینو شیبا",
    "PEPE": "پپه", "LINK": "چین لینک لینک", "DOT": "پولکادات دات", "SUI": "سویی",
    "LTC": "لایت کوین", "BCH": "بیت کوین کش", "NEAR": "نیر پروتکل نیر", "APT": "اپتوس",
    "ARB": "آربیتروم", "OP": "اپتیمیزم", "POL": "پالیگان متیک", "MATIC": "متیک پالیگان",
    "UNI": "یونی سواپ", "ATOM": "کازموس اتم", "FIL": "فایل کوین", "ICP": "اینترنت کامپیوتر",
    "RENDER": "رندر", "FET": "فچ ای آی", "TAO": "تائو", "WIF": "ویف", "BONK": "بونک",
    "FLOKI": "فلوکی", "NOT": "نات کوین نات", "DOGS": "داگز", "HMSTR": "همستر",
    "KAS": "کاسپا", "XLM": "استلار", "ETC": "اتریوم کلاسیک", "ALGO": "الگوراند",
    "SAND": "سندباکس", "MANA": "مانا", "GALA": "گالا", "INJ": "اینجکتیو", "SEI": "سی",
    "TIA": "سلستیا", "AAVE": "آوه", "MKR": "میکر", "CRV": "کرو", "LDO": "لیدو",
    "PAXG": "پکس گلد طلا", "ENA": "اتنا", "TRUMP": "ترامپ", "ONDO": "اوندو", "WLD": "ورلد کوین"
}

def get_conn():
    c = sqlite3.connect(DB_FILE)
    c.execute("CREATE TABLE IF NOT EXISTS portfolio (id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT, market TEXT, quantity REAL, avg_buy_price_toman REAL, created_at TEXT)")
    c.commit(); return c

HORIZON_SPECS = {
    "H1_DAILY": {"label": "روزانه", "min_bars": 15, "vol_scale": 1.4},
    "H2_WEEKLY": {"label": "هفتگی", "min_bars": 25, "vol_scale": 3.2},
    "H3_MONTHLY": {"label": "ماهانه", "min_bars": 45, "vol_scale": 6.5},
    "H4_120D": {"label": "۱۲۰ روزه", "min_bars": 120, "vol_scale": 12.0},
}

CRYPTO_CACHE: Dict[str, Any] = {"ts": 0, "items": [], "source": "NOT_LOADED"}
BOURSE_CACHE: Dict[str, Any] = {"ts": 0, "items": [], "source": "NOT_LOADED", "key_used": ""}
MACRO_CACHE: Dict[str, Any] = {"ts": 0, "usdt_toman": None, "usdt_source": "NOT_LOADED", "fx_rates": {}, "fx_source": "NOT_LOADED", "fng": None, "key_used": ""}
CANDLE_CACHE: Dict[str, Dict[str, Any]] = {}

def enrich_comparison(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for it in items:
        t, y = _f(it.get("today")), _f(it.get("yesterday"))
        if t is None: out.append({**it, "diff": None, "change_pct": None}); continue
        yv = y if (y is not None and y > 0) else t
        out.append({**it, "diff": round(t - yv, 6), "change_pct": round(((t - yv) / yv * 100.0) if yv > 0 else 0.0, 2)})
    return out

async def _probe_usdt_toman(brs_key: str) -> Tuple[Optional[float], str]:
    diag = []
    async with httpx.AsyncClient(timeout=3.5, headers=BRSAPI_HEADERS) as client:
        async def t_nb():
            try:
                r = await client.get("https://apiv2.nobitex.ir/v3/orderbook/USDTIRT")
                p = _f(r.json().get("lastTradePrice")) if r.status_code == 200 else None
                return (round(p/10.0, 1), "LIVE_NOBITEX_V3") if (p and p > 10000) else (None, f"NB:{r.status_code}")
            except Exception as e: return None, f"NB:{type(e).__name__}"
        async def t_wx():
            try:
                r = await client.get("https://api.wallex.ir/v1/markets")
                p = _f((((r.json().get("result") or {}).get("symbols") or {}).get("USDTTMN") or {}).get("stats", {}).get("lastPrice")) if r.status_code == 200 else None
                return (round(p, 1), "LIVE_WALLEX") if (p and p > 1000) else (None, f"WX:{r.status_code}")
            except Exception as e: return None, f"WX:{type(e).__name__}"
        async def t_tl():
            try:
                r = await client.get("https://api.tetherland.com/currencies")
                p = _f((((r.json().get("data") or {}).get("currencies") or {}).get("USDT") or {}).get("price")) if r.status_code == 200 else None
                return (round(p, 1), "LIVE_TETHERLAND") if (p and p > 1000) else (None, f"TL:{r.status_code}")
            except Exception as e: return None, f"TL:{type(e).__name__}"
        async def t_brs():
            if not brs_key: return None, "BRS:NO_KEY"
            try:
                r = await client.get("https://Api.BrsApi.ir/Market/Gold_Currency.php", params={"key": brs_key})
                if r.status_code == 200:
                    rows = r.json().get("currency") if isinstance(r.json(), dict) else _unwrap_list(r.json())
                    for row in (rows or []):
                        if str(row.get("symbol") or "").upper() in ("USD", "USDT"):
                            p = _f(row.get("price"))
                            if p and p > 1000: return round(p, 1), "LIVE_BRSAPI_FX"
                return None, f"BRS:{r.status_code}"
            except Exception as e: return None, f"BRS:{type(e).__name__}"
        for val, src in await asyncio.gather(t_nb(), t_wx(), t_tl(), t_brs()):
            if val is not None: return val, src
            diag.append(src)
    return None, " | ".join(diag)

async def load_macro_live(brs_key: str = "", force: bool = False):
    bk = (brs_key or os.getenv("BRSAPI_KEY", "")).strip()
    now = time.time()
    if not force and MACRO_CACHE["ts"] > 0 and (now - MACRO_CACHE["ts"] < 120) and MACRO_CACHE["key_used"] == bk:
        return MACRO_CACHE
    async with httpx.AsyncClient(timeout=3.5) as c:
        async def fx():
            try:
                r = await c.get("https://open.er-api.com/v6/latest/USD")
                return (r.json().get("rates") or {}, "LIVE_OPEN_ER_API") if r.status_code == 200 else ({}, f"FX:{r.status_code}")
            except Exception as e: return {}, f"FX:{type(e).__name__}"
        async def fg():
            try:
                r = await c.get("https://api.alternative.me/fng/?limit=2")
                d = r.json().get("data") or []
                return {"value": int(d[0]["value"]), "label": d[0]["value_classification"]} if d else None
            except Exception: return None
        (uv, us), (fxr, fxs), fgv = await asyncio.gather(_probe_usdt_toman(bk), fx(), fg())
    MACRO_CACHE.update({"ts": now, "key_used": bk, "usdt_toman": uv, "usdt_source": us, "fx_rates": fxr or MACRO_CACHE["fx_rates"], "fx_source": fxs, "fng": fgv or MACRO_CACHE["fng"]})
    return MACRO_CACHE

async def load_all_crypto(force: bool = False, usdt_toman: Optional[float] = None):
    now = time.time()
    if not force and CRYPTO_CACHE["items"] and (now - CRYPTO_CACHE["ts"] < 60):
        if usdt_toman:
            for it in CRYPTO_CACHE["items"]:
                if it["symbol"] == "USDT": it["today"], it["yesterday"] = usdt_toman, usdt_toman
        return CRYPTO_CACHE
    merged, srcs = {}, []
    async with httpx.AsyncClient(timeout=4.5) as c:
        async def gb():
            try: r = await c.get("https://data-api.binance.vision/api/v3/ticker/24hr"); return r.json() if r.status_code == 200 else []
            except Exception: return []
        async def gk():
            try: r = await c.get("https://api.kucoin.com/api/v1/market/allTickers"); return ((r.json().get("data") or {}).get("ticker") or []) if r.status_code == 200 else []
            except Exception: return []
        br, kr = await asyncio.gather(gb(), gk())
        if br:
            srcs.append("BINANCE")
            for row in br:
                sym = row.get("symbol", "")
                if not sym.endswith("USDT") or any(x in sym for x in ("UPUSDT", "DOWNUSDT", "BULL", "BEAR")): continue
                base = sym[:-4]; lp, pp, qv = _f(row.get("lastPrice")), _f(row.get("prevClosePrice")), _f(row.get("quoteVolume")) or 0.0
                if lp and lp > 0 and qv > 20000:
                    fa = CRYPTO_FA_NAMES.get(base, "")
                    merged[base] = {"symbol": base, "name": f"{fa.split()[0] + ' - ' if fa else ''}{base}/USDT", "search_key": norm_fa(f"{base} {fa}"), "market": "CRYPTO", "today": lp, "yesterday": pp if (pp and pp > 0) else lp, "unit": "دلار", "quote_vol": qv}
        if kr:
            srcs.append("KUCOIN")
            for row in kr:
                sym = row.get("symbol", "")
                if not sym.endswith("-USDT"): continue
                base = sym[:-5]; lp, cr, qv = _f(row.get("last")), _f(row.get("changeRate")) or 0.0, _f(row.get("volValue")) or 0.0
                if lp and lp > 0 and base not in merged and qv > 5000:
                    fa = CRYPTO_FA_NAMES.get(base, "")
                    merged[base] = {"symbol": base, "name": f"{fa.split()[0] + ' - ' if fa else ''}{base}/USDT", "search_key": norm_fa(f"{base} {fa}"), "market": "CRYPTO", "today": lp, "yesterday": round(lp / (1.0 + cr), 8) if cr > -0.99 else lp, "unit": "دلار", "quote_vol": qv}
    merged["USDT"] = {"symbol": "USDT", "name": "تتر (دلار دیجیتال) - USDT/IRT", "search_key": norm_fa(f"USDT {CRYPTO_FA_NAMES['USDT']}"), "market": "CRYPTO", "today": usdt_toman, "yesterday": usdt_toman, "unit": "تومان", "quote_vol": 1e9}
    CRYPTO_CACHE.update({"ts": now, "items": sorted(merged.values(), key=lambda x: x["quote_vol"], reverse=True), "source": "+".join(srcs) or "NONE"})
    return CRYPTO_CACHE

async def load_all_bourse(brs_key: str = "", force: bool = False):
    bk = (brs_key or os.getenv("BRSAPI_KEY", "")).strip()
    now = time.time()
    if not force and BOURSE_CACHE["ts"] > 0 and (now - BOURSE_CACHE["ts"] < 120) and BOURSE_CACHE["key_used"] == bk:
        return BOURSE_CACHE
    items, diag = [], []
    if bk:
        try:
            async with httpx.AsyncClient(timeout=6.0, headers=BRSAPI_HEADERS) as c:
                r = await c.get("https://Api.BrsApi.ir/Tsetmc/AllSymbols.php", params={"key": bk, "type": "1"})
                diag.append(f"BRS:{r.status_code}")
                if r.status_code == 200:
                    for x in _unwrap_list(r.json()):
                        sym, tr, yr = str(x.get("l18") or "").strip(), _f(x.get("pl")) or _f(x.get("pc")), _f(x.get("py"))
                        if sym and tr and tr > 0:
                            nm = str(x.get("l30") or sym).strip()
                            items.append({"symbol": sym, "name": nm, "search_key": norm_fa(f"{sym} {nm}"), "market": "BOURSE", "ins_code": str(x.get("id") or ""), "today": round(tr/10.0, 2), "yesterday": round((yr or tr)/10.0, 2), "unit": "تومان", "pe": _f(x.get("pe")), "eps": _f(x.get("eps")), "tvol": _f(x.get("tvol")) or 0.0})
                    if items: BOURSE_CACHE.update({"ts": now, "items": items, "source": f"LIVE_BRSAPI ({len(items)})", "key_used": bk}); return BOURSE_CACHE
        except Exception as e: diag.append(f"BRS_ERR:{type(e).__name__}")
    else: diag.append("BRS_KEY:EMPTY")
    async with httpx.AsyncClient(timeout=2.0, headers=TSETMC_HEADERS) as c:
        try:
            pt = "&".join(f"paperTypes%5B{i}%5D={i+1}" for i in range(9))
            r = await c.get(f"https://cdn.tsetmc.com/api/ClosingPrice/GetMarketWatch?market=0&{pt}&showTraded=false&withBestLimits=false&hEven=0&RefID=0")
            if r.status_code == 200:
                for x in (r.json().get("marketwatch") or []):
                    sym, tr = str(x.get("lVal18AFC") or "").strip(), _f(x.get("pClosing")) or _f(x.get("pDrCotVal"))
                    if sym and tr and tr > 0:
                        nm = str(x.get("lVal30") or sym).strip()
                        items.append({"symbol": sym, "name": nm, "search_key": norm_fa(f"{sym} {nm}"), "market": "BOURSE", "ins_code": str(x.get("insCode") or ""), "today": round(tr/10.0, 2), "yesterday": round((_f(x.get("priceYesterday")) or tr)/10.0, 2), "unit": "تومان", "pe": None, "eps": None, "tvol": _f(x.get("qTotTran5J")) or 0.0})
                if len(items) > 50: BOURSE_CACHE.update({"ts": now, "items": items, "source": f"LIVE_TSETMC ({len(items)})", "key_used": bk}); return BOURSE_CACHE
        except Exception as e: diag.append(f"TSETMC:{type(e).__name__}")
    BOURSE_CACHE.update({"ts": now, "items": items, "source": " | ".join(diag), "key_used": bk})
    return BOURSE_CACHE

def _clean_sort_candles(raw: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    by_t = {int(c["time"]): c for c in raw if c.get("time") and c["close"] > 0 and c["open"] > 0 and c["high"] >= c["low"]}
    return [by_t[k] for k in sorted(by_t.keys())]

async def fetch_180_candles(symbol: str, market: str, item: Dict[str, Any], brs_key: str = "") -> Dict[str, Any]:
    bk = (brs_key or os.getenv("BRSAPI_KEY", "")).strip()
    ckey = f"{market}:{norm_fa(symbol)}:{bk[:6]}"
    now = time.time()
    if ckey in CANDLE_CACHE and (now - CANDLE_CACHE[ckey]["ts"] < 300): return CANDLE_CACHE[ckey]
    candles, diag = [], []
    if market == "CRYPTO" and symbol.upper() == "USDT":
        to_ts, from_ts = int(now), int(now) - 185 * 86400
        async with httpx.AsyncClient(timeout=4.0, headers=BRSAPI_HEADERS) as c:
            try:
                r = await c.get(f"https://apiv2.nobitex.ir/market/udf/history?symbol=USDTIRT&resolution=D&from={from_ts}&to={to_ts}")
                if r.status_code == 200 and r.json().get("s") == "ok":
                    d = r.json()
                    candles = _clean_sort_candles([{"time": int(t), "open": float(o)/10.0, "high": float(h)/10.0, "low": float(l)/10.0, "close": float(cl)/10.0, "vol": float(v)} for t,o,h,l,cl,v in zip(d.get("t",[]),d.get("o",[]),d.get("h",[]),d.get("l",[]),d.get("c",[]),d.get("v",[]))])[-180:]
                    if candles: CANDLE_CACHE[ckey] = {"ts": now, "source": "LIVE_NOBITEX_1D", "candles": candles}; return CANDLE_CACHE[ckey]
            except Exception as e: diag.append(f"NB:{type(e).__name__}")
    elif market == "CRYPTO":
        async with httpx.AsyncClient(timeout=4.0) as c:
            try:
                r = await c.get(f"https://data-api.binance.vision/api/v3/klines?symbol={symbol.upper()}USDT&interval=1d&limit=180")
                if r.status_code == 200 and isinstance(r.json(), list):
                    candles = _clean_sort_candles([{"time": int(k[0]/1000), "open": float(k[1]), "high": float(k[2]), "low": float(k[3]), "close": float(k[4]), "vol": float(k[5])} for k in r.json()])
                    if candles: CANDLE_CACHE[ckey] = {"ts": now, "source": "LIVE_BINANCE_1D", "candles": candles}; return CANDLE_CACHE[ckey]
            except Exception as e: diag.append(f"BIN:{type(e).__name__}")
            try:
                r2 = await c.get(f"https://api.kucoin.com/api/v1/market/candles?symbol={symbol.upper()}-USDT&type=1day")
                if r2.status_code == 200:
                    candles = _clean_sort_candles([{"time": int(k[0]), "open": float(k[1]), "close": float(k[2]), "high": float(k[3]), "low": float(k[4]), "vol": float(k[5])} for k in (r2.json().get("data") or [])[:180]])
                    if candles: CANDLE_CACHE[ckey] = {"ts": now, "source": "LIVE_KUCOIN_1D", "candles": candles}; return CANDLE_CACHE[ckey]
            except Exception as e: diag.append(f"KUC:{type(e).__name__}")
    elif market == "BOURSE" and bk:
        try:
            async with httpx.AsyncClient(timeout=6.0, headers=BRSAPI_HEADERS) as c:
                rh = await c.get("https://Api.BrsApi.ir/Tsetmc/History.php", params={"key": bk, "type": "0", "l18": symbol})
                if rh.status_code == 200:
                    raw = []
                    for row in _unwrap_list(rh.json()):
                        ts = parse_candle_timestamp(row.get("date_g") or row.get("dEven") or row.get("date") or row.get("d"))
                        cl = _f(row.get("pc")) or _f(row.get("pl")) or _f(row.get("pClosing")) or _f(row.get("close"))
                        if ts and cl and cl > 0:
                            ct = cl/10.0; ot = (_f(row.get("pf")) or cl)/10.0; ht = (_f(row.get("pmax")) or cl)/10.0; lt = (_f(row.get("pmin")) or cl)/10.0
                            raw.append({"time": ts, "open": ot, "high": max(ht, ot, ct), "low": min(lt, ot, ct), "close": ct, "vol": _f(row.get("tvol")) or 0.0})
                    candles = _clean_sort_candles(raw)[-180:]
                    if candles: CANDLE_CACHE[ckey] = {"ts": now, "source": "LIVE_BRSAPI_1D", "candles": candles}; return CANDLE_CACHE[ckey]
        except Exception as e: diag.append(f"BRS:{type(e).__name__}")
    return {"ts": now, "source": " | ".join(diag) or "NO_DATA", "candles": []}

# ==========================================
# اندیکاتورها + فاز ۲: واگرایی، ۱۴ الگوی کندل تریدینگ‌ویو، پول هوشمند و یکپارچگی
# ==========================================
def calc_ema(vals: List[float], period: int) -> List[float]:
    k = 2.0 / (period + 1); out = [vals[0]]
    for v in vals[1:]: out.append(v * k + out[-1] * (1.0 - k))
    return out

def calc_wilder_rsi_points(candles: List[Dict[str, Any]], period: int = 14) -> List[Dict[str, Any]]:
    n = len(candles)
    if n <= period: return []
    closes = [c["close"] for c in candles]
    gains = [max(closes[i] - closes[i - 1], 0.0) for i in range(1, n)]
    losses = [max(closes[i - 1] - closes[i], 0.0) for i in range(1, n)]
    ag, al = sum(gains[:period]) / period, sum(losses[:period]) / period
    _rsi = lambda g, l: (100.0 if g > 0 else 50.0) if l == 0 else round(100.0 - 100.0 / (1.0 + g / l), 2)
    pts = [{"time": candles[period]["time"], "value": _rsi(ag, al)}]
    for k in range(period, len(gains)):
        ag, al = (ag * (period - 1) + gains[k]) / period, (al * (period - 1) + losses[k]) / period
        pts.append({"time": candles[k + 1]["time"], "value": _rsi(ag, al)})
    return pts

def calc_bollinger(closes: List[float], period: int = 20, mult: float = 2.0):
    up, lo = [], []
    for i in range(len(closes)):
        w = closes[max(0, i - period + 1):i + 1]; m = sum(w) / len(w)
        sd = math.sqrt(sum((x - m) ** 2 for x in w) / len(w))
        up.append(round(m + mult * sd, 6)); lo.append(round(m - mult * sd, 6))
    return up, lo

def detect_price_action(candles: List[Dict[str, Any]]):
    markers, n = [], len(candles); lph = lpl = None; sups, ress = [], []
    for i in range(2, n - 2):
        h, l = candles[i]["high"], candles[i]["low"]
        if h > max(candles[i-2]["high"], candles[i-1]["high"], candles[i+1]["high"], candles[i+2]["high"]):
            lbl = "HH" if (lph is None or h > lph) else "LH"; lph = h; ress.append(h)
            markers.append({"time": candles[i]["time"], "position": "aboveBar", "color": "#fbbf24", "shape": "circle", "text": lbl})
        if l < min(candles[i-2]["low"], candles[i-1]["low"], candles[i+1]["low"], candles[i+2]["low"]):
            lbl = "HL" if (lpl is None or l > lpl) else "LL"; lpl = l; sups.append(l)
            markers.append({"time": candles[i]["time"], "position": "belowBar", "color": "#38bdf8", "shape": "circle", "text": lbl})
    markers.sort(key=lambda m: m["time"])
    return markers[-30:], (round(sups[-1], 6) if sups else round(min(x["low"] for x in candles[-30:]), 6)), (round(ress[-1], 6) if ress else round(max(x["high"] for x in candles[-30:]), 6))

def detect_patterns_and_channel(candles: List[Dict[str, Any]]) -> Dict[str, Any]:
    if len(candles) < 20: return {"available": False, "pattern_name": "داده ناکافی", "bias": "NEUTRAL"}
    win = candles[-35:] if len(candles) >= 35 else candles; m_n = len(win)
    closes, highs, lows = [c["close"] for c in win], [c["high"] for c in win], [c["low"] for c in win]
    xm, ym = (m_n - 1) / 2.0, sum(closes) / m_n
    slope = sum((i - xm) * (closes[i] - ym) for i in range(m_n)) / (sum((i - xm) ** 2 for i in range(m_n)) or 1.0)
    inter = ym - slope * xm; spct = (slope / max(ym, 1e-12)) * 100.0
    ud = max(highs[i] - (slope * i + inter) for i in range(m_n)); ld = max((slope * i + inter) - lows[i] for i in range(m_n))
    us, ue = round(inter + ud, 6), round(slope * (m_n - 1) + inter + ud, 6)
    ls, le = round(inter - ld, 6), round(slope * (m_n - 1) + inter - ld, 6)
    half = m_n // 2; h1, h2 = max(highs[:half]), max(highs[half:]); l1, l2 = min(lows[:half]), min(lows[half:])
    r1, r2 = h1 - l1, h2 - l2
    pole = candles[-45:-15] if len(candles) >= 45 else candles[:max(1, len(candles) - 15)]
    pm = ((pole[-1]["close"] - pole[0]["close"]) / max(pole[0]["close"], 1e-12)) * 100.0
    ph = max(max(c["high"] for c in pole) - min(c["low"] for c in pole), 0.0)
    lu0, lu1, ll0, ll1 = us, ue, ls, le
    if h2 < h1 * 0.995 and l2 > l1 * 1.005 and r2 < r1 * 0.78:
        nm, bs, lu0, lu1, ll0, ll1, brk, tgt = "مثلث فشردگی", "NEUTRAL", round(h1, 6), round(h2, 6), round(l1, 6), round(l2, 6), round(h2, 6), round(h2 + r1 * 0.75, 6)
        ds = f"فشردگی بین {ll1} و {lu1}؛ آماده شکست."
    elif pm >= 10.0 and -0.85 <= spct <= 0.15 and (ue - le) < ph * 0.55:
        nm, bs, brk, tgt, ds = "پرچم صعودی", "BULLISH", ue, round(ue + ph * 0.65, 6), f"رشد قبلی (+{round(pm,1)}%)؛ شکست {ue} ماشه صعود."
    elif pm <= -10.0 and -0.15 <= spct <= 0.85 and (ue - le) < ph * 0.55:
        nm, bs, brk, tgt, ds = "پرچم نزولی", "BEARISH", le, round(max(le - ph * 0.65, le * 0.35), 6), f"ریزش قبلی ({round(pm,1)}%)؛ شکست کف {le} خطرناک است."
    elif spct > 0.12:
        nm, bs, brk, tgt, ds = "کانال صعودی", "BULLISH", ue, round(ue + (ue - le) * 0.5, 6), f"شیب +{round(spct,2)}%/روز؛ حمایت {le}، سقف {ue}."
    elif spct < -0.12:
        nm, bs, brk, tgt, ds = "کانال نزولی", "BEARISH", ue, round(ue + (ue - le) * 0.5, 6), f"شیب {round(spct,2)}%/روز؛ خروج با شکست سقف {ue}."
    else:
        nm, bs, brk, tgt, ds = "کانال رنج", "NEUTRAL", ue, round(ue + (ue - le) * 0.6, 6), f"نوسان بین {le} و {ue}."
    return {"available": True, "pattern_name": nm, "bias": bs, "description": ds,
            "upper_line": [{"time": win[0]["time"], "value": lu0}, {"time": win[-1]["time"], "value": lu1}],
            "lower_line": [{"time": win[0]["time"], "value": ll0}, {"time": win[-1]["time"], "value": ll1}],
            "breakout_price": brk, "pattern_target": tgt}

# مورد ۲: تشخیص واگرایی مثبت و منفی (عادی و مخفی) روی قیمت و RSI
def detect_divergences(candles: List[Dict[str, Any]], rsi_pts: List[Dict[str, Any]]) -> Dict[str, Any]:
    if len(candles) < 30 or len(rsi_pts) < 12:
        return {"found": False, "bias": "NEUTRAL", "summary": "داده برای واگرایی کافی نیست", "items": []}
    rmap = {p["time"]: p["value"] for p in rsi_pts}
    win = candles[-70:]
    lows, highs = [], []
    for i in range(2, len(win) - 2):
        t = win[i]["time"]
        if t not in rmap: continue
        if win[i]["low"] <= min(win[i-2]["low"], win[i-1]["low"], win[i+1]["low"], win[i+2]["low"]):
            lows.append((t, win[i]["low"], rmap[t]))
        if win[i]["high"] >= max(win[i-2]["high"], win[i-1]["high"], win[i+1]["high"], win[i+2]["high"]):
            highs.append((t, win[i]["high"], rmap[t]))
    items = []
    if len(lows) >= 2:
        p1, p2 = lows[-2], lows[-1]
        if p2[1] < p1[1] * 0.995 and p2[2] > p1[2] + 2.0:
            items.append({"type": "BULLISH_REGULAR", "title": "واگرایی مثبت عادی (RD+)", "color": "#10b981",
                          "desc": f"قیمت کف پایین‌تر زد ولی RSI کف بالاتر ساخت ({p1[2]}⬅{p2[2]})؛ هشدار برگشت صعودی.",
                          "price_line": [{"time": p1[0], "value": p1[1]}, {"time": p2[0], "value": p2[1]}],
                          "rsi_line": [{"time": p1[0], "value": p1[2]}, {"time": p2[0], "value": p2[2]}]})
        elif p2[1] > p1[1] * 1.005 and p2[2] < p1[2] - 2.0:
            items.append({"type": "BULLISH_HIDDEN", "title": "واگرایی مثبت مخفی (HD+)", "color": "#22c55e",
                          "desc": "قیمت کف بالاتر زد ولی RSI پایین‌تر آمد؛ تایید ادامه روند صعودی.",
                          "price_line": [{"time": p1[0], "value": p1[1]}, {"time": p2[0], "value": p2[1]}],
                          "rsi_line": [{"time": p1[0], "value": p1[2]}, {"time": p2[0], "value": p2[2]}]})
    if len(highs) >= 2:
        q1, q2 = highs[-2], highs[-1]
        if q2[1] > q1[1] * 1.005 and q2[2] < q1[2] - 2.0:
            items.append({"type": "BEARISH_REGULAR", "title": "واگرایی منفی عادی (RD-)", "color": "#ef4444",
                          "desc": f"قیمت سقف بالاتر زد ولی RSI سقف پایین‌تر ساخت ({q1[2]}⬅{q2[2]})؛ هشدار ضعف خریدار.",
                          "price_line": [{"time": q1[0], "value": q1[1]}, {"time": q2[0], "value": q2[1]}],
                          "rsi_line": [{"time": q1[0], "value": q1[2]}, {"time": q2[0], "value": q2[2]}]})
        elif q2[1] < q1[1] * 0.995 and q2[2] > q1[2] + 2.0:
            items.append({"type": "BEARISH_HIDDEN", "title": "واگرایی منفی مخفی (HD-)", "color": "#f43f5e",
                          "desc": "قیمت سقف پایین‌تر زد ولی RSI بالاتر رفت؛ تایید ادامه روند نزولی.",
                          "price_line": [{"time": q1[0], "value": q1[1]}, {"time": q2[0], "value": q2[1]}],
                          "rsi_line": [{"time": q1[0], "value": q1[2]}, {"time": q2[0], "value": q2[2]}]})
    if not items: return {"found": False, "bias": "NEUTRAL", "summary": "واگرایی معتبری در پیوت‌های اخیر دیده نشد.", "items": []}
    bs = "BULLISH" if all("BULLISH" in x["type"] for x in items) else ("BEARISH" if all("BEARISH" in x["type"] for x in items) else "MIXED")
    return {"found": True, "bias": bs, "summary": " | ".join(x["title"] for x in items), "items": items}

# مورد ۴: تحلیل ۱۶ الگوی کندل‌استیک مثل تریدینگ‌ویو
def analyze_candlesticks_tv(candles: List[Dict[str, Any]]) -> Dict[str, Any]:
    if len(candles) < 3: return {"bias": "NEUTRAL", "bias_fa": "خنثی", "score": 0, "patterns": []}
    def _i(c):
        b = abs(c["close"] - c["open"]); r = max(c["high"] - c["low"], 1e-12)
        return c["open"], c["close"], b, r, c["high"] - max(c["open"], c["close"]), min(c["open"], c["close"]) - c["low"], c["close"] > c["open"], c["close"] < c["open"]
    o2, cl2, b2, r2, uw2, lw2, u2, d2 = _i(candles[-3])
    o1, cl1, b1, r1, uw1, lw1, u1, d1 = _i(candles[-2])
    o0, cl0, b0, r0, uw0, lw0, u0, d0 = _i(candles[-1])
    dn = candles[-1]["close"] < candles[-6]["close"] if len(candles) >= 6 else d1
    up = candles[-1]["close"] > candles[-6]["close"] if len(candles) >= 6 else u1
    found = []
    if lw0 > b0 * 2.0 and uw0 < r0 * 0.2 and b0 > 0 and dn: found.append({"name": "چکش صعودی (Hammer)", "signal": 1, "desc": "حمایت خریدار در کف"})
    if uw0 > b0 * 2.0 and lw0 < r0 * 0.2 and b0 > 0 and dn: found.append({"name": "چکش معکوس", "signal": 1, "desc": "تلاش برگشت از کف"})
    if uw0 > b0 * 2.0 and lw0 < r0 * 0.2 and b0 > 0 and up: found.append({"name": "ستاره ثاقب (Shooting Star)", "signal": -1, "desc": "رد قیمت از سقف"})
    if lw0 > b0 * 2.0 and uw0 < r0 * 0.2 and b0 > 0 and up: found.append({"name": "مرد به دار آویخته", "signal": -1, "desc": "ضعف در سقف"})
    if u0 and d1 and cl0 >= o1 and o0 <= cl1 and b0 > b1: found.append({"name": "پوشای صعودی (Bullish Engulfing)", "signal": 1, "desc": "غلبه کامل خریدار"})
    if d0 and u1 and cl0 <= o1 and o0 >= cl1 and b0 > b1: found.append({"name": "پوشای نزولی (Bearish Engulfing)", "signal": -1, "desc": "غلبه کامل فروشنده"})
    if d2 and b1 < r1 * 0.35 and u0 and cl0 > (o2 + cl2) / 2.0: found.append({"name": "ستاره صبحگاهی (Morning Star)", "signal": 1, "desc": "الگوی ۳کندلی برگشت به بالا"})
    if u2 and b1 < r1 * 0.35 and d0 and cl0 < (o2 + cl2) / 2.0: found.append({"name": "ستاره شامگاهی (Evening Star)", "signal": -1, "desc": "الگوی ۳کندلی برگشت به پایین"})
    if u2 and u1 and u0 and cl0 > cl1 > cl2 and b0 > r0 * 0.5 and b1 > r1 * 0.5: found.append({"name": "سه سرباز سفید", "signal": 1, "desc": "صعود پیوسته ۳ روزه"})
    if d2 and d1 and d0 and cl0 < cl1 < cl2 and b0 > r0 * 0.5 and b1 > r1 * 0.5: found.append({"name": "سه کلاغ سیاه", "signal": -1, "desc": "نزول پیوسته ۳ روزه"})
    if d1 and u0 and o0 > cl1 and cl0 < o1 and b0 < b1 * 0.65: found.append({"name": "هارامی صعودی", "signal": 1, "desc": "توقف شتاب نزول"})
    if u1 and d0 and o0 < cl1 and cl0 > o1 and b0 < b1 * 0.65: found.append({"name": "هارامی نزولی", "signal": -1, "desc": "توقف شتاب صعود"})
    if b0 / r0 < 0.12 and lw0 > r0 * 0.6: found.append({"name": "دوجی سنجاقک", "signal": 1, "desc": "جمع‌آوری عرضه در کف"})
    if b0 / r0 < 0.12 and uw0 > r0 * 0.6: found.append({"name": "دوجی سنگ‌قبر", "signal": -1, "desc": "فشار فروش در سقف"})
    if not found:
        if u0 and b0 > r0 * 0.65: found.append({"name": "کندل قدرتمند سبز (Marubozu+)", "signal": 1, "desc": "برتری خریدار"})
        elif d0 and b0 > r0 * 0.65: found.append({"name": "کندل قدرتمند قرمز (Marubozu-)", "signal": -1, "desc": "برتری فروشنده"})
        else: found.append({"name": "کندل متعادل / خنثی", "signal": 0, "desc": "الگوی بازگشتی خاص ندارد"})
    sc = sum(x["signal"] for x in found)
    return {"bias": "BULLISH" if sc > 0 else ("BEARISH" if sc < 0 else "NEUTRAL"), "bias_fa": "مثبت" if sc > 0 else ("منفی" if sc < 0 else "خنثی"), "score": sc, "patterns": found, "summary": " | ".join(x["name"] for x in found)}

# مورد ۶: حجم ورود و خروج پول هوشمند (CMF 20 + MFI 14 + OBV)
def analyze_smart_money(candles: List[Dict[str, Any]]) -> Dict[str, Any]:
    n = len(candles)
    if n < 22: return {"available": False, "bias": "NEUTRAL", "verdict": "دیتای حجم ناکافی", "detail": ""}
    mfv = [(((c["close"] - c["low"]) - (c["high"] - c["close"])) / (c["high"] - c["low"]) if c["high"] > c["low"] else 0.0) * c["vol"] for c in candles]
    vols = [max(c["vol"], 0.0) for c in candles]
    sv20 = sum(vols[-20:])
    cmf20 = round(sum(mfv[-20:]) / sv20, 3) if sv20 > 0 else 0.0
    pmf = nmf = 0.0
    for i in range(max(1, n - 14), n):
        tp0 = (candles[i]["high"] + candles[i]["low"] + candles[i]["close"]) / 3.0
        tp1 = (candles[i-1]["high"] + candles[i-1]["low"] + candles[i-1]["close"]) / 3.0
        if tp0 > tp1: pmf += tp0 * candles[i]["vol"]
        elif tp0 < tp1: nmf += tp0 * candles[i]["vol"]
    mfi14 = 100.0 if (nmf == 0 and pmf > 0) else (50.0 if nmf == 0 else round(100.0 - 100.0 / (1.0 + pmf / nmf), 1))
    obv = [0.0]
    for i in range(1, n): obv.append(obv[-1] + (candles[i]["vol"] if candles[i]["close"] > candles[i-1]["close"] else (-candles[i]["vol"] if candles[i]["close"] < candles[i-1]["close"] else 0.0)))
    obv_up = obv[-1] > obv[-10]
    avg_v = sum(vols[-21:-1]) / 20.0 if n > 21 else sum(vols) / n
    vr = round(vols[-1] / avg_v, 2) if avg_v > 0 else 1.0
    if cmf20 >= 0.05 and obv_up:
        bs, vd = "BULLISH", "ورود پول هوشمند (انباشت 🟢)"
        dt = f"شاخص CMF={cmf20} (مثبت)، MFI={mfi14} و OBV صعودی؛ حجم امروز {vr}x میانگین است (نقدینگی در حال ورود است)."
    elif cmf20 >= 0.05 and candles[-1]["close"] < candles[-10]["close"]:
        bs, vd = "BULLISH", "خرید پنهان پول هوشمند در افت 🟢"
        dt = f"با وجود اصلاح قیمت، CMF={cmf20} مثبت است؛ نشان‌دهنده جذب فروش‌های هیجانی در کف."
    elif cmf20 <= -0.05 and not obv_up:
        bs, vd = "BEARISH", "خروج پول هوشمند (توزیع 🔴)"
        dt = f"شاخص CMF={cmf20} (منفی)، MFI={mfi14} و OBV نزولی است؛ نقدینگی در حال خروج است و رشدها پرریسک‌اند."
    else:
        bs, vd = "NEUTRAL", "جریان پول متعادل 🟡"
        dt = f"CMF={cmf20} و MFI={mfi14} (حجم {vr}x میانگین)؛ هنوز ورود یا خروج سنگین قطعی نشده است."
    return {"available": True, "bias": bs, "cmf20": cmf20, "mfi14": mfi14, "vol_ratio": vr, "verdict": vd, "detail": dt}

# مورد ۵: موتور یکپارچگی ضد تناقض
def build_unified_coherence(contracts: dict, pat: dict, div: dict, cs: dict, sm: dict) -> Dict[str, Any]:
    bull = bear = 0
    for hk in ("H1_DAILY", "H2_WEEKLY", "H3_MONTHLY", "H4_120D"):
        if contracts[hk]["is_bullish"]: bull += 15
        elif contracts[hk]["tone"] == "rose": bear += 15
    for src in (pat.get("bias"), div.get("bias"), cs.get("bias"), sm.get("bias")):
        if src == "BULLISH": bull += 12
        elif src == "BEARISH": bear += 12
    conflicts = []
    if contracts["H1_DAILY"]["is_bullish"] and contracts["H4_120D"]["evaluatable"] and not contracts["H4_120D"]["is_bullish"]:
        conflicts.append("تضاد تایم‌فریم: کوتاه‌مدت (روزانه) مثبت است ولی روند ۱۲۰ روزه هنوز صعودی نشده؛ یعنی فعلاً نوسانِ اصلاحی است نه روند بلندمدت.")
    if (contracts["H1_DAILY"]["is_bullish"] or pat.get("bias") == "BULLISH") and div.get("bias") == "BEARISH":
        conflicts.append("هشدار تضاد: ظاهر چارت صعودی است ولی واگرایی منفی RSI ضعف شتاب خرید را لو می‌دهد.")
    if contracts["H1_DAILY"]["is_bullish"] and sm.get("bias") == "BEARISH":
        conflicts.append("هشدار نقدینگی: کندل کوتاه‌مدت سبز است اما جریان پول هوشمند (CMF/OBV) هنوز خروج سرمایه نشان می‌دهد.")
    if cs.get("bias") == "BEARISH" and contracts["H1_DAILY"]["is_bullish"]:
        conflicts.append("الگوی کندل آخر منفی است؛ تا تایید کندل سبز بعدی برای خرید عجله نکنید.")
    if not conflicts:
        conflicts.append("یکپارچگی کامل: جهت تایم‌فریم‌ها، کندل‌ها، واگرایی و پول هوشمند با هم هم‌راستا هستند.")
    net = bull - bear
    vd = "برآیند یکپارچه: صعودی هم‌سو 🟢" if (net >= 25 and len(conflicts) == 1 and "یکپارچگی" in conflicts[0]) else ("برآیند یکپارچه: نزولی / پرریسک 🔴" if net <= -25 else "برآیند یکپارچه: احتیاط / دارای تضاد زمانی 🟡")
    return {"verdict": vd, "score": net, "conflicts": conflicts}

def run_backtest_180d(candles: List[Dict[str, Any]], market: str) -> Dict[str, Any]:
    n = len(candles)
    if n < 55: return {"sufficient": False, "trades_count": 0, "reason": f"حداقل ۵۵ کندل لازم است ({n})"}
    closes, highs, lows = [c["close"] for c in candles], [c["high"] for c in candles], [c["low"] for c in candles]
    ema20, ema12, ema26 = calc_ema(closes, 20), calc_ema(closes, 12), calc_ema(closes, 26)
    macd_l = [a - b for a, b in zip(ema12, ema26)]; sig_l = calc_ema(macd_l, 9)
    rmap = {p["time"]: p["value"] for p in calc_wilder_rsi_points(candles, 14)}
    fee = 1.25 if market == "BOURSE" else 0.20
    trades, i = [], 30
    while i < n - 8:
        rv = rmap.get(candles[i]["time"], 50.0)
        mc = macd_l[i] > sig_l[i] and macd_l[i-1] <= sig_l[i-1] and closes[i] > ema20[i]
        er = closes[i] > ema20[i] and closes[i-1] <= ema20[i-1] and macd_l[i] > sig_l[i]
        if (mc or er) and 38.0 <= rv <= 68.0:
            en = closes[i]
            rets = [abs(closes[k]-closes[k-1])/closes[k-1] for k in range(max(1, i-14), i+1) if closes[k-1] > 0]
            atr = max(min(sum(rets)/max(len(rets), 1), 0.06), 0.012)
            tp, sl = en * (1.0 + atr * 2.6), en * (1.0 - atr * 1.4)
            ex, eidx = closes[min(i+12, n-1)], min(i+12, n-1)
            for j in range(i+1, min(i+13, n)):
                if lows[j] <= sl: ex, eidx = sl, j; break
                if highs[j] >= tp: ex, eidx = tp, j; break
            trades.append(round(((ex - en)/en)*100.0 - fee, 2)); i = eidx + 1
        else: i += 1
    if len(trades) < 3: return {"sufficient": False, "trades_count": len(trades), "reason": f"سیگنال تاریخی کم ({len(trades)})"}
    wins = sum(1 for x in trades if x > 0); wr = round(wins/len(trades)*100.0, 1); ar = round(sum(trades)/len(trades), 2)
    return {"sufficient": True, "trades_count": len(trades), "win_rate_pct": wr, "avg_return_pct": ar, "summary": f"بک‌تست ۱۸۰ روزه: {wr}% برد ({wins} از {len(trades)} معامله) | میانگین: {'+' if ar>=0 else ''}{ar}%"}

def evaluate_horizon(hk, spec, n, price, dvol, fee, closes, ema9, ema20, ema50, macd_l, sig_l, hist_l, rsi_now, pa_sup, pa_res):
    if n < spec["min_bars"] or price <= 0 or rsi_now is None:
        return {"horizon": hk, "label": spec["label"], "evaluatable": False, "icon": "⛔", "tone": "rose", "is_bullish": False, "available_bars": n, "required_min_bars": spec["min_bars"], "action": "قابل ارزیابی نیست", "target": None, "stop": None, "net_return_pct": None, "net_risk_pct": None, "rr": None}
    atp, asl = price * (1.0 + min(dvol * spec["vol_scale"] * 1.45, 0.65)), price * (1.0 - min(dvol * spec["vol_scale"] * 0.72, 0.28))
    bull = False
    if hk == "H1_DAILY":
        sl_v = round(max(asl, pa_sup * 0.992), 6) if 0 < pa_sup < price else round(asl, 6)
        tp = round(min(atp, pa_res * 1.02) if pa_res > price * 1.015 else atp, 6)
        hr = len(hist_l) >= 2 and hist_l[-1] > hist_l[-2]
        if rsi_now >= 75: act, ic, tn = "سیو سود (اشباع)", "🟡", "amber"
        elif price > ema9[-1] and (ema9[-1] > ema20[-1] or hr) and rsi_now < 72: act, ic, tn, bull = "صعود کوتاه‌مدت (خرید)", "🟢", "emerald", True
        elif rsi_now <= 32 and hr: act, ic, tn, bull = "برگشت از کف", "🟢", "emerald", True
        elif price < ema9[-1] and not hr: act, ic, tn = "فشار فروش روزانه", "🔴", "rose"
        else: act, ic, tn = "نوسان رنج روزانه", "🟡", "amber"
    elif hk == "H2_WEEKLY":
        sl_v = round(max(asl, pa_sup * 0.99), 6) if 0 < pa_sup < price else round(asl, 6); tp = round(atp, 6)
        e20u = len(ema20) >= 6 and ema20[-1] > ema20[-6]
        if rsi_now >= 76: act, ic, tn = "اشباع هفتگی", "🟡", "amber"
        elif price > ema20[-1] and e20u and macd_l[-1] > sig_l[-1]: act, ic, tn, bull = "هفتگی صعودی (خرید)", "🟢", "emerald", True
        elif price < ema20[-1] and not e20u and macd_l[-1] < sig_l[-1]: act, ic, tn = "هفتگی نزولی (فروش)", "🔴", "rose"
        else: act, ic, tn = "تثبیت هفتگی", "🟡", "amber"
    elif hk == "H3_MONTHLY":
        sl_v, tp = round(asl, 6), round(atp, 6)
        r30 = ((price - closes[-30]) / closes[-30] * 100.0) if len(closes) >= 30 and closes[-30] > 0 else 0.0
        if price > ema50[-1] and ema20[-1] > ema50[-1] and r30 > 0: act, ic, tn, bull = f"ماهانه صعودی (+{round(r30,1)}%)", "🟢", "emerald", True
        elif price < ema50[-1] and r30 < -3.0: act, ic, tn = f"ماهانه نزولی ({round(r30,1)}%)", "🔴", "rose"
        else: act, ic, tn = "ماهانه رنج / تغییر فاز", "🟡", "amber"
    else:
        sl_v, tp = round(asl, 6), round(atp, 6)
        sma100 = sum(closes[-100:]) / 100.0 if len(closes) >= 100 else sum(closes) / len(closes)
        r120 = ((price - closes[-120]) / closes[-120] * 100.0) if len(closes) >= 120 and closes[-120] > 0 else 0.0
        e50u = len(ema50) >= 21 and ema50[-1] > ema50[-21]
        if price > sma100 and e50u and r120 > 0: act, ic, tn, bull = f"۱۲۰روزه صعودی (+{round(r120,1)}%)", "🟢", "emerald", True
        elif price < sma100 and r120 < 0: act, ic, tn = f"۱۲۰روزه نزولی ({round(r120,1)}%)", "🔴", "rose"
        else: act, ic, tn = "۱۲۰روزه خنثی", "🟡", "amber"
    nr, nsk = round(((tp - price)/price*100.0)-fee, 2), round(((price - sl_v)/price*100.0)+fee, 2)
    rr = round(nr / nsk, 2) if nsk > 0 else 0.0
    if bull and rr < 1.0: act, ic, tn, bull = "نزدیک مقاومت (R/R کم)", "🟡", "amber", False
    return {"horizon": hk, "label": spec["label"], "evaluatable": True, "icon": ic, "tone": tn, "is_bullish": bull, "available_bars": n, "required_min_bars": spec["min_bars"], "action": act, "target": tp, "stop": sl_v, "net_return_pct": nr, "net_risk_pct": nsk, "rr": rr}

def analyze_full(symbol: str, market: str, item: Dict[str, Any], candles: List[Dict[str, Any]], fng_data: Optional[dict] = None):
    n = len(candles); closes, highs, lows, vols = [c["close"] for c in candles], [c["high"] for c in candles], [c["low"] for c in candles], [c["vol"] for c in candles]
    price = closes[-1]
    rets = [abs(closes[i] - closes[i - 1]) / closes[i - 1] for i in range(1, n) if closes[i - 1] > 0]
    dvol = max(min((sum(rets[-20:]) / len(rets[-20:])) if rets else 0.02, 0.08), 0.01)
    rsi_pts = calc_wilder_rsi_points(candles, 14); rsi_now = rsi_pts[-1]["value"] if rsi_pts else None
    ema9, ema12, ema26, ema20, ema50 = [round(x, 6) for x in calc_ema(closes, 9)], calc_ema(closes, 12), calc_ema(closes, 26), [round(x, 6) for x in calc_ema(closes, 20)], [round(x, 6) for x in calc_ema(closes, 50)]
    bb_up, bb_lo = calc_bollinger(closes, 20, 2.0)
    macd_l = [round(a - b, 6) for a, b in zip(ema12, ema26)]; sig_l = [round(x, 6) for x in calc_ema(macd_l, 9)]; hist_l = [round(m - s, 6) for m, s in zip(macd_l, sig_l)]
    sh, sl = max(highs[-120:]), min(lows[-120:]); diff = sh - sl
    fib = {"0.0 (سقف)": round(sh, 6), "0.236": round(sh - 0.236*diff, 6), "0.382": round(sh - 0.382*diff, 6), "0.500": round(sh - 0.500*diff, 6), "0.618 (طلایی)": round(sh - 0.618*diff, 6), "1.0 (کف)": round(sl, 6)}
    pa_markers, pa_sup, pa_res = detect_price_action(candles)
    patterns = detect_patterns_and_channel(candles)
    divergences = detect_divergences(candles, rsi_pts)
    candlesticks = analyze_candlesticks_tv(candles)
    smart_money = analyze_smart_money(candles)
    backtest = run_backtest_180d(candles, market)
    structure = "صعودی (بالای EMA20 و EMA50)" if price > ema20[-1] > ema50[-1] else ("نزولی (زیر EMA20 و EMA50)" if price < ema20[-1] < ema50[-1] else "رنج / تغییر فاز")
    fee = 1.25 if market == "BOURSE" else 0.20
    contracts, hits = {}, 0
    for hk, sp in HORIZON_SPECS.items():
        cr = evaluate_horizon(hk, sp, n, price, dvol, fee, closes, ema9, ema20, ema50, macd_l, sig_l, hist_l, rsi_now, pa_sup, pa_res)
        if cr["is_bullish"]: hits += 1
        contracts[hk] = cr
    coherence = build_unified_coherence(contracts, patterns, divergences, candlesticks, smart_money)

    pe, eps = _f(item.get("pe")), _f(item.get("eps"))
    fund = (f"P/E={pe or 'نامشخص'} | EPS={eps or 'نامشخص'}" if market == "BOURSE" else f"حجم ۲۴ساعته: {round(float(item.get('quote_vol') or 0)/1e6, 2)}M$")
    fng_t = f" | ترس/طمع کل: {fng_data['value']}/100" if (market == "CRYPTO" and fng_data) else ""
    psych = {"mood": f"RSI={rsi_now} | جریان پول: {smart_money['verdict']}{fng_t}", "advice": coherence["conflicts"][0]}
    strategies = {"past": f"گذشته: کف {fib['1.0 (کف)']} تا سقف {fib['0.0 (سقف)']}.", "present": f"حال: {structure} | کندل: {candlesticks['bias_fa']} | الگو: {patterns['pattern_name']}.", "future": f"آینده: {patterns.get('description', '')}"}
    return {
        "price": price, "fundamental": fund, "psychology": psych, "strategies": strategies,
        "contracts": contracts, "confluence": f"{hits}/4", "backtest": backtest,
        "divergences": divergences, "candlesticks": candlesticks, "smart_money": smart_money, "coherence": coherence,
        "chart": {
            "candles": [{"time": c["time"], "open": c["open"], "high": c["high"], "low": c["low"], "close": c["close"]} for c in candles],
            "volume": [{"time": c["time"], "value": c["vol"], "color": "rgba(16,185,129,0.35)" if c["close"] >= c["open"] else "rgba(239,68,68,0.35)"} for c in candles],
            "ema20": [{"time": candles[i]["time"], "value": ema20[i]} for i in range(n)],
            "ema50": [{"time": candles[i]["time"], "value": ema50[i]} for i in range(n)],
            "bb_upper": [{"time": candles[i]["time"], "value": bb_up[i]} for i in range(n)],
            "bb_lower": [{"time": candles[i]["time"], "value": bb_lo[i]} for i in range(n)],
            "rsi": rsi_pts, "macd": [{"time": candles[i]["time"], "value": macd_l[i]} for i in range(n)],
            "macd_signal": [{"time": candles[i]["time"], "value": sig_l[i]} for i in range(n)],
            "macd_hist": [{"time": candles[i]["time"], "value": hist_l[i], "color": "#10b981" if hist_l[i] >= 0 else "#ef4444"} for i in range(n)],
            "pa_markers": pa_markers, "pa_support": pa_sup, "pa_resistance": pa_res,
            "fib": fib, "rsi_now": rsi_now, "patterns": patterns, "divergences": divergences,
        }
    }

@app.get("/api/self-test")
async def run_self_test(brs_key: str = ""):
    checks = []
    ref_c = [44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42, 45.84, 46.08, 45.89, 46.03, 45.61, 46.28, 46.28, 46.00]
    rc = [{"time": 1700000000 + i*86400, "open": c, "high": c, "low": c, "close": c, "vol": 100} for i, c in enumerate(ref_c)]
    ro = calc_wilder_rsi_points(rc, 14)
    checks.append({"name": "Wilder RSI(14) Reference Math", "passed": len(ro) == 2 and abs(ro[0]["value"]-70.46) < 0.1 and abs(ro[1]["value"]-66.25) < 0.1, "detail": str(ro)})
    checks.append({"name": "Jalali-to-Gregorian Calendar Math", "passed": jalali_to_gregorian(1403,1,1)==(2024,3,20) and jalali_to_gregorian(1405,8,24)==(2026,11,15), "detail": "OK"})
    # تست واگرایی مثبت عادی: دو کف در قیمت که کف دوم پایین‌تر و RSI دوم بالاتر است
    div_prices = [100 - i*0.5 for i in range(25)] + [87.5 + i*1.5 for i in range(10)] + [101 - i*2.0 for i in range(8)] + [85 + i*0.8 for i in range(10)]
    dc = [{"time": 1700000000 + i*86400, "open": p, "high": p+0.5, "low": p-0.5, "close": p, "vol": 1000} for i, p in enumerate(div_prices)]
    dv = detect_divergences(dc, calc_wilder_rsi_points(dc, 14))
    checks.append({"name": "Divergence Detector (RD+)", "passed": dv["found"] and any("BULLISH" in x["type"] for x in dv["items"]), "detail": dv["summary"]})
    # تست پول هوشمند انباشت: بسته‌شدن نزدیک سقف با حجم بالا
    smc = [{"time": 1700000000 + i*86400, "open": 100+i*0.3, "high": 102+i*0.3, "low": 99+i*0.3, "close": 101.9+i*0.3, "vol": 1000+i*120} for i in range(30)]
    sm_res = analyze_smart_money(smc)
    checks.append({"name": "Smart Money Flow (CMF/MFI/OBV)", "passed": sm_res["bias"] == "BULLISH" and sm_res["cmf20"] > 0.05, "detail": f"CMF={sm_res.get('cmf20')}, MFI={sm_res.get('mfi14')}"})
    # تست الگوهای کندلی تریدینگ‌ویو (چکش صعودی پس از افت)
    hm = [{"time": 1700000000+i*86400, "open": 110-i, "high": 111-i, "low": 109-i, "close": 109.5-i, "vol": 100} for i in range(8)] + [{"time": 1700000000+8*86400, "open": 100, "high": 101.2, "low": 94, "close": 101, "vol": 500}]
    cs_res = analyze_candlesticks_tv(hm)
    checks.append({"name": "TV Candlesticks (Hammer)", "passed": cs_res["bias"] == "BULLISH", "detail": cs_res["summary"]})
    # تست یکپارچگی و ۴ بازه
    bounce = [{"time": 1700000000+i*86400, "open": (210-i*1.1 if i<110 else 89+(i-109)*0.75)-0.2, "high": (210-i*1.1 if i<110 else 89+(i-109)*0.75)+1, "low": (210-i*1.1 if i<110 else 89+(i-109)*0.75)-1, "close": (210-i*1.1 if i<110 else 89+(i-109)*0.75), "vol": 1000} for i in range(130)]
    ir = analyze_full("TEST", "CRYPTO", {"quote_vol": 1e7}, bounce)
    checks.append({"name": "4-Horizon & Coherence Gate", "passed": ir["contracts"]["H1_DAILY"]["is_bullish"] and not ir["contracts"]["H4_120D"]["is_bullish"] and len(ir["coherence"]["conflicts"])>=1, "detail": f"conf={ir['confluence']}, {ir['coherence']['verdict']}"})
    macro, b_data = await asyncio.gather(load_macro_live(brs_key, force=True), load_all_bourse(brs_key))
    c_data = await load_all_crypto(force=True, usdt_toman=macro["usdt_toman"])
    checks.append({"name": "Live Crypto & USDT-Toman", "passed": len(c_data["items"]) >= 300 and macro["usdt_toman"] is not None, "detail": f"coins={len(c_data['items'])}, usdt={macro['usdt_toman']}"})
    return {"all_math_tests_passed": all(x["passed"] for x in checks[:6]), "checks": checks}

@app.get("/api/system-status")
async def system_status(brs_key: str = ""):
    macro, b_data = await asyncio.gather(load_macro_live(brs_key), load_all_bourse(brs_key))
    c_data = await load_all_crypto(usdt_toman=macro["usdt_toman"])
    return {"crypto_count": len(c_data["items"]), "bourse_count": len(b_data["items"]), "bourse_source": b_data["source"], "usdt_toman": macro["usdt_toman"]}

@app.get("/api/search")
async def instant_search(q: str = "", brs_key: str = ""):
    qn = norm_fa(q)
    macro, b_data = await asyncio.gather(load_macro_live(brs_key), load_all_bourse(brs_key))
    c_data = await load_all_crypto(usdt_toman=macro["usdt_toman"])
    res = [{"symbol": x["symbol"], "name": x["name"], "market": "BOURSE", "today": x["today"], "unit": "تومان"} for x in b_data["items"] if not qn or qn in x["search_key"]][:15]
    res += [{"symbol": x["symbol"], "name": x["name"], "market": "CRYPTO", "today": x["today"], "unit": x["unit"]} for x in c_data["items"] if not qn or qn in x["search_key"]][:20]
    return {"results": res}

@app.get("/api/analyze")
async def analyze_endpoint(symbol: str, market: str = "AUTO", brs_key: str = ""):
    t0 = time.time(); qn = norm_fa(symbol); mkt = market.strip().upper()
    macro, b_data = await asyncio.gather(load_macro_live(brs_key), load_all_bourse(brs_key))
    c_data = await load_all_crypto(usdt_toman=macro["usdt_toman"])
    item = next((x for x in b_data["items"] if norm_fa(x["symbol"]) == qn), None) if mkt in ("AUTO", "BOURSE") else None
    if item: mkt = "BOURSE"
    if not item and mkt in ("AUTO", "CRYPTO"):
        item = next((x for x in c_data["items"] if norm_fa(x["symbol"]) == qn or qn in x["search_key"]), None)
        if item: mkt = "CRYPTO"
    if not item: return {"found": False, "elapsed_ms": round((time.time()-t0)*1000, 1)}
    cres = await fetch_180_candles(item["symbol"], mkt, item, brs_key)
    if not cres["candles"]: return {"found": True, "no_candles": True, "candle_source": cres["source"]}
    return {"found": True, "no_candles": False, "symbol": item["symbol"], "display_name": item["name"], "market": mkt, "unit": item["unit"], "bars_count": len(cres["candles"]), "elapsed_ms": round((time.time()-t0)*1000, 1), **analyze_full(item["symbol"], mkt, item, cres["candles"], macro.get("fng"))}

@app.get("/api/top10-scanner")
async def top10_scanner(brs_key: str = ""):
    c_data, b_data = await asyncio.gather(load_all_crypto(), load_all_bourse(brs_key))
    cands = [(x, "CRYPTO") for x in c_data["items"] if x.get("today") and x["symbol"] != "USDT"][:24] + [(x, "BOURSE") for x in sorted(b_data["items"], key=lambda z: z.get("tvol", 0), reverse=True)[:8]]
    cres = await asyncio.gather(*[fetch_180_candles(it["symbol"], mk, it, brs_key) for it, mk in cands])
    an = [(it, mk, analyze_full(it["symbol"], mk, it, cr["candles"])) for (it, mk), cr in zip(cands, cres) if len(cr["candles"]) >= 16]
    top10 = {}
    for hk in HORIZON_SPECS:
        v = [{"symbol": it["symbol"], "market": mk, "net_return_pct": a["contracts"][hk]["net_return_pct"], "confluence": a["confluence"], "conf_num": int(a["confluence"].split("/")[0])} for it, mk, a in an if a["contracts"][hk]["evaluatable"] and a["contracts"][hk]["is_bullish"]]
        v.sort(key=lambda z: (z["conf_num"], z["net_return_pct"] or 0), reverse=True)
        top10[hk] = v[:10]
    return top10

@app.get("/api/watchlists")
async def watchlists(brs_key: str = ""):
    macro, b_data = await asyncio.gather(load_macro_live(brs_key), load_all_bourse(brs_key))
    c_data = await load_all_crypto(usdt_toman=macro["usdt_toman"])
    ut, fxr = macro["usdt_toman"], macro["fx_rates"]
    fx = [{"symbol": k, "name": n, "today": round(ut/float(fxr[k]), 2) if ut else round(float(fxr[k]), 4), "yesterday": None, "unit": "تومان" if ut else "USD"} for k, n in [("USD","دلار"),("EUR","یورو"),("GBP","پوند"),("AED","درهم"),("TRY","لیر"),("CNY","یوان"),("CAD","کانادا"),("AUD","استرالیا"),("CHF","فرانک"),("JPY","ین"),("SAR","ریال عربستان"),("RUB","روبل"),("IQD","دینار"),("KRW","وون"),("INR","روپیه")] if fxr.get(k)]
    paxg = next((x for x in c_data["items"] if x["symbol"] == "PAXG"), None)
    metals = [{"symbol": "PAXG", "name": "انس جهانی طلا", "today": paxg["today"], "yesterday": paxg["yesterday"], "unit": "دلار"}] if paxg else []
    etfs = [x for x in b_data["items"] if any(k in x["name"] or k in x["symbol"] for k in ("صندوق", "درآمد", "اهرم", "طلا", "عیار"))][:15]
    return {"bourse": enrich_comparison(b_data["items"][:15]), "crypto": enrich_comparison(c_data["items"][:15]), "metals": enrich_comparison(metals), "etfs": enrich_comparison(etfs), "forex": enrich_comparison(fx)}

class PortfolioIn(BaseModel):
    symbol: str; market: str = "CRYPTO"; quantity: float; avg_buy_price_toman: float

@app.post("/api/portfolio")
def add_pf(item: PortfolioIn):
    c = get_conn(); c.execute("INSERT INTO portfolio (symbol, market, quantity, avg_buy_price_toman, created_at) VALUES (?,?,?,?,?)", (item.symbol.strip(), item.market.upper(), item.quantity, item.avg_buy_price_toman, datetime.now(TEHRAN_TZ).isoformat())); c.commit(); c.close(); return {"ok": True}

@app.delete("/api/portfolio/{pid}")
def del_pf(pid: int):
    c = get_conn(); c.execute("DELETE FROM portfolio WHERE id=?", (pid,)); c.commit(); c.close(); return {"ok": True}

@app.get("/api/portfolio")
async def get_pf(brs_key: str = ""):
    macro, b_data = await asyncio.gather(load_macro_live(brs_key), load_all_bourse(brs_key))
    c_data = await load_all_crypto(usdt_toman=macro["usdt_toman"]); ut = macro["usdt_toman"]
    c = get_conn(); rows = c.execute("SELECT id, symbol, market, quantity, avg_buy_price_toman FROM portfolio").fetchall(); c.close()
    out = []
    for pid, sym, mkt, qty, bp in rows:
        m = next((x for x in (b_data["items"] if mkt == "BOURSE" else c_data["items"]) if norm_fa(x["symbol"]) == norm_fa(sym)), None)
        if not m or m.get("today") is None or (mkt == "CRYPTO" and sym.upper() != "USDT" and ut is None):
            out.append({"id": pid, "symbol": sym, "market": mkt, "quantity": qty, "buy_price": bp, "current_price": None, "pnl_pct": None, "signal": "دیتای زنده موجود نیست"})
        else:
            cp = float(m["today"]) * (1.0 if (mkt == "BOURSE" or sym.upper() == "USDT") else ut)
            pnl = round((cp - bp) / bp * 100.0, 2) if bp > 0 else 0.0
            out.append({"id": pid, "symbol": sym, "market": mkt, "quantity": qty, "buy_price": bp, "current_price": round(cp, 2), "pnl_pct": pnl, "signal": "فروش (حد ضرر)" if pnl <= -6 else ("سیو سود" if pnl >= 15 else "نگهداری")})
    return out

@app.get("/", response_class=HTMLResponse)
def home():
    with open(os.path.join(BASE_DIR, "index.html"), "r", encoding="utf-8") as f: return f.read()

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
