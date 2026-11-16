import math
from typing import List, Dict, Any, Optional

HORIZON_SPECS = {
    "H1_DAILY":   {"label": "روزانه",   "min_bars": 15,  "vol_scale": 1.4},
    "H2_WEEKLY":  {"label": "هفتگی",    "min_bars": 25,  "vol_scale": 3.2},
    "H3_MONTHLY": {"label": "ماهانه",   "min_bars": 45,  "vol_scale": 6.5},
    "H4_120D":    {"label": "۱۲۰ روزه", "min_bars": 120, "vol_scale": 12.0},
}

def _f(v) -> Optional[float]:
    try:
        return None if (v is None or str(v).strip() == "") else float(str(v).replace(",", "").strip())
    except Exception:
        return None

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

def detect_harmonics(candles: List[Dict[str, Any]]) -> Dict[str, Any]:
    if len(candles) < 35: return {"available": False, "name": "داده کافی نیست"}
    win = candles[-100:]; pivots = []
    for i in range(2, len(win) - 2):
        h, l = win[i]["high"], win[i]["low"]
        if h >= max(win[i-2]["high"], win[i-1]["high"], win[i+1]["high"], win[i+2]["high"]):
            if not pivots or pivots[-1]["type"] != "H": pivots.append({"time": win[i]["time"], "val": h, "type": "H"})
            elif h > pivots[-1]["val"]: pivots[-1] = {"time": win[i]["time"], "val": h, "type": "H"}
        elif l <= min(win[i-2]["low"], win[i-1]["low"], win[i+1]["low"], win[i+2]["low"]):
            if not pivots or pivots[-1]["type"] != "L": pivots.append({"time": win[i]["time"], "val": l, "type": "L"})
            elif l < pivots[-1]["val"]: pivots[-1] = {"time": win[i]["time"], "val": l, "type": "L"}
    if len(pivots) < 5: return {"available": False, "name": "الگوی هارمونیک معتبری تشکیل نشده"}
    for start in range(len(pivots) - 5, max(-1, len(pivots) - 8), -1):
        X, A, B, C, D = pivots[start:start + 5]
        xa, ab, bc, cd, ad = abs(A["val"]-X["val"]), abs(B["val"]-A["val"]), abs(C["val"]-B["val"]), abs(D["val"]-C["val"]), abs(D["val"]-A["val"])
        if min(xa, ab, bc, cd) <= 1e-12: continue
        ab_xa, bc_ab, cd_bc, ad_xa = ab/xa, bc/ab, cd/bc, ad/xa; bull = D["type"] == "L"
        dfa = "صعودی (PRZ خرید)" if bull else "نزولی (PRZ فروش)"; matched = None
        if 0.55 <= ab_xa <= 0.68 and 0.35 <= bc_ab <= 0.90 and 0.72 <= ad_xa <= 0.85: matched = f"هارمونیک گارتلی {dfa}"
        elif 0.35 <= ab_xa <= 0.54 and 0.35 <= bc_ab <= 0.90 and 0.82 <= ad_xa <= 0.95: matched = f"هارمونیک خفاش {dfa}"
        elif 0.72 <= ab_xa <= 0.85 and 0.35 <= bc_ab <= 0.90 and 1.20 <= ad_xa <= 1.68: matched = f"هارمونیک پروانه {dfa}"
        elif 0.35 <= ab_xa <= 0.65 and 0.35 <= bc_ab <= 0.90 and 1.52 <= ad_xa <= 1.72: matched = f"هارمونیک خرچنگ {dfa}"
        elif 0.58 <= bc_ab <= 0.82 and 1.18 <= cd_bc <= 1.68 and 0.85 <= (cd/ab) <= 1.18: matched = f"هارمونیک AB=CD {dfa}"
        if matched:
            return {"available": True, "name": matched, "bullish": bull, "ratios": f"AB/XA={round(ab_xa,2)} | BC/AB={round(bc_ab,2)} | AD/XA={round(ad_xa,2)}",
                    "points": [{"time": p["time"], "value": round(p["val"], 6)} for p in (X, A, B, C, D)], "prz": round(D["val"], 6)}
    return {"available": False, "name": "الگوی هارمونیک معتبری تشکیل نشده"}

def detect_patterns_and_channel(candles: List[Dict[str, Any]]) -> Dict[str, Any]:
    if len(candles) < 20: return {"available": False, "pattern_name": "داده ناکافی", "bias": "NEUTRAL"}
    win = candles[-35:] if len(candles) >= 35 else candles; m_n = len(win)
    closes, highs, lows = [c["close"] for c in win], [c["high"] for c in win], [c["low"] for c in win]
    xm, ym = (m_n - 1) / 2.0, sum(closes) / m_n
    slope = sum((i - xm) * (closes[i] - ym) for i in range(m_n)) / (sum((i - xm) ** 2 for i in range(m_n)) or 1.0)
    inter = ym - slope * xm; spct = (slope / max(ym, 1e-12)) * 100.0
    ud = max(highs[i] - (slope * i + inter) for i in range(m_n)); ld = max((slope * i + inter) - lows[i] for i in range(m_n))
    us, ue = round(inter + ud, 6), round(slope * (m_n - 1) + inter + ud, 6); ls, le = round(inter - ld, 6), round(slope * (m_n - 1) + inter - ld, 6)
    half = m_n // 2; h1, h2 = max(highs[:half]), max(highs[half:]); l1, l2 = min(lows[:half]), min(lows[half:])
    r1, r2 = h1 - l1, h2 - l2; up_sl, lo_sl = (h2 - h1)/max(h1, 1e-12), (l2 - l1)/max(l1, 1e-12)
    pole = candles[-45:-15] if len(candles) >= 45 else candles[:max(1, len(candles) - 15)]
    pm = ((pole[-1]["close"] - pole[0]["close"]) / max(pole[0]["close"], 1e-12)) * 100.0
    ph = max(max(c["high"] for c in pole) - min(c["low"] for c in pole), 0.0)
    lu0, lu1, ll0, ll1 = us, ue, ls, le
    if up_sl > 0.005 and lo_sl > up_sl * 1.25 and r2 < r1 * 0.85:
        nm, bs, lu0, lu1, ll0, ll1, brk, tgt, ds = "کنج صعودی (Rising Wedge)", "BEARISH", round(h1,6), round(h2,6), round(l1,6), round(l2,6), round(l2,6), round(l2-r1*0.7,6), f"شکست کف {round(l2,4)} هشدار ریزش است."
    elif up_sl < -0.005 and lo_sl < 0 and abs(up_sl) > abs(lo_sl) * 1.25 and r2 < r1 * 0.85:
        nm, bs, lu0, lu1, ll0, ll1, brk, tgt, ds = "کنج نزولی (Falling Wedge)", "BULLISH", round(h1,6), round(h2,6), round(l1,6), round(l2,6), round(h2,6), round(h2+r1*0.7,6), f"تخلیه فروش؛ شکست سقف {round(h2,4)} ماشه صعود است."
    elif h2 < h1 * 0.995 and l2 > l1 * 1.005 and r2 < r1 * 0.78:
        nm, bs, lu0, lu1, ll0, ll1, brk, tgt, ds = "مثلث فشردگی", "NEUTRAL", round(h1,6), round(h2,6), round(l1,6), round(l2,6), round(h2,6), round(h2+r1*0.75,6), f"فشردگی بین {round(l2,4)} و {round(h2,4)}."
    elif pm >= 10.0 and -0.85 <= spct <= 0.15 and (ue - le) < ph * 0.55:
        nm, bs, brk, tgt, ds = "پرچم صعودی", "BULLISH", ue, round(ue + ph * 0.65, 6), f"رشد قبلی (+{round(pm,1)}%)؛ شکست {ue} ماشه صعود."
    elif pm <= -10.0 and -0.15 <= spct <= 0.85 and (ue - le) < ph * 0.55:
        nm, bs, brk, tgt, ds = "پرچم نزولی", "BEARISH", le, round(max(le - ph * 0.65, le * 0.35), 6), f"ریزش قبلی ({round(pm,1)}%)؛ شکست کف {le} پرریسک است."
    elif spct > 0.12: nm, bs, brk, tgt, ds = "کانال صعودی", "BULLISH", ue, round(ue+(ue-le)*0.5,6), f"شیب +{round(spct,2)}%/روز؛ حمایت {le}، سقف {ue}."
    elif spct < -0.12: nm, bs, brk, tgt, ds = "کانال نزولی", "BEARISH", ue, round(ue+(ue-le)*0.5,6), f"شیب {round(spct,2)}%/روز؛ خروج با شکست سقف {ue}."
    else: nm, bs, brk, tgt, ds = "کانال رنج", "NEUTRAL", ue, round(ue+(ue-le)*0.6,6), f"نوسان بین {le} و {ue}."
    return {"available": True, "pattern_name": nm, "bias": bs, "description": ds,
            "upper_line": [{"time": win[0]["time"], "value": lu0}, {"time": win[-1]["time"], "value": lu1}],
            "lower_line": [{"time": win[0]["time"], "value": ll0}, {"time": win[-1]["time"], "value": ll1}],
            "breakout_price": brk, "pattern_target": tgt}

def build_candle_heatmap(candles: List[Dict[str, Any]], rsi_pts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    closes = [c["close"] for c in candles]; ema9, ema20 = calc_ema(closes, 9), calc_ema(closes, 20); rmap = {p["time"]: p["value"] for p in rsi_pts}; out = []
    for i, c in enumerate(candles):
        r = rmap.get(c["time"], 50.0); spread = ((ema9[i] - ema20[i]) / max(ema20[i], 1e-12)) * 100.0
        sc = max(-100.0, min(100.0, round((r - 50.0) * 2.0 + spread * 12.0, 1)))
        col = "#10b981" if sc >= 35 else ("#059669" if sc >= 10 else ("#ef4444" if sc <= -35 else ("#b91c1c" if sc <= -10 else "#475569")))
        out.append({"time": c["time"], "value": sc, "color": col})
    return out

def detect_divergences(candles: List[Dict[str, Any]], rsi_pts: List[Dict[str, Any]]) -> Dict[str, Any]:
    if len(candles) < 30 or len(rsi_pts) < 12: return {"found": False, "bias": "NEUTRAL", "summary": "داده کافی نیست", "items": []}
    rmap = {p["time"]: p["value"] for p in rsi_pts}; win = candles[-70:]; lows, highs = [], []
    for i in range(2, len(win) - 2):
        t = win[i]["time"]
        if t not in rmap: continue
        if win[i]["low"] <= min(win[i-2]["low"], win[i-1]["low"], win[i+1]["low"], win[i+2]["low"]): lows.append((t, win[i]["low"], rmap[t]))
        if win[i]["high"] >= max(win[i-2]["high"], win[i-1]["high"], win[i+1]["high"], win[i+2]["high"]): highs.append((t, win[i]["high"], rmap[t]))
    items = []
    if len(lows) >= 2:
        p1, p2 = lows[-2], lows[-1]
        if p2[1] < p1[1]*0.995 and p2[2] > p1[2]+2.0: items.append({"type":"BULLISH_REGULAR","title":"واگرایی مثبت عادی (RD+)","color":"#10b981","desc":f"کف قیمت پایین‌تر، RSI بالاتر ({p1[2]}⬅{p2[2]}).","price_line":[{"time":p1[0],"value":p1[1]},{"time":p2[0],"value":p2[1]}],"rsi_line":[{"time":p1[0],"value":p1[2]},{"time":p2[0],"value":p2[2]}]})
        elif p2[1] > p1[1]*1.005 and p2[2] < p1[2]-2.0: items.append({"type":"BULLISH_HIDDEN","title":"واگرایی مثبت مخفی (HD+)","color":"#22c55e","desc":"تایید ادامه روند صعودی.","price_line":[{"time":p1[0],"value":p1[1]},{"time":p2[0],"value":p2[1]}],"rsi_line":[{"time":p1[0],"value":p1[2]},{"time":p2[0],"value":p2[2]}]})
    if len(highs) >= 2:
        q1, q2 = highs[-2], highs[-1]
        if q2[1] > q1[1]*1.005 and q2[2] < q1[2]-2.0: items.append({"type":"BEARISH_REGULAR","title":"واگرایی منفی عادی (RD-)","color":"#ef4444","desc":f"سقف قیمت بالاتر، RSI پایین‌تر ({q1[2]}⬅{q2[2]}).","price_line":[{"time":q1[0],"value":q1[1]},{"time":q2[0],"value":q2[1]}],"rsi_line":[{"time":q1[0],"value":q1[2]},{"time":q2[0],"value":q2[2]}]})
        elif q2[1] < q1[1]*0.995 and q2[2] > q1[2]+2.0: items.append({"type":"BEARISH_HIDDEN","title":"واگرایی منفی مخفی (HD-)","color":"#f43f5e","desc":"تایید ادامه روند نزولی.","price_line":[{"time":q1[0],"value":q1[1]},{"time":q2[0],"value":q2[1]}],"rsi_line":[{"time":q1[0],"value":q1[2]},{"time":q2[0],"value":q2[2]}]})
    if not items: return {"found": False, "bias": "NEUTRAL", "summary": "واگرایی معتبری دیده نشد.", "items": []}
    return {"found": True, "bias": "BULLISH" if all("BULLISH" in x["type"] for x in items) else ("BEARISH" if all("BEARISH" in x["type"] for x in items) else "MIXED"), "summary": " | ".join(x["title"] for x in items), "items": items}

def analyze_candlesticks_tv(candles: List[Dict[str, Any]]) -> Dict[str, Any]:
    if len(candles) < 3: return {"bias": "NEUTRAL", "bias_fa": "خنثی", "score": 0, "patterns": []}
    def _i(c):
        b = abs(c["close"] - c["open"]); r = max(c["high"] - c["low"], 1e-12)
        return c["open"], c["close"], b, r, c["high"]-max(c["open"],c["close"]), min(c["open"],c["close"])-c["low"], c["close"]>c["open"], c["close"]<c["open"]
    o2, cl2, b2, r2, uw2, lw2, u2, d2 = _i(candles[-3]); o1, cl1, b1, r1, uw1, lw1, u1, d1 = _i(candles[-2]); o0, cl0, b0, r0, uw0, lw0, u0, d0 = _i(candles[-1])
    dn = candles[-1]["close"] < candles[-6]["close"] if len(candles) >= 6 else d1
    up = candles[-1]["close"] > candles[-6]["close"] if len(candles) >= 6 else u1
    found = []
    if lw0 > b0*2.0 and uw0 < r0*0.2 and b0 > 0 and dn: found.append({"name":"چکش صعودی (Hammer)","signal":1,"desc":"حمایت خریدار در کف"})
    if uw0 > b0*2.0 and lw0 < r0*0.2 and b0 > 0 and up: found.append({"name":"ستاره ثاقب","signal":-1,"desc":"رد قیمت از سقف"})
    if u0 and d1 and cl0 >= o1 and o0 <= cl1 and b0 > b1: found.append({"name":"پوشای صعودی","signal":1,"desc":"غلبه خریدار"})
    if d0 and u1 and cl0 <= o1 and o0 >= cl1 and b0 > b1: found.append({"name":"پوشای نزولی","signal":-1,"desc":"غلبه فروشنده"})
    if d2 and b1 < r1*0.35 and u0 and cl0 > (o2+cl2)/2.0: found.append({"name":"ستاره صبحگاهی","signal":1,"desc":"برگشت صعودی ۳کندلی"})
    if u2 and b1 < r1*0.35 and d0 and cl0 < (o2+cl2)/2.0: found.append({"name":"ستاره شامگاهی","signal":-1,"desc":"برگشت نزولی ۳کندلی"})
    if u2 and u1 and u0 and cl0 > cl1 > cl2 and b0 > r0*0.5: found.append({"name":"سه سرباز سفید","signal":1,"desc":"صعود پیوسته"})
    if d2 and d1 and d0 and cl0 < cl1 < cl2 and b0 > r0*0.5: found.append({"name":"سه کلاغ سیاه","signal":-1,"desc":"نزول پیوسته"})
    if b0/r0 < 0.12 and lw0 > r0*0.6: found.append({"name":"دوجی سنجاقک","signal":1,"desc":"جذب عرضه در کف"})
    if b0/r0 < 0.12 and uw0 > r0*0.6: found.append({"name":"دوجی سنگ‌قبر","signal":-1,"desc":"فشار فروش در سقف"})
    if not found:
        if u0 and b0 > r0*0.65: found.append({"name":"کندل قدرتمند سبز","signal":1,"desc":"برتری خریدار"})
        elif d0 and b0 > r0*0.65: found.append({"name":"کندل قدرتمند قرمز","signal":-1,"desc":"برتری فروشنده"})
        else: found.append({"name":"کندل متعادل / خنثی","signal":0,"desc":"الگوی خاص ندارد"})
    sc = sum(x["signal"] for x in found)
    return {"bias": "BULLISH" if sc>0 else ("BEARISH" if sc<0 else "NEUTRAL"), "bias_fa": "مثبت" if sc>0 else ("منفی" if sc<0 else "خنثی"), "score": sc, "patterns": found}

def analyze_smart_money(candles: List[Dict[str, Any]]) -> Dict[str, Any]:
    n = len(candles)
    if n < 22: return {"available": False, "bias": "NEUTRAL", "verdict": "داده ناکافی", "detail": ""}
    mfv = [(((c["close"]-c["low"])-(c["high"]-c["close"]))/(c["high"]-c["low"]) if c["high"]>c["low"] else 0.0)*c["vol"] for c in candles]
    vols = [max(c["vol"], 0.0) for c in candles]; sv20 = sum(vols[-20:])
    cmf20 = round(sum(mfv[-20:]) / sv20, 3) if sv20 > 0 else 0.0
    pmf = nmf = 0.0
    for i in range(max(1, n - 14), n):
        tp0, tp1 = (candles[i]["high"]+candles[i]["low"]+candles[i]["close"])/3.0, (candles[i-1]["high"]+candles[i-1]["low"]+candles[i-1]["close"])/3.0
        if tp0 > tp1: pmf += tp0 * candles[i]["vol"]
        elif tp0 < tp1: nmf += tp0 * candles[i]["vol"]
    mfi14 = 100.0 if (nmf==0 and pmf>0) else (50.0 if nmf==0 else round(100.0 - 100.0/(1.0 + pmf/nmf), 1))
    obv = [0.0]
    for i in range(1, n): obv.append(obv[-1] + (candles[i]["vol"] if candles[i]["close"]>candles[i-1]["close"] else (-candles[i]["vol"] if candles[i]["close"]<candles[i-1]["close"] else 0.0)))
    obv_up = obv[-1] > obv[-10]; avg_v = sum(vols[-21:-1]) / 20.0 if n > 21 else sum(vols) / n
    vr = round(vols[-1] / avg_v, 2) if avg_v > 0 else 1.0
    if cmf20 >= 0.05 and obv_up: bs, vd, dt = "BULLISH", "ورود پول هوشمند (انباشت 🟢)", f"CMF={cmf20}، MFI={mfi14} و OBV صعودی؛ حجم {vr}x میانگین."
    elif cmf20 <= -0.05 and not obv_up: bs, vd, dt = "BEARISH", "خروج پول هوشمند (توزیع 🔴)", f"CMF={cmf20}، MFI={mfi14} و OBV نزولی؛ نقدینگی خارج می‌شود."
    else: bs, vd, dt = "NEUTRAL", "جریان پول متعادل 🟡", f"CMF={cmf20} و MFI={mfi14} (حجم {vr}x)."
    return {"available": True, "bias": bs, "cmf20": cmf20, "mfi14": mfi14, "vol_ratio": vr, "verdict": vd, "detail": dt}

def build_unified_coherence(contracts: dict, pat: dict, harm: dict, div: dict, cs: dict, sm: dict, news_sent: str = "NEUTRAL", has_high_cal_24h: bool = False) -> Dict[str, Any]:
    bull = bear = 0
    for hk in HORIZON_SPECS:
        if contracts[hk]["is_bullish"]: bull += 15
        elif contracts[hk]["tone"] == "rose": bear += 15
    for src in (pat.get("bias"), div.get("bias"), cs.get("bias"), sm.get("bias"), news_sent):
        if src == "BULLISH": bull += 10
        elif src == "BEARISH": bear += 10
    if harm.get("available"):
        if harm.get("bullish"): bull += 10
        else: bear += 10
    conflicts = []
    if contracts["H1_DAILY"]["is_bullish"] and contracts["H4_120D"]["evaluatable"] and not contracts["H4_120D"]["is_bullish"]:
        conflicts.append("تضاد تایم‌فریم: کوتاه‌مدت (روزانه) مثبت است ولی روند ۱۲۰ روزه هنوز صعودی نشده.")
    if (contracts["H1_DAILY"]["is_bullish"] or pat.get("bias") == "BULLISH") and div.get("bias") == "BEARISH":
        conflicts.append("واگرایی منفی RSI هشدار تضعیف شتاب خرید را می‌دهد.")
    if contracts["H1_DAILY"]["is_bullish"] and sm.get("bias") == "BEARISH":
        conflicts.append("ظاهر قیمت سبز است اما جریان پول هوشمند خروج سرمایه نشان می‌دهد.")
    if has_high_cal_24h:
        conflicts.append("📅 هشدار تقویم اقتصادی: در ۲۴ ساعت آینده رویداد خیلی مهم دلاری (High Impact) در پیش است.")
    if not conflicts: conflicts.append("یکپارچگی کامل: تایم‌فریم‌ها، کندل‌ها، جریان پول و اخبار هم‌راستا هستند.")
    net = bull - bear
    vd = "برآیند یکپارچه: صعودی هم‌سو 🟢" if (net >= 25 and not has_high_cal_24h and "یکپارچگی" in conflicts[0]) else ("برآیند یکپارچه: نزولی / پرریسک 🔴" if net <= -25 else "برآیند یکپارچه: احتیاط / دارای تضاد 🟡")
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

def analyze_full(symbol: str, market: str, item: Dict[str, Any], candles: List[Dict[str, Any]], fng_data: Optional[dict] = None, news_data: Optional[dict] = None, has_high_cal_24h: bool = False):
    n = len(candles); closes, highs, lows = [c["close"] for c in candles], [c["high"] for c in candles], [c["low"] for c in candles]
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
    patterns = detect_patterns_and_channel(candles); harmonics = detect_harmonics(candles); heatmap = build_candle_heatmap(candles, rsi_pts)
    divergences = detect_divergences(candles, rsi_pts); candlesticks = analyze_candlesticks_tv(candles); smart_money = analyze_smart_money(candles); backtest = run_backtest_180d(candles, market)
    structure = "صعودی (بالای EMA20 و EMA50)" if price > ema20[-1] > ema50[-1] else ("نزولی (زیر EMA20 و EMA50)" if price < ema20[-1] < ema50[-1] else "رنج / تغییر فاز")
    fee = 1.25 if market == "BOURSE" else 0.20
    contracts, hits = {}, 0
    for hk, sp in HORIZON_SPECS.items():
        cr = evaluate_horizon(hk, sp, n, price, dvol, fee, closes, ema9, ema20, ema50, macd_l, sig_l, hist_l, rsi_now, pa_sup, pa_res)
        if cr["is_bullish"]: hits += 1
        contracts[hk] = cr
    coherence = build_unified_coherence(contracts, patterns, harmonics, divergences, candlesticks, smart_money, (news_data or {}).get("sentiment", "NEUTRAL"), has_high_cal_24h)
    pe, eps = _f(item.get("pe")), _f(item.get("eps"))
    if market == "BOURSE":
        st_f = "ارزنده" if (eps and eps > 0 and pe and 0 < pe < 8) else ("زیان‌ده" if (eps is not None and eps < 0) else "نیازمند بررسی کدال")
        fund_metrics = f"P/E={pe if pe is not None else 'نامشخص'} | EPS={eps if eps is not None else 'نامشخص'} | حجم: {int(item.get('tvol') or 0):,} | وضعیت: {st_f}"
        codal_url = f"https://codal.ir/ReportList.aspx?search&Symbol={symbol}"
    else:
        qv = float(item.get("quote_vol") or 0)
        fng_t = f" | ترس/طمع کل: {fng_data['value']}/100 ({fng_data['label']})" if fng_data else ""
        fund_metrics = f"حجم ۲۴ ساعته: {round(qv/1e6, 2)} میلیون دلار | نقدشوندگی: {'عالی' if qv > 1e7 else 'متوسط'}{fng_t}"
        codal_url = ""
    strategies = {"past": f"گذشته: کف {fib['1.0 (کف)']} تا سقف {fib['0.0 (سقف)']}.", "present": f"حال: {structure} | کندل: {candlesticks['bias_fa']} | الگو: {patterns['pattern_name']}.", "future": f"آینده: {patterns.get('description', '')}"}
    return {
        "price": price, "fundamental": {"metrics": fund_metrics, "codal_url": codal_url, "news": news_data or {"items": [], "source": "NONE"}},
        "strategies": strategies, "contracts": contracts, "confluence": f"{hits}/4", "backtest": backtest,
        "divergences": divergences, "candlesticks": candlesticks, "smart_money": smart_money, "coherence": coherence, "harmonics": harmonics,
        "chart": {
            "candles": [{"time": c["time"], "open": c["open"], "high": c["high"], "low": c["low"], "close": c["close"]} for c in candles],
            "volume": [{"time": c["time"], "value": c["vol"], "color": "rgba(16,185,129,0.35)" if c["close"] >= c["open"] else "rgba(239,68,68,0.35)"} for c in candles],
            "heatmap": heatmap, "ema20": [{"time": candles[i]["time"], "value": ema20[i]} for i in range(n)],
            "ema50": [{"time": candles[i]["time"], "value": ema50[i]} for i in range(n)],
            "bb_upper": [{"time": candles[i]["time"], "value": bb_up[i]} for i in range(n)],
            "bb_lower": [{"time": candles[i]["time"], "value": bb_lo[i]} for i in range(n)],
            "rsi": rsi_pts, "macd": [{"time": candles[i]["time"], "value": macd_l[i]} for i in range(n)],
            "macd_signal": [{"time": candles[i]["time"], "value": sig_l[i]} for i in range(n)],
            "macd_hist": [{"time": candles[i]["time"], "value": hist_l[i], "color": "#10b981" if hist_l[i] >= 0 else "#ef4444"} for i in range(n)],
            "pa_markers": pa_markers, "pa_support": pa_sup, "pa_resistance": pa_res,
            "fib": fib, "rsi_now": rsi_now, "patterns": patterns, "divergences": divergences, "harmonics": harmonics,
        }
    }
