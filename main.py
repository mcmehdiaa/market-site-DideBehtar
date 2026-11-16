import os, time, asyncio, sqlite3
from datetime import datetime
from typing import List, Dict, Any, Optional
import uvicorn
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from news_cal import TEHRAN_TZ, fetch_economic_calendar, fetch_asset_news
from quant_math import (
    HORIZON_SPECS, _f, calc_ema, calc_wilder_rsi_points, calc_bollinger,
    detect_price_action, detect_harmonics, detect_patterns_and_channel,
    build_candle_heatmap, detect_divergences, analyze_candlesticks_tv,
    analyze_smart_money, build_unified_coherence, run_backtest_180d, evaluate_horizon
)
from market_data import (
    norm_fa, jalali_to_gregorian, enrich_comparison, load_macro_live,
    load_all_crypto, load_all_bourse, fetch_candles_tf, TF_BINANCE, TF_LABELS
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = "/tmp/standalone_market.db" if os.path.isdir("/tmp") else os.path.join(BASE_DIR, "standalone_market.db")
app = FastAPI(title="فاز ۴ نهایی - تایم‌فریم کامل، تقویم و اخبار")

def get_conn():
    c = sqlite3.connect(DB_FILE)
    c.execute("CREATE TABLE IF NOT EXISTS portfolio (id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT, market TEXT, quantity REAL, avg_buy_price_toman REAL, created_at TEXT)")
    c.commit(); return c

def analyze_full(symbol: str, market: str, item: Dict[str, Any], candles: List[Dict[str, Any]], candles_1d: Optional[List[Dict[str, Any]]] = None,
                 fng_data: Optional[dict] = None, news_data: Optional[dict] = None, has_high_cal_24h: bool = False, tf: str = "1d"):
    n = len(candles); closes, highs, lows = [c["close"] for c in candles], [c["high"] for c in candles], [c["low"] for c in candles]
    price = closes[-1]
    rsi_pts = calc_wilder_rsi_points(candles, 14); rsi_now = rsi_pts[-1]["value"] if rsi_pts else None
    ema12, ema26 = calc_ema(closes, 12), calc_ema(closes, 26)
    ema20, ema50 = [round(x, 6) for x in calc_ema(closes, 20)], [round(x, 6) for x in calc_ema(closes, 50)]
    bb_up, bb_lo = calc_bollinger(closes, 20, 2.0)
    macd_l = [round(a - b, 6) for a, b in zip(ema12, ema26)]; sig_l = [round(x, 6) for x in calc_ema(macd_l, 9)]; hist_l = [round(m - s, 6) for m, s in zip(macd_l, sig_l)]
    sh, sl = max(highs[-120:]), min(lows[-120:]); diff = sh - sl
    fib = {"0.0 (سقف)": round(sh, 6), "0.236": round(sh - 0.236*diff, 6), "0.382": round(sh - 0.382*diff, 6), "0.500": round(sh - 0.500*diff, 6), "0.618 (طلایی)": round(sh - 0.618*diff, 6), "1.0 (کف)": round(sl, 6)}
    pa_markers, pa_sup, pa_res = detect_price_action(candles)
    patterns, harmonics, heatmap = detect_patterns_and_channel(candles), detect_harmonics(candles), build_candle_heatmap(candles, rsi_pts)
    divergences, candlesticks, smart_money = detect_divergences(candles, rsi_pts), analyze_candlesticks_tv(candles), analyze_smart_money(candles)
    structure = "صعودی (بالای EMA20 و EMA50)" if price > ema20[-1] > ema50[-1] else ("نزولی (زیر EMA20 و EMA50)" if price < ema20[-1] < ema50[-1] else "رنج / تغییر فاز")

    # محاسبه ۴ بازه (روزانه تا ۱۲۰ روزه) همیشه روی دیتای استاندارد 1D
    d1 = candles_1d if (candles_1d and len(candles_1d) > 0) else candles
    n1 = len(d1); c1 = [x["close"] for x in d1]; p1 = c1[-1]
    r1 = [abs(c1[i]-c1[i-1])/c1[i-1] for i in range(1, n1) if c1[i-1] > 0]
    dv1 = max(min((sum(r1[-20:])/len(r1[-20:])) if r1 else 0.02, 0.08), 0.01)
    rp1 = calc_wilder_rsi_points(d1, 14); rn1 = rp1[-1]["value"] if rp1 else None
    e9_1, e20_1, e50_1 = [round(x,6) for x in calc_ema(c1,9)], [round(x,6) for x in calc_ema(c1,20)], [round(x,6) for x in calc_ema(c1,50)]
    m1 = [round(a-b,6) for a,b in zip(calc_ema(c1,12), calc_ema(c1,26))]; s1 = [round(x,6) for x in calc_ema(m1,9)]; h1 = [round(x-y,6) for x,y in zip(m1,s1)]
    _, sup1, res1 = detect_price_action(d1); backtest = run_backtest_180d(d1, market)
    fee = 1.25 if market == "BOURSE" else 0.20
    contracts, hits = {}, 0
    for hk, sp in HORIZON_SPECS.items():
        cr = evaluate_horizon(hk, sp, n1, p1, dv1, fee, c1, e9_1, e20_1, e50_1, m1, s1, h1, rn1, sup1, res1)
        if cr["is_bullish"]: hits += 1
        contracts[hk] = cr

    coherence = build_unified_coherence(contracts, patterns, harmonics, divergences, candlesticks, smart_money, (news_data or {}).get("sentiment", "NEUTRAL"), has_high_cal_24h)
    pe, eps = _f(item.get("pe")), _f(item.get("eps"))
    if market == "BOURSE":
        st_f = "ارزنده" if (eps and eps > 0 and pe and 0 < pe < 8) else ("زیان‌ده" if (eps is not None and eps < 0) else "بررسی کدال")
        f_met = f"P/E={pe if pe is not None else '-'} | EPS={eps if eps is not None else '-'} | حجم: {int(item.get('tvol') or 0):,} | {st_f}"
        codal = f"https://codal.ir/ReportList.aspx?search&Symbol={symbol}"
    else:
        qv = float(item.get("quote_vol") or 0); fng_t = f" | ترس/طمع: {fng_data['value']}/100" if fng_data else ""
        f_met, codal = f"حجم ۲۴ساعته: {round(qv/1e6, 2)} میلیون دلار | نقدشوندگی: {'عالی' if qv > 1e7 else 'متوسط'}{fng_t}", ""

    strategies = {"past": f"گذشته ({TF_LABELS.get(tf, tf)}): کف {fib['1.0 (کف)']} تا سقف {fib['0.0 (سقف)']}.",
                  "present": f"حال ({TF_LABELS.get(tf, tf)}): {structure} | کندل: {candlesticks['bias_fa']} | الگو: {patterns['pattern_name']}.",
                  "future": f"آینده: {patterns.get('description', '')}"}
    return {
        "price": price, "tf": tf, "tf_label": TF_LABELS.get(tf, tf),
        "fundamental": {"metrics": f_met, "codal_url": codal, "news": news_data or {"items": [], "source": "NONE"}},
        "strategies": strategies, "contracts": contracts, "confluence": f"{hits}/4", "backtest": backtest,
        "divergences": divergences, "candlesticks": candlesticks, "smart_money": smart_money, "coherence": coherence, "harmonics": harmonics,
        "chart": {
            "tf": tf, "tf_label": TF_LABELS.get(tf, tf),
            "candles": [{"time": c["time"], "open": c["open"], "high": c["high"], "low": c["low"], "close": c["close"]} for c in candles],
            "volume": [{"time": c["time"], "value": c["vol"], "color": "rgba(16,185,129,0.35)" if c["close"] >= c["open"] else "rgba(239,68,68,0.35)"} for c in candles],
            "heatmap": heatmap, "ema20": [{"time": candles[i]["time"], "value": ema20[i]} for i in range(n)], "ema50": [{"time": candles[i]["time"], "value": ema50[i]} for i in range(n)],
            "bb_upper": [{"time": candles[i]["time"], "value": bb_up[i]} for i in range(n)], "bb_lower": [{"time": candles[i]["time"], "value": bb_lo[i]} for i in range(n)],
            "rsi": rsi_pts, "macd": [{"time": candles[i]["time"], "value": macd_l[i]} for i in range(n)],
            "macd_signal": [{"time": candles[i]["time"], "value": sig_l[i]} for i in range(n)],
            "macd_hist": [{"time": candles[i]["time"], "value": hist_l[i], "color": "#10b981" if hist_l[i] >= 0 else "#ef4444"} for i in range(n)],
            "pa_markers": pa_markers, "pa_support": pa_sup, "pa_resistance": pa_res, "fib": fib, "rsi_now": rsi_now, "patterns": patterns, "divergences": divergences, "harmonics": harmonics
        }
    }

@app.get("/api/self-test")
async def run_self_test(brs_key: str = "", proxy_url: str = ""):
    checks = []
    rc = [{"time": 1700000000 + i*86400, "open": c, "high": c, "low": c, "close": c, "vol": 100} for i, c in enumerate([44.34,44.09,44.15,43.61,44.33,44.83,45.10,45.42,45.84,46.08,45.89,46.03,45.61,46.28,46.28,46.00])]
    ro = calc_wilder_rsi_points(rc, 14)
    checks.append({"name": "Wilder RSI(14) Reference Math", "passed": len(ro)==2 and abs(ro[0]["value"]-70.46)<0.1 and abs(ro[1]["value"]-66.25)<0.1, "detail": "70.46, 66.25"})
    checks.append({"name": "Jalali-to-Gregorian Calendar Math", "passed": jalali_to_gregorian(1403,1,1)==(2024,3,20) and jalali_to_gregorian(1405,8,24)==(2026,11,15), "detail": "OK"})
    cal, btc_n, pepe_n, macro, b_data = await asyncio.gather(fetch_economic_calendar(), fetch_asset_news("BTC", "CRYPTO"), fetch_asset_news("PEPE", "CRYPTO"), load_macro_live(brs_key, force=True), load_all_bourse(brs_key, proxy_url))
    c_data = await load_all_crypto(force=True, usdt_toman=macro["usdt_toman"])
    checks.append({"name": "Live Economic Calendar", "passed": len(cal["events"]) >= 1, "detail": f"events={len(cal['events'])}, {cal['source']}"})
    checks.append({"name": "Live Crypto News (BTC & PEPE)", "passed": len(btc_n["items"])>=1 and len(pepe_n["items"])>=1, "detail": f"BTC={len(btc_n['items'])}({btc_n['source']}), PEPE={len(pepe_n['items'])}"})
    checks.append({"name": "Live Crypto & USDT-Toman", "passed": len(c_data["items"]) >= 300 and macro["usdt_toman"] is not None, "detail": f"coins={len(c_data['items'])}, usdt={macro['usdt_toman']}"})
    checks.append({"name": "Live Iran Bourse", "passed": len(b_data["items"]) >= 500, "detail": f"count={len(b_data['items'])}, {b_data['source']}"})
    return {"all_math_tests_passed": all(x["passed"] for x in checks[:2]), "checks": checks}

@app.get("/api/economic-calendar")
async def economic_calendar_endpoint(): return await fetch_economic_calendar()

@app.get("/api/market-heatmap")
async def market_heatmap(brs_key: str = "", proxy_url: str = ""):
    c_data, b_data = await asyncio.gather(load_all_crypto(), load_all_bourse(brs_key, proxy_url))
    return {"crypto": enrich_comparison([x for x in c_data["items"] if x["symbol"] != "USDT"][:24]), "bourse": enrich_comparison(sorted(b_data["items"], key=lambda z: z.get("tvol", 0), reverse=True)[:12])}

@app.get("/api/system-status")
async def system_status(brs_key: str = "", proxy_url: str = ""):
    macro, b_data = await asyncio.gather(load_macro_live(brs_key), load_all_bourse(brs_key, proxy_url))
    c_data = await load_all_crypto(usdt_toman=macro["usdt_toman"])
    return {"crypto_count": len(c_data["items"]), "bourse_count": len(b_data["items"]), "bourse_source": b_data["source"], "usdt_toman": macro["usdt_toman"]}

@app.get("/api/search")
async def instant_search(q: str = "", brs_key: str = "", proxy_url: str = ""):
    qn = norm_fa(q); macro, b_data = await asyncio.gather(load_macro_live(brs_key), load_all_bourse(brs_key, proxy_url))
    c_data = await load_all_crypto(usdt_toman=macro["usdt_toman"])
    res = [{"symbol": x["symbol"], "name": x["name"], "market": "BOURSE", "today": x["today"], "unit": "تومان"} for x in b_data["items"] if not qn or qn in x["search_key"]][:15]
    res += [{"symbol": x["symbol"], "name": x["name"], "market": "CRYPTO", "today": x["today"], "unit": x["unit"]} for x in c_data["items"] if not qn or qn in x["search_key"]][:20]
    return {"results": res}

@app.get("/api/analyze")
async def analyze_endpoint(symbol: str, market: str = "AUTO", tf: str = "1d", brs_key: str = "", proxy_url: str = ""):
    t0 = time.time(); qn = norm_fa(symbol); mkt = market.strip().upper(); tf = tf if tf in TF_BINANCE else "1d"
    macro, b_data, cal = await asyncio.gather(load_macro_live(brs_key), load_all_bourse(brs_key, proxy_url), fetch_economic_calendar())
    c_data = await load_all_crypto(usdt_toman=macro["usdt_toman"])
    item = next((x for x in b_data["items"] if norm_fa(x["symbol"]) == qn), None) if mkt in ("AUTO", "BOURSE") else None
    if item: mkt = "BOURSE"
    if not item and mkt in ("AUTO", "CRYPTO"):
        item = next((x for x in c_data["items"] if norm_fa(x["symbol"]) == qn or qn in x["search_key"]), None)
        if item: mkt = "CRYPTO"
    if not item: return {"found": False, "elapsed_ms": round((time.time()-t0)*1000, 1)}
    if tf == "1d":
        cres, news_res = await asyncio.gather(fetch_candles_tf(item["symbol"], mkt, item, "1d", brs_key, proxy_url), fetch_asset_news(item["symbol"], mkt))
        c1d = cres
    else:
        cres, c1d, news_res = await asyncio.gather(fetch_candles_tf(item["symbol"], mkt, item, tf, brs_key, proxy_url), fetch_candles_tf(item["symbol"], mkt, item, "1d", brs_key, proxy_url), fetch_asset_news(item["symbol"], mkt))
    if not cres["candles"]: return {"found": True, "no_candles": True, "candle_source": cres["source"]}
    return {"found": True, "no_candles": False, "symbol": item["symbol"], "display_name": item["name"], "market": mkt, "unit": item["unit"], "candle_source": cres["source"],
            "bars_count": len(cres["candles"]), "elapsed_ms": round((time.time()-t0)*1000, 1), **analyze_full(item["symbol"], mkt, item, cres["candles"], c1d["candles"], macro.get("fng"), news_res, cal.get("has_high_24h", False), tf)}

@app.get("/api/top10-scanner")
async def top10_scanner(brs_key: str = "", proxy_url: str = ""):
    c_data, b_data = await asyncio.gather(load_all_crypto(), load_all_bourse(brs_key, proxy_url))
    cands = [(x, "CRYPTO") for x in c_data["items"] if x.get("today") and x["symbol"] != "USDT"][:30] + [(x, "BOURSE") for x in sorted(b_data["items"], key=lambda z: z.get("tvol", 0), reverse=True)[:10]]
    cres = await asyncio.gather(*[fetch_candles_tf(it["symbol"], mk, it, "1d", brs_key, proxy_url) for it, mk in cands])
    an = [(it, mk, analyze_full(it["symbol"], mk, it, cr["candles"])) for (it, mk), cr in zip(cands, cres) if len(cr["candles"]) >= 16]
    top10 = {}
    for hk in HORIZON_SPECS:
        v = [{"symbol": it["symbol"], "market": mk, "net_return_pct": a["contracts"][hk]["net_return_pct"], "confluence": a["confluence"], "conf_num": int(a["confluence"].split("/")[0])} for it, mk, a in an if a["contracts"][hk]["evaluatable"] and a["contracts"][hk]["is_bullish"]]
        v.sort(key=lambda z: (z["conf_num"], z["net_return_pct"] or 0), reverse=True); top10[hk] = v[:10]
    return top10

@app.get("/api/watchlists")
async def watchlists(brs_key: str = "", proxy_url: str = ""):
    macro, b_data = await asyncio.gather(load_macro_live(brs_key), load_all_bourse(brs_key, proxy_url))
    c_data = await load_all_crypto(usdt_toman=macro["usdt_toman"]); ut, fxr = macro["usdt_toman"], macro["fx_rates"]
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
async def get_pf(brs_key: str = "", proxy_url: str = ""):
    macro, b_data = await asyncio.gather(load_macro_live(brs_key), load_all_bourse(brs_key, proxy_url))
    c_data = await load_all_crypto(usdt_toman=macro["usdt_toman"]); ut = macro["usdt_toman"]
    c = get_conn(); rows = c.execute("SELECT id, symbol, market, quantity, avg_buy_price_toman FROM portfolio").fetchall(); c.close()
    out = []
    for pid, sym, mkt, qty, bp in rows:
        m = next((x for x in (b_data["items"] if mkt == "BOURSE" else c_data["items"]) if norm_fa(x["symbol"]) == norm_fa(sym)), None)
        if not m or m.get("today") is None or (mkt == "CRYPTO" and sym.upper() != "USDT" and ut is None): out.append({"id": pid, "symbol": sym, "market": mkt, "quantity": qty, "buy_price": bp, "current_price": None, "pnl_pct": None, "signal": "دیتای زنده موجود نیست"})
        else:
            cp = float(m["today"]) * (1.0 if (mkt == "BOURSE" or sym.upper() == "USDT") else ut); pnl = round((cp - bp) / bp * 100.0, 2) if bp > 0 else 0.0
            out.append({"id": pid, "symbol": sym, "market": mkt, "quantity": qty, "buy_price": bp, "current_price": round(cp, 2), "pnl_pct": pnl, "signal": "فروش (حد ضرر)" if pnl <= -6 else ("سیو سود" if pnl >= 15 else "نگهداری")})
    return out

@app.get("/", response_class=HTMLResponse)
def home():
    with open(os.path.join(BASE_DIR, "index.html"), "r", encoding="utf-8") as f: return f.read()

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
