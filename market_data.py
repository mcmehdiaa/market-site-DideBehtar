import os, time, asyncio
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple
import httpx
from news_cal import TEHRAN_TZ, build_tsetmc_url
from quant_math import _f

TSETMC_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/131.0.0.0 Safari/537.36", "Accept": "application/json", "Referer": "https://tsetmc.com/"}
BRSAPI_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 6.1; Win64; x64) Chrome/131.0.0.0 Safari/537.36 OPR/106.0.0.0", "Accept": "application/json"}

CRYPTO_FA_NAMES = {
    "USDT": "تتر دلار دیجیتال", "BTC": "بیت کوین بیتکوین", "ETH": "اتریوم اتريوم", "SOL": "سولانا سول",
    "BNB": "بایننس کوین", "XRP": "ریپل", "ADA": "کاردانو آدا", "DOGE": "دوج کوین دوج", "TRX": "ترون",
    "TON": "تون کوین تون", "AVAX": "آوالانچ", "SHIB": "شیبا", "PEPE": "پپه", "LINK": "چین لینک",
    "DOT": "پولکادات", "SUI": "سویی", "LTC": "لایت کوین", "BCH": "بیت کوین کش", "NEAR": "نیر",
    "APT": "اپتوس", "ARB": "آربیتروم", "OP": "اپتیمیزم", "POL": "پالیگان", "UNI": "یونی سواپ",
    "ATOM": "کازموس", "FIL": "فایل کوین", "ICP": "اینترنت کامپیوتر", "RENDER": "رندر", "FET": "فچ ای آی",
    "TAO": "تائو", "WIF": "ویف", "BONK": "بونک", "FLOKI": "فلوکی", "NOT": "نات کوین", "DOGS": "داگز",
    "HMSTR": "همستر", "KAS": "کاسپا", "XLM": "استلار", "PAXG": "پکس گلد طلا", "ENA": "اتنا", "TRUMP": "ترامپ"
}

CRYPTO_CACHE: Dict[str, Any] = {"ts": 0, "items": [], "source": "NOT_LOADED"}
BOURSE_CACHE: Dict[str, Any] = {"ts": 0, "items": [], "source": "NOT_LOADED", "key_used": ""}
MACRO_CACHE: Dict[str, Any] = {"ts": 0, "usdt_toman": None, "usdt_source": "NOT_LOADED", "fx_rates": {}, "fx_source": "NOT_LOADED", "fng": None, "key_used": ""}
CANDLE_CACHE: Dict[str, Dict[str, Any]] = {}

TF_BINANCE = {"1m": ("1m", 200), "5m": ("5m", 200), "15m": ("15m", 200), "1h": ("1h", 200), "4h": ("4h", 200), "1d": ("1d", 200), "1w": ("1w", 150), "1M": ("1M", 60), "1y": ("1d", 365)}
TF_KUCOIN = {"1m": "1min", "5m": "5min", "15m": "15min", "1h": "1hour", "4h": "4hour", "1d": "1day", "1w": "1week", "1M": "1week", "1y": "1day"}
TF_LABELS = {"1m": "۱ دقیقه", "5m": "۵ دقیقه", "15m": "۱۵ دقیقه", "1h": "۱ ساعت", "4h": "۴ ساعت", "1d": "روزانه (1D)", "1w": "هفتگی (1W)", "1M": "ماهانه (1M)", "1y": "۱ ساله (365D)"}

def norm_fa(t: str) -> str:
    return str(t or "").strip().upper().replace("ي", "ی").replace("ك", "ک").replace("ة", "ه").replace("\u200c", "").replace("‌", "").replace(" ", "").replace("-", "")

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
    gd = days + 1; leap = (gy % 4 == 0 and gy % 100 != 0) or (gy % 400 == 0)
    sal = [0, 31, 29 if leap else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]; gm = 0
    while gm < 13 and gd > sal[gm]: gd -= sal[gm]; gm += 1
    return gy, gm, gd

def parse_candle_timestamp(raw) -> Optional[int]:
    if raw is None: return None
    s = str(raw).strip()
    if len(s) == 8 and s.isdigit():
        y = int(s[:4])
        if 1990 <= y <= 2100: return int(datetime(y, int(s[4:6]), int(s[6:8]), 12, 0, tzinfo=TEHRAN_TZ).timestamp())
        if 1350 <= y <= 1500: gy, gm, gd = jalali_to_gregorian(y, int(s[4:6]), int(s[6:8])); return int(datetime(gy, gm, gd, 12, 0, tzinfo=TEHRAN_TZ).timestamp())
    parts = s[:10].replace("/", "-").split("-")
    if len(parts) == 3 and all(p.isdigit() for p in parts):
        y, m, d = int(parts[0]), int(parts[1]), int(parts[2])
        if 1990 <= y <= 2100: return int(datetime(y, m, d, 12, 0, tzinfo=TEHRAN_TZ).timestamp())
        if 1350 <= y <= 1500: gy, gm, gd = jalali_to_gregorian(y, m, d); return int(datetime(gy, gm, gd, 12, 0, tzinfo=TEHRAN_TZ).timestamp())
    return None

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
    async with httpx.AsyncClient(timeout=3.5, headers=BRSAPI_HEADERS) as c:
        async def t_nb():
            try: r = await c.get("https://apiv2.nobitex.ir/v3/orderbook/USDTIRT"); p = _f(r.json().get("lastTradePrice")) if r.status_code == 200 else None; return (round(p/10.0, 1), "LIVE_NOBITEX_V3") if (p and p > 10000) else (None, f"NB:{r.status_code}")
            except Exception as e: return None, f"NB:{type(e).__name__}"
        async def t_wx():
            try: r = await c.get("https://api.wallex.ir/v1/markets"); p = _f((((r.json().get("result") or {}).get("symbols") or {}).get("USDTTMN") or {}).get("stats", {}).get("lastPrice")) if r.status_code == 200 else None; return (round(p, 1), "LIVE_WALLEX") if (p and p > 1000) else (None, f"WX:{r.status_code}")
            except Exception as e: return None, f"WX:{type(e).__name__}"
        async def t_tl():
            try: r = await c.get("https://api.tetherland.com/currencies"); p = _f((((r.json().get("data") or {}).get("currencies") or {}).get("USDT") or {}).get("price")) if r.status_code == 200 else None; return (round(p, 1), "LIVE_TETHERLAND") if (p and p > 1000) else (None, f"TL:{r.status_code}")
            except Exception as e: return None, f"TL:{type(e).__name__}"
        async def t_brs():
            if not brs_key: return None, "BRS:NO_KEY"
            try:
                r = await c.get("https://Api.BrsApi.ir/Market/Gold_Currency.php", params={"key": brs_key})
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
    bk, now = (brs_key or os.getenv("BRSAPI_KEY", "")).strip(), time.time()
    if not force and MACRO_CACHE["ts"] > 0 and (now - MACRO_CACHE["ts"] < 120) and MACRO_CACHE["key_used"] == bk: return MACRO_CACHE
    async with httpx.AsyncClient(timeout=3.5) as c:
        async def fx():
            try: r = await c.get("https://open.er-api.com/v6/latest/USD"); return (r.json().get("rates") or {}, "LIVE_OPEN_ER_API") if r.status_code == 200 else ({}, f"FX:{r.status_code}")
            except Exception as e: return {}, f"FX:{type(e).__name__}"
        async def fg():
            try: r = await c.get("https://api.alternative.me/fng/?limit=2"); d = r.json().get("data") or []; return {"value": int(d[0]["value"]), "label": d[0]["value_classification"]} if d else None
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

async def load_all_bourse(brs_key: str = "", proxy_url: str = "", force: bool = False):
    bk, px, now = (brs_key or os.getenv("BRSAPI_KEY", "")).strip(), (proxy_url or os.getenv("TSETMC_PROXY_URL", "")).strip(), time.time()
    if not force and BOURSE_CACHE["ts"] > 0 and (now - BOURSE_CACHE["ts"] < 120) and BOURSE_CACHE["key_used"] == f"{bk}|{px}": return BOURSE_CACHE
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
                    if items: BOURSE_CACHE.update({"ts": now, "items": items, "source": f"LIVE_BRSAPI ({len(items)})", "key_used": f"{bk}|{px}"}); return BOURSE_CACHE
        except Exception as e: diag.append(f"BRS_ERR:{type(e).__name__}")
    pt = "&".join(f"paperTypes%5B{i}%5D={i+1}" for i in range(9))
    raw_url = f"https://cdn.tsetmc.com/api/ClosingPrice/GetMarketWatch?market=0&{pt}&showTraded=false&withBestLimits=false&hEven=0&RefID=0"
    async with httpx.AsyncClient(timeout=3.5 if px else 2.0, headers=TSETMC_HEADERS) as c:
        try:
            r = await c.get(build_tsetmc_url(raw_url, px)); diag.append(f"TSE:{r.status_code}")
            if r.status_code == 200:
                for x in (r.json().get("marketwatch") or []):
                    sym, tr = str(x.get("lVal18AFC") or "").strip(), _f(x.get("pClosing")) or _f(x.get("pDrCotVal"))
                    if sym and tr and tr > 0:
                        nm = str(x.get("lVal30") or sym).strip()
                        items.append({"symbol": sym, "name": nm, "search_key": norm_fa(f"{sym} {nm}"), "market": "BOURSE", "ins_code": str(x.get("insCode") or ""), "today": round(tr/10.0, 2), "yesterday": round((_f(x.get("priceYesterday")) or tr)/10.0, 2), "unit": "تومان", "pe": None, "eps": None, "tvol": _f(x.get("qTotTran5J")) or 0.0})
                if len(items) > 50: BOURSE_CACHE.update({"ts": now, "items": items, "source": f"LIVE_TSETMC{'_PROXY' if px else ''} ({len(items)})", "key_used": f"{bk}|{px}"}); return BOURSE_CACHE
        except Exception as e: diag.append(f"TSE:{type(e).__name__}")
    BOURSE_CACHE.update({"ts": now, "items": items, "source": " | ".join(diag), "key_used": f"{bk}|{px}"})
    return BOURSE_CACHE

def _clean_sort_candles(raw: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    by_t = {int(c["time"]): c for c in raw if c.get("time") and c["close"] > 0 and c["open"] > 0 and c["high"] >= c["low"]}
    return [by_t[k] for k in sorted(by_t.keys())]

def _resample(daily: List[Dict[str, Any]], step: int) -> List[Dict[str, Any]]:
    return [{"time": daily[i:i+step][-1]["time"], "open": daily[i:i+step][0]["open"], "high": max(x["high"] for x in daily[i:i+step]), "low": min(x["low"] for x in daily[i:i+step]), "close": daily[i:i+step][-1]["close"], "vol": sum(x["vol"] for x in daily[i:i+step])} for i in range(0, len(daily), step)]

async def fetch_candles_tf(symbol: str, market: str, item: Dict[str, Any], tf: str = "1d", brs_key: str = "", proxy_url: str = "") -> Dict[str, Any]:
    tf = tf if tf in TF_BINANCE else "1d"
    bk, px = (brs_key or os.getenv("BRSAPI_KEY", "")).strip(), (proxy_url or os.getenv("TSETMC_PROXY_URL", "")).strip()
    ckey, now = f"{market}:{norm_fa(symbol)}:{tf}:{bk[:6]}:{px[:8]}", time.time()
    ttl = 30 if tf in ("1m", "5m", "15m") else 300
    if ckey in CANDLE_CACHE and (now - CANDLE_CACHE[ckey]["ts"] < ttl): return CANDLE_CACHE[ckey]
    candles, diag = [], []
    if market == "CRYPTO" and symbol.upper() == "USDT":
        rmap = {"1h": ("60", 14), "4h": ("240", 45), "1d": ("D", 185), "1w": ("W", 500), "1M": ("W", 700), "1y": ("D", 365)}
        if tf not in rmap: return {"ts": now, "source": f"تایم‌فریم {tf} برای تتر نوبیتکس موجود نیست (از 1h به بالا)", "candles": []}
        rs, db = rmap[tf]; to_ts = int(now)
        async with httpx.AsyncClient(timeout=4.0, headers=BRSAPI_HEADERS) as c:
            try:
                r = await c.get(f"https://apiv2.nobitex.ir/market/udf/history?symbol=USDTIRT&resolution={rs}&from={to_ts-db*86400}&to={to_ts}")
                if r.status_code == 200 and r.json().get("s") == "ok":
                    d = r.json()
                    candles = _clean_sort_candles([{"time": int(t), "open": float(o)/10.0, "high": float(h)/10.0, "low": float(l)/10.0, "close": float(cl)/10.0, "vol": float(v)} for t,o,h,l,cl,v in zip(d.get("t",[]),d.get("o",[]),d.get("h",[]),d.get("l",[]),d.get("c",[]),d.get("v",[]))])[-365:]
                    if candles: CANDLE_CACHE[ckey] = {"ts": now, "source": f"LIVE_NOBITEX_{tf}", "candles": candles}; return CANDLE_CACHE[ckey]
            except Exception as e: diag.append(f"NB:{type(e).__name__}")
    elif market == "CRYPTO":
        bi, bl = TF_BINANCE[tf]; ki = TF_KUCOIN[tf]
        async with httpx.AsyncClient(timeout=4.5) as c:
            try:
                r = await c.get(f"https://data-api.binance.vision/api/v3/klines?symbol={symbol.upper()}USDT&interval={bi}&limit={bl}")
                if r.status_code == 200 and isinstance(r.json(), list):
                    candles = _clean_sort_candles([{"time": int(k[0]/1000), "open": float(k[1]), "high": float(k[2]), "low": float(k[3]), "close": float(k[4]), "vol": float(k[5])} for k in r.json()])
                    if candles: CANDLE_CACHE[ckey] = {"ts": now, "source": f"LIVE_BINANCE_{tf}", "candles": candles}; return CANDLE_CACHE[ckey]
            except Exception as e: diag.append(f"BIN:{type(e).__name__}")
            try:
                r2 = await c.get(f"https://api.kucoin.com/api/v1/market/candles?symbol={symbol.upper()}-USDT&type={ki}")
                if r2.status_code == 200:
                    candles = _clean_sort_candles([{"time": int(k[0]), "open": float(k[1]), "close": float(k[2]), "high": float(k[3]), "low": float(k[4]), "vol": float(k[5])} for k in (r2.json().get("data") or [])[:bl]])
                    if candles: CANDLE_CACHE[ckey] = {"ts": now, "source": f"LIVE_KUCOIN_{tf}", "candles": candles}; return CANDLE_CACHE[ckey]
            except Exception as e: diag.append(f"KUC:{type(e).__name__}")
    elif market == "BOURSE":
        if tf in ("1m", "5m", "15m", "1h", "4h"): return {"ts": now, "source": f"داده دقیقه‌ای/ساعتی ({tf}) برای بورس موجود نیست (1D تا 1Y)", "candles": []}
        raw = []
        if bk:
            try:
                async with httpx.AsyncClient(timeout=6.0, headers=BRSAPI_HEADERS) as c:
                    rh = await c.get("https://Api.BrsApi.ir/Tsetmc/History.php", params={"key": bk, "type": "0", "l18": symbol})
                    if rh.status_code == 200:
                        for row in _unwrap_list(rh.json()):
                            ts = parse_candle_timestamp(row.get("date_g") or row.get("dEven") or row.get("date") or row.get("d"))
                            cl = _f(row.get("pc")) or _f(row.get("pl")) or _f(row.get("pClosing")) or _f(row.get("close"))
                            if ts and cl and cl > 0:
                                ct = cl/10.0; ot = (_f(row.get("pf")) or cl)/10.0; ht = (_f(row.get("pmax")) or cl)/10.0; lt = (_f(row.get("pmin")) or cl)/10.0
                                raw.append({"time": ts, "open": ot, "high": max(ht, ot, ct), "low": min(lt, ot, ct), "close": ct, "vol": _f(row.get("tvol")) or 0.0})
            except Exception as e: diag.append(f"BRS:{type(e).__name__}")
        elif item.get("ins_code"):
            try:
                async with httpx.AsyncClient(timeout=4.0, headers=TSETMC_HEADERS) as c:
                    rh = await c.get(build_tsetmc_url(f"https://cdn.tsetmc.com/api/ClosingPrice/GetClosingPriceDailyList/{item['ins_code']}/365", px))
                    if rh.status_code == 200:
                        for row in (rh.json().get("closingPriceDaily") or []):
                            ts = parse_candle_timestamp(row.get("dEven")); cl = _f(row.get("pClosing"))
                            if ts and cl and cl > 0:
                                ct = cl/10.0; ot = (_f(row.get("priceFirst")) or cl)/10.0; ht = (_f(row.get("priceMax")) or cl)/10.0; lt = (_f(row.get("priceMin")) or cl)/10.0
                                raw.append({"time": ts, "open": ot, "high": max(ht, ot, ct), "low": min(lt, ot, ct), "close": ct, "vol": _f(row.get("qTotTran5J")) or 0.0})
            except Exception as e: diag.append(f"TSE:{type(e).__name__}")
        candles = _clean_sort_candles(raw)[-365:]
        if tf == "1w" and len(candles) >= 10: candles = _resample(candles, 5)
        elif tf == "1M" and len(candles) >= 25: candles = _resample(candles, 21)
        if candles: CANDLE_CACHE[ckey] = {"ts": now, "source": f"LIVE_BOURSE_{tf}", "candles": candles}; return CANDLE_CACHE[ckey]
    return {"ts": now, "source": " | ".join(diag) or "NO_DATA", "candles": []}
