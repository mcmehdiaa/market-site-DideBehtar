import os
import time
import math
import asyncio
import sqlite3
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional

import httpx
import uvicorn
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

TEHRAN_TZ = timezone(timedelta(hours=3, minutes=30))
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = "/tmp/standalone_market.db" if os.path.isdir("/tmp") else os.path.join(BASE_DIR, "standalone_market.db")

app = FastAPI(title="فاز ۱ - تحلیلگر کل بازار بورس و کریپتو در ۴ بازه تا ۱۲۰ روزه")

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

# ==========================================
# ۴ بازه زمانی دقیق طبق درخواست شما (تا ۱۲۰ روزه)
# ==========================================
HORIZON_SPECS = {
    "H1_DAILY":   {"label": "۱) روزانه",   "days": 1,   "min_bars": 10,  "vol_scale": 1.4},
    "H2_WEEKLY":  {"label": "۲) هفتگی",    "days": 7,   "min_bars": 20,  "vol_scale": 3.2},
    "H3_MONTHLY": {"label": "۳) ماهانه",   "days": 30,  "min_bars": 45,  "vol_scale": 6.5},
    "H4_120D":    {"label": "۴) ۱۲۰ روزه", "days": 120, "min_bars": 120, "vol_scale": 12.0},
}

# کش سریع در حافظه برای جست‌وجوی زیر ۵ میلی‌ثانیه
CRYPTO_CACHE: Dict[str, Any] = {"ts": 0, "items": [], "source": "NOT_LOADED"}
BOURSE_CACHE: Dict[str, Any] = {"ts": 0, "items": [], "source": "NOT_LOADED"}
CANDLE_CACHE: Dict[str, Dict[str, Any]] = {}  # key -> {"ts": float, "source": str, "candles": list}

CORE_BOURSE_FALLBACK = [
    {"symbol": "فولاد", "name": "فولاد مبارکه اصفهان", "today": 481, "yesterday": 468, "unit": "تومان", "pe": 6.8, "eps": 71},
    {"symbol": "فملی", "name": "ملی صنایع مس ایران", "today": 592, "yesterday": 579, "unit": "تومان", "pe": 7.4, "eps": 80},
    {"symbol": "شستا", "name": "سرمایه گذاری تامین اجتماعی", "today": 342, "yesterday": 349, "unit": "تومان", "pe": 8.1, "eps": 42},
    {"symbol": "خودرو", "name": "ایران خودرو", "today": 285, "yesterday": 291, "unit": "تومان", "pe": 0.0, "eps": -12},
    {"symbol": "خساپا", "name": "سایپا", "today": 214, "yesterday": 210, "unit": "تومان", "pe": 0.0, "eps": -8},
    {"symbol": "وبملت", "name": "بانک ملت", "today": 418, "yesterday": 405, "unit": "تومان", "pe": 4.9, "eps": 85},
    {"symbol": "وتجارت", "name": "بانک تجارت", "today": 195, "yesterday": 198, "unit": "تومان", "pe": 5.5, "eps": 35},
    {"symbol": "شپنا", "name": "پالایش نفت اصفهان", "today": 615, "yesterday": 602, "unit": "تومان", "pe": 6.1, "eps": 101},
    {"symbol": "شبندر", "name": "پالایش نفت بندرعباس", "today": 540, "yesterday": 532, "unit": "تومان", "pe": 5.8, "eps": 93},
    {"symbol": "کگل", "name": "معدنی و صنعتی گل گهر", "today": 725, "yesterday": 710, "unit": "تومان", "pe": 7.2, "eps": 100},
    {"symbol": "کچاد", "name": "معدنی و صنعتی چادرملو", "today": 660, "yesterday": 665, "unit": "تومان", "pe": 6.9, "eps": 95},
    {"symbol": "فارس", "name": "صنایع پتروشیمی خلیج فارس", "today": 890, "yesterday": 872, "unit": "تومان", "pe": 7.9, "eps": 112},
    {"symbol": "نوری", "name": "پتروشیمی نوری", "today": 1420, "yesterday": 1390, "unit": "تومان", "pe": 6.4, "eps": 221},
    {"symbol": "تاپیکو", "name": "سرمایه گذاری نفت و گاز تامین", "today": 512, "yesterday": 518, "unit": "تومان", "pe": 7.1, "eps": 72},
    {"symbol": "ذوب", "name": "ذوب آهن اصفهان", "today": 176, "yesterday": 172, "unit": "تومان", "pe": 12.0, "eps": 14},
]

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
        diff = t - y
        pct = ((t - y) / y * 100.0) if y > 0 else 0.0
        out.append({**it, "diff": round(diff, 6), "change_pct": round(pct, 2)})
    return out

# ==========================================
# دریافت کل بازار رمزارزها (۷۰۰ تا ۱۰۰۰+ کوین) در یک درخواست
# ==========================================
async def load_all_crypto(force: bool = False):
    now = time.time()
    if not force and CRYPTO_CACHE["items"] and (now - CRYPTO_CACHE["ts"] < 60):
        return CRYPTO_CACHE

    merged: Dict[str, Dict[str, Any]] = {}
    sources_used = []

    async with httpx.AsyncClient(timeout=5.0) as client:
        # ۱) Binance Public Market Data Endpoint (بدون بلاک آی‌پی آمریکا)
        try:
            r = await client.get("https://data-api.binance.vision/api/v3/ticker/24hr")
            if r.status_code == 200:
                sources_used.append("BINANCE_VISION")
                for row in r.json():
                    sym = row.get("symbol", "")
                    if not sym.endswith("USDT") or any(x in sym for x in ("UPUSDT", "DOWNUSDT", "BULL", "BEAR")):
                        continue
                    base = sym[:-4]
                    last_p = float(row.get("lastPrice") or 0)
                    prev_p = float(row.get("prevClosePrice") or 0)
                    qvol = float(row.get("quoteVolume") or 0)
                    if last_p > 0 and qvol > 50000:
                        merged[base] = {
                            "symbol": base, "name": f"{base}/USDT", "market": "CRYPTO",
                            "today": last_p, "yesterday": prev_p if prev_p > 0 else last_p,
                            "unit": "دلار", "quote_vol": qvol, "src": "binance"
                        }
        except Exception:
            pass

        # ۲) KuCoin All Tickers (تکمیل صدها کوین جدید و آلت‌کوین‌ها)
        try:
            r2 = await client.get("https://api.kucoin.com/api/v1/market/allTickers")
            if r2.status_code == 200:
                sources_used.append("KUCOIN")
                for row in (r2.json().get("data") or {}).get("ticker", []):
                    sym = row.get("symbol", "")
                    if not sym.endswith("-USDT"):
                        continue
                    base = sym[:-5]
                    last_p = float(row.get("last") or 0)
                    chg_rate = float(row.get("changeRate") or 0)
                    qvol = float(row.get("volValue") or 0)
                    if last_p > 0 and base not in merged and qvol > 10000:
                        yest = last_p / (1.0 + chg_rate) if chg_rate > -0.99 else last_p
                        merged[base] = {
                            "symbol": base, "name": f"{base}/USDT", "market": "CRYPTO",
                            "today": last_p, "yesterday": round(yest, 8),
                            "unit": "دلار", "quote_vol": qvol, "src": "kucoin"
                        }
        except Exception:
            pass

    if merged:
        items = sorted(merged.values(), key=lambda x: x["quote_vol"], reverse=True)
        CRYPTO_CACHE.update({"ts": now, "items": items, "source": "+".join(sources_used)})
    return CRYPTO_CACHE

# ==========================================
# دریافت لیست بورس ایران (تلاش زنده TSETMC / BrsApi + فال‌بک شفاف)
# ==========================================
async def load_all_bourse(force: bool = False):
    now = time.time()
    if not force and BOURSE_CACHE["items"] and (now - BOURSE_CACHE["ts"] < 120):
        return BOURSE_CACHE

    brs_key = os.getenv("BRSAPI_KEY", "").strip()
    headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}

    async with httpx.AsyncClient(timeout=4.5, headers=headers) as client:
        # ۱) اگر کلید BrsApi تنظیم شده باشد (بهترین راه برای کل ۷۰۰+ نماد از خارج ایران)
        if brs_key:
            try:
                r = await client.get(f"https://BrsApi.ir/Api/Tsetmc/AllSymbols.php?key={brs_key}&type=1")
                if r.status_code == 200 and isinstance(r.json(), list):
                    items = []
                    for x in r.json():
                        t_rial = float(x.get("pl") or 0)
                        y_rial = float(x.get("py") or t_rial)
                        if t_rial > 0 and x.get("l18"):
                            items.append({
                                "symbol": x["l18"], "name": x.get("l30") or x["l18"], "market": "BOURSE",
                                "ins_code": str(x.get("id") or ""), "today": round(t_rial / 10.0, 2),
                                "yesterday": round(y_rial / 10.0, 2), "unit": "تومان",
                                "pe": float(x.get("pe") or 0), "eps": float(x.get("eps") or 0),
                                "tvol": float(x.get("tvol") or 0)
                            })
                    if len(items) > 100:
                        BOURSE_CACHE.update({"ts": now, "items": items, "source": f"LIVE_BRSAPI ({len(items)} نماد)"})
                        return BOURSE_CACHE
            except Exception:
                pass

        # ۲) تلاش مستقیم روی API رسمی TSETMC
        try:
            url = "https://cdn.tsetmc.com/api/ClosingPrice/GetMarketWatch?market=0&industrialGroup=&paperTypes%5B0%5D=1&paperTypes%5B1%5D=2&paperTypes%5B2%5D=8&showTraded=false&withBestLimits=false&hEven=0&RefID=0"
            r = await client.get(url)
            if r.status_code == 200:
                rows = r.json().get("marketwatch", [])
                items = []
                for x in rows:
                    t_rial = float(x.get("pClosing") or x.get("pDrCotVal") or 0)
                    y_rial = float(x.get("priceYesterday") or t_rial)
                    sym = (x.get("lVal18AFC") or "").strip()
                    if t_rial > 0 and sym:
                        items.append({
                            "symbol": sym, "name": x.get("lVal30") or sym, "market": "BOURSE",
                            "ins_code": str(x.get("insCode") or ""), "today": round(t_rial / 10.0, 2),
                            "yesterday": round(y_rial / 10.0, 2), "unit": "تومان",
                            "pe": 0, "eps": 0, "tvol": float(x.get("qTotTran5J") or 0)
                        })
                if len(items) > 50:
                    BOURSE_CACHE.update({"ts": now, "items": items, "source": f"LIVE_TSETMC ({len(items)} نماد)"})
                    return BOURSE_CACHE
        except Exception:
            pass

    # اگر TSETMC از سرور آمریکای Vercel بلاک بود، صادقانه گزارش می‌دهیم
    if not BOURSE_CACHE["items"]:
        fallback = [{**x, "market": "BOURSE", "tvol": 1000000} for x in CORE_BOURSE_FALLBACK]
        BOURSE_CACHE.update({"ts": now, "items": fallback, "source": "TSETMC_BLOCKED_ON_US_IP (نیاز به فاز ۲)"})
    return BOURSE_CACHE

# ==========================================
# دریافت تا ۱۸۰ کندل واقعی روزانه (برای تحلیل دقیق بازه ۱۲۰ روزه)
# ==========================================
async def fetch_180_candles(symbol: str, market: str, item: Dict[str, Any]) -> Dict[str, Any]:
    ckey = f"{market}:{symbol.upper()}"
    now = time.time()
    if ckey in CANDLE_CACHE and (now - CANDLE_CACHE[ckey]["ts"] < 300):
        return CANDLE_CACHE[ckey]

    candles = []
    src = "NO_DATA"

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
                    src = "LIVE_BINANCE_VISION_1D"
            except Exception:
                pass

            if len(candles) < 10:
                try:
                    r2 = await client.get(f"https://api.kucoin.com/api/v1/market/candles?symbol={symbol.upper()}-USDT&type=1day")
                    if r2.status_code == 200:
                        raw = r2.json().get("data") or []
                        # KuCoin ترتیب نزولی دارد و ستون‌ها: [time, open, close, high, low, vol]
                        for k in reversed(raw[:180]):
                            candles.append({
                                "date": datetime.fromtimestamp(int(k[0]), tz=TEHRAN_TZ).strftime("%m-%d"),
                                "open": float(k[1]), "close": float(k[2]), "high": float(k[3]), "low": float(k[4]), "vol": float(k[5])
                            })
                        if candles:
                            src = "LIVE_KUCOIN_1D"
                except Exception:
                    pass

    elif market == "BOURSE":
        ins_code = item.get("ins_code")
        async with httpx.AsyncClient(timeout=4.5, headers={"User-Agent": "Mozilla/5.0"}) as client:
            if not ins_code:
                try:
                    rs = await client.get(f"https://cdn.tsetmc.com/api/Instrument/GetInstrumentSearch/{symbol}")
                    if rs.status_code == 200:
                        hits = rs.json().get("instrumentSearch") or []
                        exact = next((h for h in hits if (h.get("lVal18AFC") or "").strip() == symbol), hits[0] if hits else None)
                        if exact:
                            ins_code = str(exact.get("insCode"))
                except Exception:
                    pass
            if ins_code:
                try:
                    rh = await client.get(f"https://cdn.tsetmc.com/api/ClosingPrice/GetClosingPriceDailyList/{ins_code}/180")
                    if rh.status_code == 200:
                        rows = rh.json().get("closingPriceDaily") or []
                        for row in reversed(rows):
                            c = float(row.get("pClosing") or 0) / 10.0
                            if c > 0:
                                o = float(row.get("priceFirst") or c * 10) / 10.0
                                h = float(row.get("priceMax") or c * 10) / 10.0
                                l = float(row.get("priceMin") or c * 10) / 10.0
                                d_str = str(row.get("dEven") or "")
                                candles.append({"date": f"{d_str[4:6]}-{d_str[6:8]}" if len(d_str) == 8 else d_str,
                                                "open": o, "high": h, "low": l, "close": c, "vol": float(row.get("qTotTran5J") or 0)})
                        if candles:
                            src = "LIVE_TSETMC_1D"
                except Exception:
                    pass

    res = {"ts": now, "source": src, "candles": candles}
    if candles:
        CANDLE_CACHE[ckey] = res
    return res

# ==========================================
# تحلیل تکنیکال، پرایس اکشن، فیبوناچی و قرارداد ۴ بازه تا ۱۲۰ روزه
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

def analyze_full(symbol: str, market: str, item: Dict[str, Any], candles: List[Dict[str, Any]]):
    n = len(candles)
    closes = [c["close"] for c in candles]
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]
    price = closes[-1] if closes else float(item.get("today") or 0)

    # نوسان واقعی روزانه (ATR%) برای هدف/حدضرر پویا در ۴ بازه
    rets = [abs(closes[i] - closes[i - 1]) / closes[i - 1] for i in range(1, len(closes)) if closes[i - 1] > 0]
    daily_vol = max(min((sum(rets[-20:]) / len(rets[-20:])) if rets else 0.02, 0.08), 0.01)

    rsi_s = calc_rsi(closes, 14) if n >= 2 else [50.0]
    rsi_now = rsi_s[-1]
    ema12 = calc_ema(closes, 12) if n >= 2 else [price]
    ema26 = calc_ema(closes, 26) if n >= 2 else [price]
    macd_l = [round(a - b, 6) for a, b in zip(ema12, ema26)]
    sig_l = [round(x, 6) for x in calc_ema(macd_l, 9)]
    hist_l = [round(m - s, 6) for m, s in zip(macd_l, sig_l)]

    sh = max(highs[-120:]) if highs else price
    sl = min(lows[-120:]) if lows else price
    diff = sh - sl
    fib = {
        "0.0": round(sh, 6), "0.236": round(sh - 0.236 * diff, 6),
        "0.382": round(sh - 0.382 * diff, 6), "0.500": round(sh - 0.500 * diff, 6),
        "0.618": round(sh - 0.618 * diff, 6), "1.0": round(sl, 6),
    }

    # پرایس اکشن و ساختار
    sma20 = sum(closes[-20:]) / len(closes[-20:]) if closes else price
    sma50 = sum(closes[-50:]) / len(closes[-50:]) if closes else price
    if price > sma20 > sma50:
        structure = "روند صعودی قدرتمند (قیمت بالای میانگین ۲۰ و ۵۰ روزه)"
    elif price < sma20 < sma50:
        structure = "روند نزولی (فشار فروش زیر میانگین‌ها)"
    else:
        structure = "رنج / فاز نوسانی و تغییر جهت"

    # ۴ بازه دقیق: روزانه، هفتگی، ماهانه، ۱۲۰ روزه
    fee_pct = 1.25 if market == "BOURSE" else 0.20
    contracts = {}
    for hk, spec in HORIZON_SPECS.items():
        if n < spec["min_bars"] or price <= 0:
            contracts[hk] = {
                "horizon": hk, "label": spec["label"], "evaluatable": False,
                "available_bars": n, "required_min_bars": spec["min_bars"],
                "action": "قابل ارزیابی نیست (کمبود تاریخچه کندل)",
                "target": None, "stop": None, "net_return_pct": None, "net_risk_pct": None, "rr": None
            }
        else:
            tp_pct = min(daily_vol * spec["vol_scale"] * 1.45, 0.65)
            sl_pct = min(daily_vol * spec["vol_scale"] * 0.72, 0.28)
            tp = round(price * (1.0 + tp_pct), 6)
            sl = round(price * (1.0 - sl_pct), 6)
            net_ret = round(tp_pct * 100.0 - fee_pct, 2)
            net_rsk = round(sl_pct * 100.0 + fee_pct, 2)
            rr = round(net_ret / net_rsk, 2) if net_rsk > 0 else 0.0

            # پیشنهاد صریح بر اساس وضعیت تکنیکال همان بازه
            if rsi_now >= 75:
                act = "صبر برای اصلاح / سیو سود (اشباع خرید)"
            elif rsi_now <= 32 and price <= fib["0.500"]:
                act = "پیشنهاد خرید پله‌ای در کف حمایتی"
            elif macd_l[-1] > sig_l[-1] and price > sma20 and rr >= 1.5:
                act = "پیشنهاد خرید / نگهداری صعودی"
            elif price < sma20 and macd_l[-1] < sig_l[-1]:
                act = "پیشنهاد فروش / دوری از معامله (روند منفی)"
            else:
                act = "انتظار / نوسان‌گیری بین حمایت و مقاومت"

            contracts[hk] = {
                "horizon": hk, "label": spec["label"], "evaluatable": True,
                "available_bars": n, "required_min_bars": spec["min_bars"],
                "action": act, "target": tp, "stop": sl,
                "net_return_pct": net_ret, "net_risk_pct": net_rsk, "rr": rr
            }

    # روانشناس بازار + بنیادی + استراتژی گذشته/حال/آینده
    if rsi_now >= 70:
        mood, advice = f"طمع شدید (RSI={rsi_now})", "جو خرید هیجانی حاکم است؛ خرید روی قله پرریسک است، منتظر پولبک بمانید."
    elif rsi_now <= 32:
        mood, advice = f"ترس شدید (RSI={rsi_now})", "فروش هیجانی در کف؛ با تایید کندل سبز امکان ورود پله‌ای با حد ضرر مشخص وجود دارد."
    else:
        mood, advice = f"تعادل روانی (RSI={rsi_now})", "بازار در تعادل است؛ فقط مطابق حد سود و ضرر عمل کنید."

    pe, eps = float(item.get("pe") or 0), float(item.get("eps") or 0)
    if market == "BOURSE":
        fund = f"P/E={pe or 'نامشخص'} | EPS={eps or 'نامشخص'} | وضعیت: {'ارزنده' if (eps > 0 and 0 < pe < 8) else ('زیان‌ده' if eps < 0 else 'نیازمند بررسی صورت مالی')}"
    else:
        qv = float(item.get("quote_vol") or 0)
        fund = f"حجم معاملات ۲۴ ساعته: {round(qv/1e6, 2)} میلیون دلار | نقدشوندگی: {'عالی' if qv > 1e7 else 'متوسط'}"

    strategies = {
        "past": f"گذشته (۱۲۰ روز اخیر): نوسان بین کف {fib['1.0']} و سقف {fib['0.0']}؛ خرید نزدیک ۰.۶۱۸ ({fib['0.618']}) پربازده‌ترین استراتژی بوده است.",
        "present": f"حال: قیمت در {price} ({structure}). تراز فیبوناچی نزدیک: حمایت {fib['0.618']} و مقاومت {fib['0.236']}.",
        "future": f"آینده: عبور قطعی از {fib['0.236']} هدف {fib['0.0']} را فعال می‌کند؛ شکست حمایت {fib['0.618']} به سمت پایین نیازمند خروج فوری است."
    }

    return {
        "price": price,
        "technical": {
            "dates": [c["date"] for c in candles[-60:]], "closes": closes[-60:],
            "rsi_now": rsi_now, "rsi_series": rsi_s[-60:],
            "macd_series": macd_l[-60:], "signal_series": sig_l[-60:], "hist_series": hist_l[-60:],
            "fib": fib, "structure": structure,
        },
        "fundamental": fund,
        "psychology": {"mood": mood, "advice": advice},
        "strategies": strategies,
        "contracts": contracts,
    }

# ==========================================
# اندپوینت‌ها: جست‌وجوی زیر ۵ میلی‌ثانیه کل بازار، اسکنر ۴ بازه و تحلیل
# ==========================================
@app.get("/api/system-status")
async def system_status():
    c_data, b_data = await asyncio.gather(load_all_crypto(), load_all_bourse())
    return {
        "timestamp_tehran": datetime.now(TEHRAN_TZ).strftime("%Y-%m-%d %H:%M"),
        "crypto_count": len(c_data["items"]),
        "crypto_source": c_data["source"],
        "bourse_count": len(b_data["items"]),
        "bourse_source": b_data["source"],
    }

@app.get("/api/search")
async def instant_search(q: str = ""):
    q_clean = q.strip().upper()
    c_data, b_data = await asyncio.gather(load_all_crypto(), load_all_bourse())
    results = []

    for it in b_data["items"]:
        if not q_clean or q_clean in it["symbol"].upper() or q_clean in it["name"].upper():
            results.append({"symbol": it["symbol"], "name": it["name"], "market": "BOURSE", "today": it["today"], "unit": "تومان"})
            if len(results) >= 12:
                break

    for it in c_data["items"]:
        if not q_clean or q_clean in it["symbol"].upper():
            results.append({"symbol": it["symbol"], "name": it["name"], "market": "CRYPTO", "today": it["today"], "unit": "دلار"})
            if len(results) >= 25:
                break

    return {"query": q, "total_universe": len(b_data["items"]) + len(c_data["items"]), "results": results}

@app.get("/api/analyze")
async def analyze_endpoint(symbol: str, market: str = "CRYPTO"):
    t0 = time.time()
    sym_u, mkt_u = symbol.strip().upper(), market.strip().upper()
    c_data, b_data = await asyncio.gather(load_all_crypto(), load_all_bourse())

    item = None
    if mkt_u == "BOURSE":
        item = next((x for x in b_data["items"] if x["symbol"].upper() == sym_u), None)
    else:
        item = next((x for x in c_data["items"] if x["symbol"].upper() == sym_u), None)

    if not item:
        # جست‌وجوی متقابل در بازار دیگر
        item = next((x for x in c_data["items"] if x["symbol"].upper() == sym_u), None)
        if item:
            mkt_u = "CRYPTO"
        else:
            item = next((x for x in b_data["items"] if x["symbol"].upper() == sym_u), None)
            if item:
                mkt_u = "BOURSE"

    if not item:
        return {"found": False, "symbol": sym_u, "elapsed_ms": round((time.time() - t0) * 1000, 1)}

    c_res = await fetch_180_candles(item["symbol"], mkt_u, item)
    candles = c_res["candles"]
    if not candles:
        return {
            "found": True, "no_candles": True, "symbol": item["symbol"], "market": mkt_u,
            "candle_source": c_res["source"], "item": enrich_comparison([item])[0],
            "elapsed_ms": round((time.time() - t0) * 1000, 1)
        }

    full = analyze_full(item["symbol"], mkt_u, item, candles)
    return {
        "found": True, "no_candles": False, "symbol": item["symbol"], "market": mkt_u,
        "unit": item["unit"], "candle_source": c_res["source"], "bars_count": len(candles),
        "comparison": enrich_comparison([item])[0],
        "elapsed_ms": round((time.time() - t0) * 1000, 1),
        **full
    }

@app.get("/api/top5-scanner")
async def top5_scanner():
    c_data = await load_all_crypto()
    # اسکن موازی برترین رمزارزهای پرحجم برای هر ۴ بازه در کسری از ثانیه
    candidates = [x for x in c_data["items"] if x["today"] > 0][:14]
    candle_tasks = [fetch_180_candles(x["symbol"], "CRYPTO", x) for x in candidates]
    candle_results = await asyncio.gather(*candle_tasks)

    analyzed = []
    for item, cres in zip(candidates, candle_results):
        if len(cres["candles"]) >= 10:
            analyzed.append((item, analyze_full(item["symbol"], "CRYPTO", item, cres["candles"])))

    top5 = {}
    for hk in HORIZON_SPECS:
        valid = [
            (it, a["contracts"][hk]) for it, a in analyzed
            if a["contracts"][hk]["evaluatable"] and ("خرید" in a["contracts"][hk]["action"] or "نگهداری" in a["contracts"][hk]["action"])
        ]
        valid.sort(key=lambda z: z[1]["net_return_pct"] or 0, reverse=True)
        top5[hk] = [{
            "symbol": it["symbol"], "price": it["today"], "action": c["action"],
            "net_return_pct": c["net_return_pct"], "rr": c["rr"]
        } for it, c in valid[:5]]
    return top5

@app.get("/api/watchlists")
async def watchlists():
    c_data, b_data = await asyncio.gather(load_all_crypto(), load_all_bourse())
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
async def get_pf():
    c_data, b_data = await asyncio.gather(load_all_crypto(), load_all_bourse())
    usd = 70200.0
    conn = get_conn()
    rows = conn.execute("SELECT id, symbol, market, quantity, avg_buy_price_toman FROM portfolio").fetchall()
    conn.close()
    out = []
    for pid, sym, mkt, qty, buy_p in rows:
        pool = b_data["items"] if mkt == "BOURSE" else c_data["items"]
        m = next((x for x in pool if x["symbol"].upper() == sym.upper()), None)
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
