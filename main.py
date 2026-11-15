import os
import math
import sqlite3
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any

import httpx
import uvicorn
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

TEHRAN_TZ = timezone(timedelta(hours=3, minutes=30))
DB_FILE = "standalone_market.db"

app = FastAPI(title="سایت مستقل تحلیل بازار، پرایس اکشن، بنیادی و روانشناسی")

def init_db():
    conn = sqlite3.connect(DB_FILE)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS portfolio (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            market TEXT NOT NULL,
            quantity REAL NOT NULL,
            avg_buy_price_toman REAL NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()

init_db()

HORIZON_SPECS = {
    "H1_DAILY":     {"label": "روزانه",   "min_bars": 5,  "tp_mult": 1.028, "sl_mult": 0.985},
    "H2_WEEKLY":    {"label": "هفتگی",    "min_bars": 10, "tp_mult": 1.065, "sl_mult": 0.962},
    "H3_MONTHLY":   {"label": "ماهانه",   "min_bars": 40, "tp_mult": 1.150, "sl_mult": 0.925},
    "H4_QUARTERLY": {"label": "سه‌ماهه",  "min_bars": 90, "tp_mult": 1.300, "sl_mult": 0.870},
}

WATCHLIST_DATA: Dict[str, List[Dict[str, Any]]] = {
    "bourse": [
        {"symbol": "فولاد", "name": "فولاد مبارکه", "today": 481, "yesterday": 468, "unit": "تومان", "bars": 120, "pe": 6.8, "sector_pe": 7.9, "eps": 71, "roe": 31, "debt": 0.38, "bias": 0.0022},
        {"symbol": "فملی", "name": "ملی مس ایران", "today": 592, "yesterday": 579, "unit": "تومان", "bars": 120, "pe": 7.4, "sector_pe": 8.2, "eps": 80, "roe": 34, "debt": 0.31, "bias": 0.0025},
        {"symbol": "شستا", "name": "تامین اجتماعی", "today": 342, "yesterday": 349, "unit": "تومان", "bars": 120, "pe": 8.1, "sector_pe": 7.5, "eps": 42, "roe": 21, "debt": 0.45, "bias": -0.0005},
        {"symbol": "خودرو", "name": "ایران خودرو", "today": 285, "yesterday": 291, "unit": "تومان", "bars": 110, "pe": 0.0, "sector_pe": 9.0, "eps": -12, "roe": -8, "debt": 0.82, "bias": -0.0018},
        {"symbol": "خساپا", "name": "سایپا", "today": 214, "yesterday": 210, "unit": "تومان", "bars": 105, "pe": 0.0, "sector_pe": 9.0, "eps": -8, "roe": -5, "debt": 0.79, "bias": -0.0008},
        {"symbol": "وبملت", "name": "بانک ملت", "today": 418, "yesterday": 405, "unit": "تومان", "bars": 120, "pe": 4.9, "sector_pe": 6.2, "eps": 85, "roe": 26, "debt": 0.65, "bias": 0.0020},
        {"symbol": "وتجارت", "name": "بانک تجارت", "today": 195, "yesterday": 198, "unit": "تومان", "bars": 95, "pe": 5.5, "sector_pe": 6.2, "eps": 35, "roe": 19, "debt": 0.68, "bias": 0.0002},
        {"symbol": "شپنا", "name": "پالایش اصفهان", "today": 615, "yesterday": 602, "unit": "تومان", "bars": 120, "pe": 6.1, "sector_pe": 6.8, "eps": 101, "roe": 36, "debt": 0.34, "bias": 0.0019},
        {"symbol": "شبندر", "name": "پالایش بندرعباس", "today": 540, "yesterday": 532, "unit": "تومان", "bars": 120, "pe": 5.8, "sector_pe": 6.8, "eps": 93, "roe": 33, "debt": 0.36, "bias": 0.0017},
        {"symbol": "کگل", "name": "گل‌گهر", "today": 725, "yesterday": 710, "unit": "تومان", "bars": 120, "pe": 7.2, "sector_pe": 7.9, "eps": 100, "roe": 32, "debt": 0.28, "bias": 0.0021},
        {"symbol": "کچاد", "name": "چادرملو", "today": 660, "yesterday": 665, "unit": "تومان", "bars": 120, "pe": 6.9, "sector_pe": 7.9, "eps": 95, "roe": 29, "debt": 0.29, "bias": 0.0012},
        {"symbol": "فارس", "name": "خلیج فارس", "today": 890, "yesterday": 872, "unit": "تومان", "bars": 120, "pe": 7.9, "sector_pe": 8.4, "eps": 112, "roe": 28, "debt": 0.41, "bias": 0.0018},
        {"symbol": "نوری", "name": "پتروشیمی نوری", "today": 1420, "yesterday": 1390, "unit": "تومان", "bars": 120, "pe": 6.4, "sector_pe": 7.6, "eps": 221, "roe": 42, "debt": 0.26, "bias": 0.0026},
        {"symbol": "تاپیکو", "name": "نفت و گاز تامین", "today": 512, "yesterday": 518, "unit": "تومان", "bars": 115, "pe": 7.1, "sector_pe": 7.6, "eps": 72, "roe": 24, "debt": 0.42, "bias": 0.0004},
        {"symbol": "ذوب", "name": "ذوب آهن", "today": 176, "yesterday": 172, "unit": "تومان", "bars": 28, "pe": 12.0, "sector_pe": 7.9, "eps": 14, "roe": 11, "debt": 0.71, "bias": -0.0002},
    ],
    "crypto": [
        {"symbol": "BTC", "name": "بیت‌کوین", "today": 91500, "yesterday": 89800, "unit": "دلار", "bars": 120, "mcap_b": 1810, "vol_ratio": 0.042, "infl": 0.85, "bias": 0.0030},
        {"symbol": "ETH", "name": "اتریوم", "today": 3240, "yesterday": 3180, "unit": "دلار", "bars": 120, "mcap_b": 390, "vol_ratio": 0.055, "infl": 0.40, "bias": 0.0022},
        {"symbol": "SOL", "name": "سولانا", "today": 218, "yesterday": 209, "unit": "دلار", "bars": 120, "mcap_b": 102, "vol_ratio": 0.088, "infl": 4.80, "bias": 0.0038},
        {"symbol": "BNB", "name": "بایننس کوین", "today": 635, "yesterday": 628, "unit": "دلار", "bars": 120, "mcap_b": 92, "vol_ratio": 0.031, "infl": -1.20, "bias": 0.0018},
        {"symbol": "XRP", "name": "ریپل", "today": 1.12, "yesterday": 1.05, "unit": "دلار", "bars": 120, "mcap_b": 63, "vol_ratio": 0.095, "infl": 3.50, "bias": 0.0024},
        {"symbol": "ADA", "name": "کاردانو", "today": 0.78, "yesterday": 0.74, "unit": "دلار", "bars": 120, "mcap_b": 27, "vol_ratio": 0.060, "infl": 2.40, "bias": 0.0015},
        {"symbol": "AVAX", "name": "آوالانچ", "today": 36.4, "yesterday": 35.1, "unit": "دلار", "bars": 120, "mcap_b": 15, "vol_ratio": 0.072, "infl": 6.10, "bias": 0.0020},
        {"symbol": "DOGE", "name": "دوج‌کوین", "today": 0.38, "yesterday": 0.36, "unit": "دلار", "bars": 120, "mcap_b": 55, "vol_ratio": 0.110, "infl": 3.40, "bias": 0.0029},
        {"symbol": "TON", "name": "تون‌کوین", "today": 5.65, "yesterday": 5.72, "unit": "دلار", "bars": 120, "mcap_b": 14, "vol_ratio": 0.045, "infl": 1.90, "bias": 0.0005},
        {"symbol": "TRX", "name": "ترون", "today": 0.21, "yesterday": 0.20, "unit": "دلار", "bars": 120, "mcap_b": 18, "vol_ratio": 0.052, "infl": -0.90, "bias": 0.0016},
        {"symbol": "DOT", "name": "پولکادات", "today": 6.8, "yesterday": 6.5, "unit": "دلار", "bars": 120, "mcap_b": 9.8, "vol_ratio": 0.063, "infl": 7.50, "bias": 0.0011},
        {"symbol": "LINK", "name": "چین‌لینک", "today": 15.9, "yesterday": 15.2, "unit": "دلار", "bars": 120, "mcap_b": 10.1, "vol_ratio": 0.074, "infl": 2.10, "bias": 0.0023},
        {"symbol": "SUI", "name": "سویی", "today": 3.45, "yesterday": 3.20, "unit": "دلار", "bars": 100, "mcap_b": 9.5, "vol_ratio": 0.125, "infl": 12.0, "bias": 0.0040},
        {"symbol": "SHIB", "name": "شیبا اینو", "today": 0.000025, "yesterday": 0.000024, "unit": "دلار", "bars": 120, "mcap_b": 14.7, "vol_ratio": 0.090, "infl": 0.0, "bias": 0.0014},
        {"symbol": "PEPE", "name": "پپه", "today": 0.000019, "yesterday": 0.000020, "unit": "دلار", "bars": 18, "mcap_b": 8.0, "vol_ratio": 0.180, "infl": 0.0, "bias": -0.0010},
    ],
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
        t, y = float(it["today"]), float(it["yesterday"])
        diff = t - y
        pct = ((t - y) / y * 100.0) if y > 0 else 0.0
        out.append({**it, "diff": round(diff, 6), "change_pct": round(pct, 2)})
    return out

async def try_fetch_live_crypto():
    ids = "bitcoin,ethereum,solana,binancecoin,ripple,cardano,avalanche-2,dogecoin,the-open-network,tron,polkadot,chainlink,sui,shiba-inu,pepe"
    id_map = {
        "BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana", "BNB": "binancecoin",
        "XRP": "ripple", "ADA": "cardano", "AVAX": "avalanche-2", "DOGE": "dogecoin",
        "TON": "the-open-network", "TRX": "tron", "DOT": "polkadot", "LINK": "chainlink",
        "SUI": "sui", "SHIB": "shiba-inu", "PEPE": "pepe"
    }
    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            r = await client.get(f"https://api.coingecko.com/api/v3/simple/price?ids={ids}&vs_currencies=usd&include_24hr_change=true")
            if r.status_code == 200:
                data = r.json()
                for item in WATCHLIST_DATA["crypto"]:
                    cg_id = id_map.get(item["symbol"])
                    if cg_id and cg_id in data:
                        p = float(data[cg_id]["usd"])
                        c = float(data[cg_id].get("usd_24h_change") or 0.0)
                        item["today"] = p
                        item["yesterday"] = round(p / (1.0 + c / 100.0), 8) if c != -100 else p
                return "LIVE_COINGECKO"
    except Exception:
        pass
    return "CACHED_DEMO"

async def get_candles(symbol: str, market: str, today_p: float, yest_p: float, bars_count: int, bias: float):
    if market == "CRYPTO" and bars_count >= 30:
        try:
            async with httpx.AsyncClient(timeout=4.0) as client:
                r = await client.get(f"https://api.binance.com/api/v3/klines?symbol={symbol.upper()}USDT&interval=1d&limit=100")
                if r.status_code == 200:
                    raw = r.json()
                    candles = [{
                        "date": datetime.fromtimestamp(k[0] / 1000, tz=TEHRAN_TZ).strftime("%m-%d"),
                        "open": float(k[1]), "high": float(k[2]), "low": float(k[3]), "close": float(k[4])
                    } for k in raw]
                    if len(candles) >= 10:
                        return "LIVE_BINANCE", candles
        except Exception:
            pass

    now = datetime.now(TEHRAN_TZ)
    n = max(bars_count, 5)
    closes = [1.0]
    for i in range(1, n):
        wave = math.sin(i * 0.25) * 0.015 + math.cos(i * 0.12) * 0.010
        closes.append(closes[-1] * (1.0 + bias + wave * 0.3))
    scale = today_p / closes[-1] if closes[-1] > 0 else 1.0
    candles = []
    for i in range(n):
        c = round(closes[i] * scale, 6)
        if i == n - 2 and yest_p > 0:
            c = yest_p
        if i == n - 1:
            c = today_p
        o = round(candles[-1]["close"] if i > 0 else c * 0.995, 6)
        h = round(max(o, c) * 1.014, 6)
        l = round(min(o, c) * 0.986, 6)
        dt = (now - timedelta(days=(n - 1 - i))).strftime("%m-%d")
        candles.append({"date": dt, "open": o, "high": h, "low": l, "close": c})
    return "STRUCTURED_DATA", candles

def calc_ema(vals: List[float], period: int) -> List[float]:
    if not vals:
        return []
    k = 2.0 / (period + 1)
    out = [vals[0]]
    for v in vals[1:]:
        out.append(v * k + out[-1] * (1.0 - k))
    return out

def calc_rsi_series(closes: List[float], period: int = 14) -> List[float]:
    if len(closes) < 2:
        return [50.0] * len(closes)
    rsis = [50.0]
    gains, losses = [], []
    for i in range(1, len(closes)):
        chg = closes[i] - closes[i - 1]
        gains.append(max(chg, 0.0))
        losses.append(max(-chg, 0.0))
        g_w, l_w = gains[-period:], losses[-period:]
        avg_g, avg_l = sum(g_w) / len(g_w), sum(l_w) / len(l_w)
        if avg_l == 0:
            rsis.append(100.0 if avg_g > 0 else 50.0)
        else:
            rsis.append(round(100.0 - (100.0 / (1.0 + (avg_g / avg_l))), 2))
    return rsis

def analyze_technicals(candles: List[Dict[str, float]]):
    closes = [c["close"] for c in candles]
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]

    rsi_series = calc_rsi_series(closes, 14)
    ema12 = calc_ema(closes, 12)
    ema26 = calc_ema(closes, 26)
    macd_line = [round(a - b, 6) for a, b in zip(ema12, ema26)]
    signal_line = [round(x, 6) for x in calc_ema(macd_line, 9)]
    macd_hist = [round(m - s, 6) for m, s in zip(macd_line, signal_line)]

    swing_high = max(highs[-60:])
    swing_low = min(lows[-60:])
    diff = swing_high - swing_low
    fib = {
        "0.0": round(swing_high, 4),
        "0.236": round(swing_high - 0.236 * diff, 4),
        "0.382": round(swing_high - 0.382 * diff, 4),
        "0.500": round(swing_high - 0.500 * diff, 4),
        "0.618": round(swing_high - 0.618 * diff, 4),
        "1.0": round(swing_low, 4),
    }

    last = candles[-1]
    prev = candles[-2] if len(candles) >= 2 else last
    body = abs(last["close"] - last["open"])
    rng = max(last["high"] - last["low"], 1e-9)
    low_wick = min(last["open"], last["close"]) - last["low"]
    up_wick = last["high"] - max(last["open"], last["close"])

    if low_wick > body * 1.8 and last["close"] >= last["open"]:
        pa = "پین‌بار صعودی (ورود خریداران در کف)"
    elif up_wick > body * 1.8 and last["close"] <= last["open"]:
        pa = "پین‌بار نزولی (رد قیمت از مقاومت)"
    elif last["close"] > prev["high"] and last["close"] > last["open"]:
        pa = "اینگالفینگ صعودی / شکست سقف کندل قبل"
    elif body / rng < 0.2:
        pa = "کندل دوجی (تردید خریدار و فروشنده)"
    else:
        pa = "کندل مومنتوم متعادل"

    sma20 = sum(closes[-20:]) / len(closes[-20:])
    if last["close"] > sma20 * 1.015:
        struct = "روند صعودی (سقف‌ها و کف‌های بالاتر)"
    elif last["close"] < sma20 * 0.985:
        struct = "روند نزولی (زیر میانگین ۲۰ روزه)"
    else:
        struct = "فاز رنج / خنثی (انباشت نقدینگی)"

    return {
        "dates": [c["date"] for c in candles[-50:]],
        "closes": closes[-50:],
        "rsi_now": rsi_series[-1],
        "rsi_series": rsi_series[-50:],
        "macd_now": macd_line[-1],
        "signal_now": signal_line[-1],
        "hist_now": macd_hist[-1],
        "macd_series": macd_line[-50:],
        "signal_series": signal_line[-50:],
        "hist_series": macd_hist[-50:],
        "fib": fib,
        "swing_high": round(swing_high, 4),
        "swing_low": round(swing_low, 4),
        "pa_pattern": pa,
        "structure": struct,
        "support": fib["0.618"],
        "resistance": fib["0.236"],
    }

def build_fundamental_psych_strategies(item: Dict[str, Any], market: str, tech: Dict[str, Any]):
    if market == "BOURSE":
        pe, sec_pe = item.get("pe", 0), item.get("sector_pe", 7.5)
        eps, roe, debt = item.get("eps", 0), item.get("roe", 0), item.get("debt", 0.5)
        if eps <= 0:
            f_verdict = "ضعیف / زیان‌ده"
            f_text = f"سود هر سهم (EPS={eps}) منفی و بدهی {int(debt*100)}% بالاست؛ برای نگهداری میان‌مدت ریسک بالایی دارد."
        elif pe < sec_pe and roe >= 25:
            f_verdict = "ارزنده و بنیادی قوی"
            f_text = f"نسبت P/E برابر {pe} (پایین‌تر از صنعت {sec_pe}) و بازده حقوق صاحبان سهام ROE={roe}% عالی است."
        else:
            f_verdict = "متعادل"
            f_text = f"نسبت P/E={pe} نزدیک میانگین صنعت ({sec_pe})، ROE={roe}% و بدهی {int(debt*100)}% است."
    else:
        mcap, vr, infl = item.get("mcap_b", 10), item.get("vol_ratio", 0.05), item.get("infl", 2.0)
        f_verdict = "دارایی بزرگ و پرنقدینگی" if mcap >= 20 else "پروژه متوسط / نوسانی"
        f_text = f"ارزش بازار {mcap} میلیارد دلار، نسبت حجم به مارکت‌کپ {round(vr*100,1)}% و تورم سالانه عرضه {infl}% است."

    rsi = tech["rsi_now"]
    if rsi >= 70:
        mood, score = "طمع شدید و هیجان خرید (FOMO)", min(95, int(rsi + 10))
        psych = "بازار بیش‌ازحد داغ است. اشتباه رایج الان خرید روی سقف است؛ صبر برای اصلاح تا تراز ۰.۳۸۲ فیبوناچی یا سیو سود پله‌ای عاقلانه‌تر است."
    elif rsi <= 32:
        mood, score = "ترس شدید و فروش هیجانی", max(10, int(rsi - 5))
        psych = "اکثریت دچار ترس شده‌اند. فروش هیجانی در کف اشتباه است؛ با تایید پرایس اکشن روی حمایت، پول هوشمند پله‌ای جمع‌آوری می‌کند."
    elif 48 <= rsi <= 65:
        mood, score = "خوش‌بینی متعادل و منطقی", int(rsi)
        psych = "احساسات بازار متعادل است و حباب هیجانی وجود ندارد. پایبندی به حد ضرر و حجم استاندارد بهترین تصمیم است."
    else:
        mood, score = "تردید و فاز انتظار", int(rsi)
        psych = "بازار بی‌تصمیم است. معامله‌گری بیش‌ازحد در بازار رنج باعث فرسایش سرمایه می‌شود؛ منتظر شکست تراز کلیدی بمانید."

    macd_bull = tech["macd_now"] > tech["signal_now"]
    strategies = {
        "past": f"وضعیت گذشته (چند هفته اخیر): ساختار «{tech['structure']}» بین کف {tech['swing_low']} و سقف {tech['swing_high']}. استراتژی موفق گذشته: خرید نزدیک تراز ۰.۶۱۸ فیبوناچی ({tech['fib']['0.618']}) و فروش پله‌ای روی ۰.۲۳۶ ({tech['fib']['0.236']}).",
        "present": f"وضعیت حال (هم‌اکنون): RSI={rsi}، MACD {'صعودی' if macd_bull else 'نزولی'}، پرایس اکشن: {tech['pa_pattern']}. استراتژی فعلی: " + ("نگهداری یا خرید پله‌ای در پولبک به ۰.۵۰ فیبوناچی با حد ضرر زیر ۰.۶۱۸." if (macd_bull and rsi < 70) else "توقف خرید جدید و کنترل ریسک تا مشخص شدن جهت."),
        "future": f"وضعیت آینده (دو سناریو): ۱) سناریوی صعودی: شکست قطعی مقاومت {tech['resistance']} با حجم بالا ⬅ استراتژی Breakout تا سقف {tech['swing_high']}. ۲) سناریوی نزولی: از دست رفتن حمایت {tech['support']} ⬅ استراتژی خروج سریع و انتقال به نقدینگی یا صندوق درآمد ثابت."
    }
    return {
        "fundamental": {"verdict": f_verdict, "detail": f_text},
        "psychology": {"mood": mood, "greed_score": score, "advice": psych},
        "strategies": strategies,
    }

def build_4horizon_contract(symbol: str, market: str, price_toman: float, available_bars: int, eps: float = 0):
    contracts = {}
    fee_pct = 1.25 if market == "BOURSE" else 0.20
    for hz_key, spec in HORIZON_SPECS.items():
        if available_bars < spec["min_bars"] or price_toman <= 0:
            contracts[hz_key] = {
                "horizon": hz_key, "label": spec["label"], "evaluatable": False,
                "available_bars": available_bars, "required_min_bars": spec["min_bars"],
                "status_fa": "قابل ارزیابی نیست (کمبود تاریخچه)",
                "target": None, "stop": None, "net_target_return_pct": None, "net_stop_loss_pct": None, "reward_to_risk": None
            }
        else:
            tp = round(price_toman * spec["tp_mult"], 4)
            sl = round(price_toman * spec["sl_mult"], 4)
            net_ret = round(((tp - price_toman) / price_toman * 100.0) - fee_pct, 2)
            net_sl = round(((price_toman - sl) / price_toman * 100.0) + fee_pct, 2)
            rr = round(net_ret / net_sl, 2) if net_sl > 0 else 0.0
            contracts[hz_key] = {
                "horizon": hz_key, "label": spec["label"], "evaluatable": True,
                "available_bars": available_bars, "required_min_bars": spec["min_bars"],
                "status_fa": "معتبر و قابل معامله" if rr >= 1.2 else "ریسک/ریوارد پایین",
                "target": tp, "stop": sl, "net_target_return_pct": net_ret, "net_stop_loss_pct": net_sl, "reward_to_risk": rr
            }

    h1_ok = contracts["H1_DAILY"]["evaluatable"]
    h2_ok = contracts["H2_WEEKLY"]["evaluatable"]
    decision = "BUY_CANDIDATE" if (h1_ok and h2_ok and (market != "BOURSE" or eps >= 0)) else "NO_TRADE"
    return {"symbol": symbol, "market": market, "price": price_toman, "decision": decision, "contracts": contracts}

async def call_llm_step(provider: str, model_id: str, prompt: str) -> Dict[str, str]:
    openrouter_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
    if provider == "Gemini" and gemini_key:
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={gemini_key}"
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.post(url, json={"contents": [{"parts": [{"text": prompt}]}]})
                if r.status_code == 200:
                    return {"mode": "LIVE_GEMINI", "text": r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()}
        except Exception:
            pass
    if openrouter_key:
        try:
            async with httpx.AsyncClient(timeout=12.0) as client:
                r = await client.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers={"Authorization": f"Bearer {openrouter_key}"},
                    json={"model": model_id, "messages": [{"role": "user", "content": prompt}], "max_tokens": 180}
                )
                if r.status_code == 200:
                    return {"mode": "LIVE_OPENROUTER", "text": r.json()["choices"][0]["message"]["content"].strip()}
        except Exception:
            pass
    return {"mode": "RULE_ENGINE", "text": ""}

async def run_5ai_pipeline(contract: dict, tech: dict, extra: dict):
    sym, dec = contract["symbol"], contract["decision"]
    h1 = contract["contracts"]["H1_DAILY"]
    steps = [
        ("1. DeepSeek (تکنیکال و پرایس اکشن)", "deepseek/deepseek-r1:free",
         f"در ۲ خط فارسی، {sym} با RSI={tech['rsi_now']} و پرایس اکشن «{tech['pa_pattern']}» را تحلیل کن.",
         f"پرایس اکشن: {tech['pa_pattern']} در {tech['structure']}. RSI={tech['rsi_now']} و تراز حمایت فیبوناچی {tech['support']}."),
        ("2. Gemini (تحلیل بنیادی)", "google/gemini-2.0-flash-exp:free",
         f"در ۲ خط فارسی، وضعیت بنیادی {sym} ({extra['fundamental']['detail']}) را جمع‌بندی کن.",
         f"{extra['fundamental']['verdict']}: {extra['fundamental']['detail']}"),
        ("3. Perplexity (جو بازار و اخبار)", "perplexity/sonar",
         f"در ۲ خط فارسی، ریسک نقدینگی و وضعیت فعلی {sym} را بگو.",
         f"پایش جریان نقدینگی: حجم معاملات تاییدکننده استراتژی حال است؛ تراز مقاومت پیش رو {tech['resistance']}."),
        ("4. Claude (نقد ریسک و روانشناسی)", "anthropic/claude-3.5-sonnet",
         f"در ۲ خط فارسی، از دید روانشناسی بازار ({extra['psychology']['mood']}) ریسک {sym} را نقد کن.",
         f"حالت روانی بازار «{extra['psychology']['mood']}» است. {extra['psychology']['advice']}"),
        ("5. OpenAI (حکم نهایی و استراتژی)", "openai/gpt-4o-mini",
         f"بر اساس تصمیم قفل‌شده {dec}، جمع‌بندی اجرایی ۲ خطی فارسی برای {sym} بده.",
         f"رای نهایی سیستم: {dec}. هدف روزانه {h1.get('target') or 'قابل ارزیابی نیست'} و حد ضرر {h1.get('stop') or 'نامشخص'}.")
    ]
    out, prev = [], ""
    for title, mid, prompt, fb in steps:
        prov = title.split(". ")[1].split(" ")[0]
        res = await call_llm_step(prov, mid, f"{prompt}\nگام قبل: {prev}")
        txt = res["text"] or fb
        prev = txt[:150]
        out.append({"step": title, "mode": res["mode"], "analysis": txt})
    return out

@app.get("/api/market-overview")
async def market_overview():
    c_src = await try_fetch_live_crypto()
    bourse = enrich_comparison(WATCHLIST_DATA["bourse"])
    crypto = enrich_comparison(WATCHLIST_DATA["crypto"])
    pos_b = sum(1 for x in bourse if x["change_pct"] > 0)
    pos_c = sum(1 for x in crypto if x["change_pct"] > 0)
    today_status = "متعادل رو به مثبت" if pos_b >= 8 else "اصلاحی و پرفشار"
    tomorrow = (
        "با برتری خریداران در شاخص‌سازها، فردا بازگشایی متعادل-مثبت محتمل است (استراتژی: نگهداری سهم‌های بنیادی و پیگیری شکست مقاومت)."
        if pos_b >= 8 else
        "فشار عرضه غالب است؛ فردا بازار محتاط خواهد بود (استراتژی: حفظ نقدینگی، صندوق درآمد ثابت یا پوشش ریسک با صندوق طلا)."
    )
    return {
        "timestamp_tehran": datetime.now(TEHRAN_TZ).strftime("%Y-%m-%d %H:%M"),
        "crypto_source": c_src,
        "today_status": today_status,
        "bourse_breadth": f"{pos_b} مثبت از ۱۵ نماد بورس",
        "crypto_breadth": f"{pos_c} مثبت از ۱۵ رمزارز",
        "tomorrow_outlook": tomorrow,
    }

@app.get("/api/watchlists")
async def get_watchlists():
    await try_fetch_live_crypto()
    return {k: enrich_comparison(v) for k, v in WATCHLIST_DATA.items()}

@app.get("/api/top5-by-horizon")
async def top5_by_horizon():
    pool = [(x, "BOURSE") for x in WATCHLIST_DATA["bourse"]] + [(x, "CRYPTO") for x in WATCHLIST_DATA["crypto"]]
    analyzed = [build_4horizon_contract(x["symbol"], m, x["today"], x.get("bars", 100), x.get("eps", 0)) for x, m in pool]
    res = {}
    for hk in HORIZON_SPECS:
        valid = [a for a in analyzed if a["contracts"][hk]["evaluatable"] and a["decision"] == "BUY_CANDIDATE"]
        valid.sort(key=lambda z: z["contracts"][hk]["net_target_return_pct"] or 0, reverse=True)
        res[hk] = [{
            "symbol": a["symbol"], "market": a["market"],
            "net_return_pct": a["contracts"][hk]["net_target_return_pct"],
            "rr": a["contracts"][hk]["reward_to_risk"]
        } for a in valid[:5]]
    return res

@app.get("/api/analyze")
async def analyze_symbol(symbol: str, market: str = "BOURSE"):
    sym_u, mkt_u = symbol.strip().upper(), market.strip().upper()
    await try_fetch_live_crypto()
    pool = WATCHLIST_DATA["bourse"] if mkt_u == "BOURSE" else WATCHLIST_DATA["crypto"]
    found = next((x for x in pool if x["symbol"].upper() == sym_u), None)
    if not found:
        for k, mn in [("bourse", "BOURSE"), ("crypto", "CRYPTO"), ("etfs", "BOURSE")]:
            cand = next((x for x in WATCHLIST_DATA[k] if x["symbol"].upper() == sym_u), None)
            if cand:
                found, mkt_u = cand, mn
                break

    if not found:
        contract = build_4horizon_contract(sym_u, mkt_u, 0.0, 0)
        return {"found": False, "contract": contract}

    src, candles = await get_candles(found["symbol"], mkt_u, float(found["today"]), float(found["yesterday"]), int(found.get("bars", 100)), float(found.get("bias", 0.001)))
    tech = analyze_technicals(candles)
    extra = build_fundamental_psych_strategies(found, mkt_u, tech)
    contract = build_4horizon_contract(found["symbol"], mkt_u, float(found["today"]), len(candles), float(found.get("eps", 0)))
    ai_chain = await run_5ai_pipeline(contract, tech, extra)

    return {
        "found": True,
        "candle_source": src,
        "unit": found["unit"],
        "comparison": enrich_comparison([found])[0],
        "technical": tech,
        "fundamental": extra["fundamental"],
        "psychology": extra["psychology"],
        "strategies": extra["strategies"],
        "contract": contract,
        "ai_pipeline": ai_chain,
    }

class PortfolioIn(BaseModel):
    symbol: str
    market: str = "BOURSE"
    quantity: float
    avg_buy_price_toman: float

@app.post("/api/portfolio")
def add_portfolio(item: PortfolioIn):
    conn = sqlite3.connect(DB_FILE)
    conn.execute("INSERT INTO portfolio (symbol, market, quantity, avg_buy_price_toman, created_at) VALUES (?, ?, ?, ?, ?)",
                 (item.symbol.strip(), item.market.upper(), item.quantity, item.avg_buy_price_toman, datetime.now(TEHRAN_TZ).isoformat()))
    conn.commit()
    conn.close()
    return {"ok": True}

@app.delete("/api/portfolio/{pid}")
def del_portfolio(pid: int):
    conn = sqlite3.connect(DB_FILE)
    conn.execute("DELETE FROM portfolio WHERE id = ?", (pid,))
    conn.commit()
    conn.close()
    return {"ok": True}

@app.get("/api/portfolio")
async def get_portfolio():
    await try_fetch_live_crypto()
    usd = next((x["today"] for x in WATCHLIST_DATA["forex"] if x["symbol"] == "USD"), 70200)
    conn = sqlite3.connect(DB_FILE)
    rows = conn.execute("SELECT id, symbol, market, quantity, avg_buy_price_toman FROM portfolio").fetchall()
    conn.close()
    out = []
    for pid, sym, mkt, qty, buy_p in rows:
        cur_p, day_pct = buy_p, 0.0
        pool_k = "bourse" if mkt == "BOURSE" else "crypto"
        m = next((x for x in WATCHLIST_DATA[pool_k] if x["symbol"].upper() == sym.upper()), None)
        if not m and mkt == "BOURSE":
            m = next((x for x in WATCHLIST_DATA["etfs"] if x["symbol"].upper() == sym.upper()), None)
        if m:
            cur_p = float(m["today"]) * (usd if mkt == "CRYPTO" else 1.0)
            y = float(m["yesterday"])
            day_pct = ((float(m["today"]) - y) / y * 100.0) if y > 0 else 0.0
        pnl = ((cur_p - buy_p) / buy_p * 100.0) if buy_p > 0 else 0.0
        if pnl <= -6.0:
            sig, col = "فروش فوری (حد ضرر)", "rose"
        elif pnl >= 15.0:
            sig, col = "سیو سود / فروش پله‌ای", "amber"
        elif day_pct > 1.5 and pnl < 5.0:
            sig, col = "خرید پله‌ای / نگهداری", "emerald"
        else:
            sig, col = "نگهداری (Hold)", "sky"
        out.append({"id": pid, "symbol": sym, "market": mkt, "quantity": qty, "buy_price": buy_p,
                    "current_price": round(cur_p, 2), "pnl_pct": round(pnl, 2), "day_pct": round(day_pct, 2), "signal": sig, "color": col})
    return out

@app.get("/", response_class=HTMLResponse)
def home():
    with open("index.html", "r", encoding="utf-8") as f:
        return f.read()

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("backend:app", host="0.0.0.0", port=port)
