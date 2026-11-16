import os, time
import xml.etree.ElementTree as ET
from urllib.parse import quote
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any
import httpx

TEHRAN_TZ = timezone(timedelta(hours=3, minutes=30))
CALENDAR_CACHE: Dict[str, Any] = {"ts": 0, "err_ts": 0, "events": [], "source": "NOT_LOADED", "has_high_24h": False}
NEWS_CACHE: Dict[str, Dict[str, Any]] = {}

def build_tsetmc_url(target_url: str, proxy_url: str = "") -> str:
    px = (proxy_url or os.getenv("TSETMC_PROXY_URL", "")).strip()
    if px:
        return f"{px}{quote(target_url, safe='')}" if ("?" in px or px.endswith("=")) else f"{px.rstrip('/')}/?url={quote(target_url, safe='')}"
    return target_url

async def fetch_economic_calendar() -> Dict[str, Any]:
    now = time.time()
    if CALENDAR_CACHE["events"] and (now - CALENDAR_CACHE["ts"] < 3600):
        return CALENDAR_CACHE
    if CALENDAR_CACHE["err_ts"] and (now - CALENDAR_CACHE["err_ts"] < 300):
        return CALENDAR_CACHE
    try:
        async with httpx.AsyncClient(timeout=4.5, headers={"User-Agent": "Mozilla/5.0"}) as c:
            r = await c.get("https://nfs.faireconomy.media/ff_calendar_thisweek.json")
            if r.status_code == 200 and isinstance(r.json(), list):
                events, high_24h, now_dt = [], False, datetime.now(TEHRAN_TZ)
                for ev in r.json():
                    imp = str(ev.get("impact") or "")
                    if imp not in ("High", "Medium"):
                        continue
                    dt_str = str(ev.get("date") or "")
                    upcoming, tehran_lbl = False, dt_str[:16]
                    try:
                        dt_obj = datetime.fromisoformat(dt_str).astimezone(TEHRAN_TZ)
                        tehran_lbl = dt_obj.strftime("%m/%d - %H:%M")
                        diff_h = (dt_obj - now_dt).total_seconds() / 3600.0
                        upcoming = diff_h >= -1.0
                        if imp == "High" and 0 <= diff_h <= 24.0 and str(ev.get("country") or "") == "USD":
                            high_24h = True
                    except Exception:
                        pass
                    events.append({
                        "title": ev.get("title"), "country": ev.get("country"),
                        "impact_level": imp, "impact_fa": "🔴 خیلی مهم" if imp == "High" else "🟡 متوسط",
                        "time_tehran": tehran_lbl, "upcoming": upcoming,
                        "forecast": ev.get("forecast") or "-", "previous": ev.get("previous") or "-"
                    })
                CALENDAR_CACHE.update({"ts": now, "events": events[:28], "source": "LIVE_FOREX_FACTORY", "has_high_24h": high_24h})
                return CALENDAR_CACHE
            CALENDAR_CACHE.update({"err_ts": now, "source": f"CAL_HTTP_{r.status_code}"})
    except Exception as e:
        CALENDAR_CACHE.update({"err_ts": now, "source": f"CAL_ERR:{type(e).__name__}"})
    return CALENDAR_CACHE

def parse_rss_items(xml_text: str, default_source: str = "News", limit: int = 6) -> List[Dict[str, str]]:
    items, root = [], ET.fromstring(xml_text)
    for node in root.findall(".//item")[:limit]:
        title = (node.findtext("title") or "").strip()
        link = (node.findtext("link") or "").strip()
        pub = (node.findtext("pubDate") or "").strip()
        src_el = node.find("source")
        src_name = (src_el.text.strip() if (src_el is not None and src_el.text) else default_source)
        t_lbl = pub[:16]
        try:
            t_lbl = parsedate_to_datetime(pub).astimezone(TEHRAN_TZ).strftime("%m/%d %H:%M")
        except Exception:
            pass
        if title and link.startswith("http"):
            items.append({"title": title, "url": link, "source": src_name, "time": t_lbl})
    return items

async def fetch_asset_news(symbol: str, market: str) -> Dict[str, Any]:
    ck, now = f"{market}:{symbol.upper()}", time.time()
    if ck in NEWS_CACHE and (now - NEWS_CACHE[ck]["ts"] < 600) and NEWS_CACHE[ck].get("items"):
        return NEWS_CACHE[ck]

    items, diag, src_lbl = [], [], "NO_NEWS"
    async with httpx.AsyncClient(timeout=4.5, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/131.0.0.0"}, follow_redirects=True) as c:
        if market == "CRYPTO":
            sym_u = symbol.upper()
            try:
                q_str = f"{sym_u} crypto" if sym_u not in ("USDT", "BTC") else "cryptocurrency bitcoin market"
                r = await c.get("https://news.google.com/rss/search", params={"q": q_str, "hl": "en-US", "gl": "US", "ceid": "US:en"})
                if r.status_code == 200:
                    items = parse_rss_items(r.text, "Google News")
                    if items: src_lbl = f"LIVE_GNEWS_CRYPTO ({sym_u})"
                else: diag.append(f"GN:{r.status_code}")
            except Exception as e: diag.append(f"GN:{type(e).__name__}")

            if not items:
                for url, name in [("https://cointelegraph.com/rss", "CoinTelegraph"), ("https://decrypt.co/feed", "Decrypt")]:
                    try:
                        r2 = await c.get(url)
                        if r2.status_code == 200:
                            items = parse_rss_items(r2.text, name)
                            if items:
                                src_lbl = f"LIVE_{name.upper()}_RSS"
                                break
                        else: diag.append(f"{name}:{r2.status_code}")
                    except Exception as e: diag.append(f"{name}:{type(e).__name__}")

            if not items:
                try:
                    r4 = await c.get("https://min-api.cryptocompare.com/data/v2/news/?lang=EN")
                    if r4.status_code == 200:
                        raw_d = r4.json().get("Data")
                        if isinstance(raw_d, list) and raw_d:
                            items = [{"title": str(x.get("title") or ""), "source": str((x.get("source_info") or {}).get("name") or x.get("source") or "CryptoCompare"),
                                      "url": str(x.get("url") or ""), "time": datetime.fromtimestamp(int(x.get("published_on", now)), tz=TEHRAN_TZ).strftime("%m/%d %H:%M")}
                                     for x in raw_d[:6] if x.get("title") and str(x.get("url") or "").startswith("http")]
                            if items: src_lbl = "LIVE_CRYPTOCOMPARE"
                        else: diag.append(f"CC_TYPE:{type(raw_d).__name__}")
                except Exception as e: diag.append(f"CC:{type(e).__name__}")
        else:
            try:
                r = await c.get("https://news.google.com/rss/search", params={"q": f"{symbol} بورس", "hl": "fa", "gl": "IR", "ceid": "IR:fa"})
                if r.status_code == 200:
                    items = parse_rss_items(r.text, "خبرگزاری اقتصادی")
                    src_lbl = "LIVE_GOOGLE_NEWS_FA" if items else "NO_RECENT_NEWS"
                else: diag.append(f"GFA:{r.status_code}")
            except Exception as e: diag.append(f"GFA:{type(e).__name__}")

    if not items and diag:
        src_lbl = " | ".join(diag)
    pos_kw = ("surge", "rally", "bull", "etf", "approval", "partnership", "record", "gain", "رشد", "سود", "افزایش", "مثبت", "صعود")
    neg_kw = ("hack", "crash", "sec", "ban", "drop", "lawsuit", "bankrupt", "plunge", "زیان", "ریزش", "تعلیق", "کاهش", "منفی")
    pc = sum(1 for it in items if any(w in (it.get("title") or "").lower() for w in pos_kw))
    nc = sum(1 for it in items if any(w in (it.get("title") or "").lower() for w in neg_kw))
    sent = "BULLISH" if pc > nc else ("BEARISH" if nc > pc else "NEUTRAL")
    res = {"ts": now, "source": src_lbl, "sentiment": sent, "items": items}
    if items:
        NEWS_CACHE[ck] = res
    return res
