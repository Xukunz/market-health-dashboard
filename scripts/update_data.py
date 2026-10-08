#!/usr/bin/env python3
"""Daily, source-dated market snapshot. No API key and no invented prices."""
from __future__ import annotations

import csv
import io
import json
import logging
import math
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, time as clocktime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from statistics import mean, pstdev
from urllib.parse import quote, urlencode
from zoneinfo import ZoneInfo

import xml.etree.ElementTree as ETXML
import requests

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "site" / "data.json"
HISTORY = ROOT / "site" / "history.json"
ET = ZoneInfo("America/New_York")
NOW = datetime.now(timezone.utc)
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; MarketHealthDashboard/1.0; public market data)", "Accept": "application/json,text/csv,application/xml,*/*"}
SESSION = requests.Session()
SESSION.headers.update(HEADERS)
WATCHLIST = [
    ("AAPL", "Apple", "大型科技"), ("AMZN", "Amazon", "大型科技"),
    ("TSLA", "Tesla", "汽车 / 科技"), ("MSFT", "Microsoft", "大型科技"),
    ("META", "Meta", "大型科技"), ("NVDA", "NVIDIA", "AI / 芯片"),
    ("ARM", "Arm", "AI / 芯片"), ("AMD", "AMD", "AI / 芯片"),
    ("INTC", "Intel", "AI / 芯片"), ("1810.HK", "小米集团", "中概 / 港股"),
    ("GOOG", "Alphabet", "大型科技"), ("MU", "Micron", "存储芯片"),
    ("SNDK", "SanDisk", "存储芯片"), ("QCOM", "Qualcomm", "AI / 芯片"),
    ("T", "AT&T", "电信"), ("VZ", "Verizon", "电信"),
    ("TMUS", "T-Mobile", "电信"), ("TTWO", "Take-Two", "游戏"),
    ("ORCL", "Oracle", "云计算"), ("WDC", "Western Digital", "存储设备"),
    ("STX", "Seagate", "存储设备"), ("MRVL", "Marvell", "AI / 芯片"),
    ("AMAT", "Applied Materials", "半导体设备"), ("GEV", "GE Vernova", "能源 / 电力"),
    ("ASML", "ASML", "半导体设备"), ("LRCX", "Lam Research", "半导体设备"),
    ("KLAC", "KLA", "半导体设备"), ("BRK.B", "Berkshire B", "综合金融"),
    ("BRK.A", "Berkshire A", "综合金融"), ("BABA", "Alibaba", "中概 / 港股"),
    ("PDD", "PDD", "中概 / 港股"), ("BILI", "Bilibili", "中概 / 港股"),
    ("NTES", "NetEase", "中概 / 港股"), ("LI", "Li Auto", "中概 / 港股"),
    ("NIO", "NIO", "中概 / 港股"), ("0700.HK", "腾讯控股", "中概 / 港股"),
    ("SKHY", "SK hynix", "存储芯片"), ("AMC", "AMC", "高波动")
]
# Scoring sample is intentionally independent of a visitor's displayed watchlist.
# Keep it fixed for methodology 1.1 so scores remain comparable over time.
SCORE_STOCKS = (
    "AAPL", "AMZN", "TSLA", "MSFT", "META", "NVDA", "ARM", "AMD", "INTC",
    "GOOG", "MU", "SNDK", "QCOM", "T", "VZ", "TMUS", "TTWO", "ORCL", "WDC",
    "STX", "MRVL", "AMAT", "GEV", "ASML", "LRCX", "KLAC", "BRK.B", "BRK.A",
    "BABA", "PDD", "BILI", "NTES", "LI", "NIO", "SKHY", "AMC",
)
BENCHMARKS = [("SPY", "S&P 500 ETF"), ("QQQ", "Nasdaq 100 ETF"), ("SOXX", "半导体 ETF"), ("RSP", "等权标普 ETF"), ("IWM", "小盘股 ETF"), ("HYG", "高收益债 ETF"), ("TLT", "长期美债 ETF")]
SECTORS = ["XLC", "XLY", "XLP", "XLE", "XLF", "XLV", "XLI", "XLB", "XLK", "XLU", "XLRE"]
CHIPS = ["NVDA", "ARM", "AMD", "INTC", "MU", "SNDK", "QCOM", "MRVL", "AMAT", "ASML", "LRCX", "KLAC", "SKHY", "WDC", "STX"]
FRED = {"treasury_10y": ("DGS10", "美国10年期国债收益率", "%"), "treasury_30y": ("DGS30", "美国30年期国债收益率", "%"), "vix": ("VIXCLS", "VIX波动率指数", ""), "brent": ("DCOILBRENTEU", "Brent现货原油", "USD/桶"), "high_yield_spread": ("BAMLH0A0HYM2", "美国高收益债信用利差", "%")}
# FRED 会屏蔽部分数据中心/CI 出口 IP（GitHub Actions 上表现为读超时）。
# 这些序列用 Yahoo Finance 的同类日线标的兜底，页面会显示真实来源；没有同类标的的序列仍留空。
YAHOO_MACRO = {"treasury_10y": ("^TNX", "10Y 美债收益率（^TNX）"),
               "treasury_30y": ("^TYX", "30Y 美债收益率（^TYX）"),
               "vix": ("^VIX", "VIX 波动率（^VIX）"),
               "brent": ("BZ=F", "Brent 原油期货（BZ=F 近月）")}
NEWS_QUERIES = [
    ("科技", 'Nvidia OR Microsoft OR Google OR Apple OR Amazon stocks'),
    ("半导体", 'semiconductor OR SK hynix OR Micron OR AMD OR ASML earnings'),
    ("宏观", 'US treasury yields OR inflation OR Federal Reserve OR oil prices markets'),
    ("中概", 'Alibaba OR Tencent OR Xiaomi OR PDD OR Chinese ADR stocks'),
    ("监管", 'technology antitrust OR semiconductor export controls OR chip sanctions'),
]
MATERIAL = re.compile(r"earnings|forecast|guidance|profit warning|revenue|sec\b|doj\b|investigat|lawsuit|sue |court|regulat|sanction|export ban|acquisition|merger|takeover|buyout|billion|downgrad|upgrad|rate cut|fed |tariff|layoff|record high|record low", re.I)
LOG = logging.getLogger("market-update")


def get(url: str, *, timeout: int = 18):
    last = None
    for retry in range(3):
        try:
            r = SESSION.get(url, timeout=timeout)
            r.raise_for_status()
            return r
        except requests.RequestException as exc:
            last = exc
            if retry < 2:
                time.sleep(0.7 * (retry + 1))
    raise last


def safe_float(n):
    try:
        x = float(n)
        return x if math.isfinite(x) else None
    except (ValueError, TypeError):
        return None


def rounded(value, places=2):
    n = safe_float(value)
    return round(n, places) if n is not None else None


def sma(series, n):
    return mean(series[-n:]) if len(series) >= n else None


def pct(a, b):
    return round((a / b - 1) * 100, 2) if a is not None and b is not None and b else None


def age_in_market_days(date_string):
    try:
        return (NOW.astimezone(ET).date() - date.fromisoformat(date_string)).days
    except (TypeError, ValueError):
        return 999


def accept_market_snapshot(item):
    # 7 calendar days allows weekends/extended exchange holidays, not months-old cache.
    return item is not None and -1 <= age_in_market_days(item.get("date")) <= 7


def yahoo_symbol(symbol):
    return {"BRK.B": "BRK-B", "BRK.A": "BRK-A"}.get(symbol, symbol)


def yahoo_daily(symbol: str):
    """Daily candles, Yahoo's unofficial public endpoint. Do not infer intraday ticks."""
    yf = yahoo_symbol(symbol)
    endpoint = f"/v8/finance/chart/{quote(yf)}?" + urlencode({"range": "1y", "interval": "1d"})
    try:
        body = get("https://query1.finance.yahoo.com" + endpoint).json()
    except (requests.RequestException, ValueError):
        body = get("https://query2.finance.yahoo.com" + endpoint).json()
    chart = (body.get("chart") or {}).get("result")
    if not chart:
        raise ValueError(f"Yahoo unavailable for {symbol}: {(body.get('chart') or {}).get('error')}")
    result = chart[0]
    times = result.get("timestamp") or []
    quote_data = ((result.get("indicators") or {}).get("quote") or [{}])[0]
    valid = []
    exchange_zone = (result.get("meta") or {}).get("exchangeTimezoneName")
    try:
        market_zone = ZoneInfo(exchange_zone) if exchange_zone else (ZoneInfo("Asia/Hong_Kong") if symbol.endswith(".HK") else ET)
    except (KeyError, ValueError):
        market_zone = ZoneInfo("Asia/Hong_Kong") if symbol.endswith(".HK") else ET
    for t, c, v, h, l in zip(times, quote_data.get("close") or [], quote_data.get("volume") or [], quote_data.get("high") or [], quote_data.get("low") or []):
        c = safe_float(c)
        if c is None or c <= 0:
            continue
        valid.append({"ts": t, "date": datetime.fromtimestamp(t, market_zone).date().isoformat(), "close": c, "volume": v or 0, "high": safe_float(h), "low": safe_float(l)})
    if len(valid) < 2:
        raise ValueError(f"Insufficient daily prices: {symbol}")
    return summarize_candles(symbol, keep_completed_bars(symbol, valid), "Yahoo Finance (unofficial chart)")


def keep_completed_bars(symbol, bars):
    """When a workflow is started intraday, do not present partial bars as a close."""
    market_tz = ZoneInfo("Asia/Hong_Kong") if symbol.endswith(".HK") else ET
    cutoff = clocktime(16, 20) if symbol.endswith(".HK") else clocktime(16, 15)
    now_local = NOW.astimezone(market_tz)
    if bars and bars[-1]["date"] == now_local.date().isoformat() and now_local.time() < cutoff:
        return bars[:-1]
    return bars


def summarize_candles(symbol, bars, source):
    if len(bars) < 2:
        raise ValueError("Fewer than two completed daily candles")
    prices = [b["close"] for b in bars]
    last = bars[-1]
    av = mean([b["volume"] for b in bars[-21:-1] if b["volume"] > 0]) if any(b["volume"] > 0 for b in bars[-21:-1]) else None
    val = {
        "symbol": symbol, "price": rounded(last["close"], 4 if last["close"] < 1 else 2),
        "currency": "HKD" if symbol.endswith(".HK") else "USD",
        "date": last["date"], "data_timestamp": datetime.fromtimestamp(last["ts"], timezone.utc).isoformat(),
        "source": source, "change_1d": pct(last["close"], prices[-2]),
        "change_5d": pct(last["close"], prices[-6]) if len(prices) >= 6 else None,
        "change_20d": pct(last["close"], prices[-21]) if len(prices) >= 21 else None,
        "volume": int(last["volume"]), "volume_multiple": rounded(last["volume"] / av, 2) if av else None,
        "sma20": rounded(sma(prices, 20)), "sma50": rounded(sma(prices, 50)), "sma200": rounded(sma(prices, 200)),
        "low20": rounded(min(p["low"] for p in bars[-20:] if p["low"] is not None)) if any(p["low"] is not None for p in bars[-20:]) else None,
        "high20": rounded(max(p["high"] for p in bars[-20:] if p["high"] is not None)) if any(p["high"] is not None for p in bars[-20:]) else None,
        "sparkline": [rounded(p, 3) for p in prices[-25:]],
        "volatility20": rounded(pstdev([100 * (prices[i] / prices[i-1] - 1) for i in range(max(1, len(prices)-20), len(prices))]), 2) if len(prices) >= 21 else None,
    }
    return val


def stooq_daily(symbol):
    """Fallback for .US tickers. Stooq data may have different adjustments."""
    if symbol.endswith(".HK"):
        raise ValueError("Stooq fallback skipped for HK symbols")
    yf = yahoo_symbol(symbol).lower().replace("-", ".")
    start = (NOW - timedelta(days=390)).strftime("%Y%m%d")
    end = NOW.strftime("%Y%m%d")
    url = "https://stooq.com/q/d/l/?" + urlencode({"s": yf + ".us", "i": "d", "d1": start, "d2": end})
    resp = get(url)
    rows = []
    for row in csv.DictReader(io.StringIO(resp.text)):
        try:
            day = datetime.fromisoformat(row["Date"])
            close = float(row["Close"])
            rows.append({"ts": int(day.replace(tzinfo=ET).timestamp()), "date": day.date().isoformat(), "close": close, "volume": int(float(row.get("Volume", 0))), "low": safe_float(row.get("Low")), "high": safe_float(row.get("High"))})
        except (ValueError, TypeError, KeyError):
            continue
    if len(rows) < 2:
        raise ValueError("Stooq unavailable")
    return summarize_candles(symbol, keep_completed_bars(symbol, rows), "Stooq daily (fallback, adjusted data may differ)")


def quote_one(item):
    symbol = item[0]
    try:
        y = yahoo_daily(symbol)
        if accept_market_snapshot(y):
            return y
        LOG.warning("Stale Yahoo daily source: %s %s", symbol, y.get("date"))
    except Exception as e:
        LOG.warning("Yahoo %s: %s", symbol, str(e)[:160])
    try:
        y = stooq_daily(symbol)
        if accept_market_snapshot(y):
            return y
        LOG.warning("Stale Stooq daily source: %s %s", symbol, y.get("date"))
    except Exception as e:
        LOG.warning("Stooq %s: %s", symbol, str(e)[:160])
    return None


def fred_series(name, series_id, label, unit):
    url = "https://fred.stlouisfed.org/graph/fredgraph.csv?" + urlencode({"id": series_id, "cosd": (NOW - timedelta(days=50)).date().isoformat()})
    rows = []
    for row in csv.DictReader(io.StringIO(get(url).text)):
        d = row.get("DATE") or row.get("observation_date")
        value = safe_float(row.get(series_id))
        if d and value is not None:
            rows.append((d, value))
    if not rows:
        raise ValueError("No valid FRED observations")
    current_day, value = rows[-1]
    prior5 = rows[-6][1] if len(rows) >= 6 else None
    return {"key": name, "name": label, "unit": unit, "value": rounded(value, 3), "date": current_day,
            "change_5obs": rounded(value - prior5, 3) if prior5 is not None else None,
            "change_5obs_pct": pct(value, prior5), "source": f"FRED · {series_id}",
            "url": f"https://fred.stlouisfed.org/series/{series_id}"}


def yahoo_macro(key, symbol, label, unit):
    """兜底宏观序列：取 Yahoo 同类日线收盘，来源与 URL 会如实标注，不冒充 FRED 观测值。"""
    daily = yahoo_daily(symbol)
    spark = daily.get("sparkline") or []
    price = daily["price"]
    prior5 = spark[-6] if len(spark) >= 6 else None
    return {"key": key, "name": label, "unit": unit, "value": rounded(price, 3), "date": daily["date"],
            "change_5obs": rounded(price - prior5, 3) if prior5 is not None else None,
            "change_5obs_pct": daily.get("change_5d"),
            "source": f"Yahoo Finance · {symbol}（FRED 不可用时的兜底）",
            "url": f"https://finance.yahoo.com/quote/{quote(symbol)}"}


def yahoo_macro_fallback(key, label, unit):
    target = YAHOO_MACRO.get(key)
    if not target:
        return None
    try:
        return yahoo_macro(key, *target, unit)
    except Exception as e:
        LOG.warning("Yahoo macro fallback %s: %s", key, str(e)[:150])
        return None


def load_fred():
    output = {}
    for key, (series_id, label, unit) in FRED.items():
        observation = None
        try:
            observation = fred_series(key, series_id, label, unit)
        except Exception as e:
            LOG.warning("FRED %s: %s", series_id, str(e)[:150])
            observation = yahoo_macro_fallback(key, label, unit)
        if observation is None:
            continue
        if age_in_market_days(observation["date"]) > 12:
            LOG.warning("Ignoring stale macro %s observation %s", series_id, observation["date"])
        else:
            output[key] = observation
    return output


def band_score(value, breaks):
    for maximum, score in breaks:
        if value <= maximum:
            return score
    return breaks[-1][1]


def observation_near_date(observation, reference_date, max_lag_days=5):
    if not observation:
        return False
    if not reference_date:
        return True
    try:
        lag = (date.fromisoformat(reference_date) - date.fromisoformat(observation["date"])).days
    except (KeyError, TypeError, ValueError):
        return False
    return 0 <= lag <= max_lag_days


def build_health(stocks, indices, macro):
    spy = indices.get("SPY")
    reference_date = spy.get("date") if spy else None
    def same_session(item):
        return reference_date is None or item.get("date") == reference_date
    sectors = [indices[s] for s in SECTORS if s in indices and indices[s].get("sma50") and same_session(indices[s])]
    watch = [stocks[s] for s in SCORE_STOCKS if s in stocks and stocks[s].get("sma50") and stocks[s].get("currency") == "USD" and same_session(stocks[s])]
    vix = macro.get("vix") if observation_near_date(macro.get("vix"), reference_date) else None
    ten = macro.get("treasury_10y") if observation_near_date(macro.get("treasury_10y"), reference_date) else None
    brent = macro.get("brent") if observation_near_date(macro.get("brent"), reference_date) else None
    spread = macro.get("high_yield_spread") if observation_near_date(macro.get("high_yield_spread"), reference_date) else None
    parts = []
    if spy and all(spy.get("sma"+str(n)) is not None for n in [20, 50, 200]):
        score = sum(weight for n, weight in [(20, 8), (50, 8), (200, 9)] if spy["price"] >= spy["sma"+str(n)])
        parts.append({"key":"trend", "name":"市场趋势", "score": score, "max": 25,
                      "reason": f"SPY高于20/50/200日均线：{sum(spy['price']>=spy['sma'+str(n)] for n in [20,50,200])}/3", "coverage": "SPY"})
    if len(sectors) >= 7 and len(watch) >= 15:
        p1 = sum(s["price"] >= s["sma50"] for s in sectors) / len(sectors)
        p2 = sum(s["price"] >= s["sma50"] for s in watch) / len(watch)
        score = round(12*p1 + 8*p2)
        parts.append({"key":"breadth", "name":"上涨广度", "score": score, "max": 20,
                      "reason": f"板块ETF站上50日线{round(100*p1)}% · 固定股票样本站上50日线{round(100*p2)}%", "coverage": f"{len(sectors)}个行业ETF + {len(watch)}只美股"})
    if vix:
        s = band_score(vix["value"], [(14,20),(18,16),(22,12),(28,8),(35,4),(float('inf'),0)])
        parts.append({"key":"volatility", "name":"波动环境", "score":s, "max":20,
                      "reason": f"VIX {vix['value']}（{vix['date']}）", "coverage": vix.get("source", "FRED VIXCLS")})
    if ten and brent and brent["change_5obs_pct"] is not None:
        s1 = band_score(ten["value"],[(3.5,10),(4.25,8),(5,5),(5.5,2),(float('inf'),0)])
        s2 = band_score(brent["change_5obs_pct"],[(-5,10),(2,8),(6,5),(12,2),(float('inf'),0)])
        parts.append({"key":"macro", "name":"利率与能源", "score":s1+s2, "max":20,
                      "reason": f"10Y {ten['value']}% · Brent近5个观测值变化 {brent['change_5obs_pct']:+.1f}%",
                      "coverage": f"{ten.get('source','FRED DGS10')} + {brent.get('source','FRED DCOILBRENTEU')}"})
    if spread:
        s = band_score(spread["value"], [(3,15),(4,12),(5,8),(6.5,4),(float('inf'),0)])
        parts.append({"key":"credit", "name":"信用压力", "score":s, "max":15,
                      "reason": f"美国高收益债OAS {spread['value']}%", "coverage": spread.get("source", "FRED BAMLH0A0HYM2")})
    base = sum(p["max"] for p in parts)
    scored_macro = [item for item in (vix, spread) if item]
    if ten and brent and brent["change_5obs_pct"] is not None:
        scored_macro.extend((ten, brent))
    macro_proxy_count = sum(item.get("source", "").startswith("Yahoo Finance") for item in scored_macro)
    result = {"score": round(100*sum(p["score"] for p in parts)/base) if base >= 60 and reference_date else None,
              "observed_points": sum(p["score"] for p in parts), "coverage":base,
              "label":"观察池风险评分", "components":parts,
              "data_quality":{"reference_date":reference_date, "sector_count":len(sectors),
                              "sector_target":len(SECTORS), "stock_count":len(watch),
                              "stock_target":len(SCORE_STOCKS), "macro_proxy_count":macro_proxy_count},
              "disclaimer":"规则化风险状态指标，不是官方指数；缺失分项时按已获数据归一化，覆盖率低于60%或缺少SPY基准交易日则不出分。上涨广度使用固定行业ETF和股票样本，不代表全市场涨跌家数；用户自选列表不参与评分。"}
    return result


def build_semi_health(stocks, indices):
    soxx, spy = indices.get("SOXX"), indices.get("SPY")
    reference_date = soxx.get("date") if soxx else None
    chips = [stocks[s] for s in CHIPS if s in stocks and stocks[s].get("sma50")
             and (reference_date is None or stocks[s].get("date") == reference_date)]
    if not soxx or not spy or len(chips) < 6 or not soxx.get("sma200"):
        return {"score":None,"coverage":0,"reason":"缺少SOXX、SPY或半导体样本数据"}
    trend = sum(weight for n, weight in [(20,12),(50,13),(200,15)] if soxx["price"] >= soxx["sma"+str(n)])
    rel = None
    if (soxx["change_5d"] is not None and spy["change_5d"] is not None
            and (reference_date is None or spy.get("date") == reference_date)):
        diff = soxx["change_5d"] - spy["change_5d"]
        rel = band_score(-diff, [(-3,20),(0,15),(3,9),(7,4),(float('inf'),0)])
    breadth = round(25*sum(s["price"]>=s["sma50"] for s in chips)/len(chips))
    drawdown = pct(soxx["price"], soxx["high20"])
    resilience = band_score(-drawdown, [(2,15),(5,11),(9,6),(14,2),(float('inf'),0)]) if drawdown is not None else None
    blocks = [{"name":"趋势", "score":trend, "max":40}, {"name":"样本广度", "score":breadth, "max":25}]
    if rel is not None:blocks.append({"name":"相对大盘强弱", "score":rel, "max":20})
    if resilience is not None:blocks.append({"name":"距20日高点", "score":resilience, "max":15})
    total = sum(b["max"] for b in blocks)
    return {"score":round(100*sum(b["score"] for b in blocks)/total), "coverage":total,
            "chip_count":len(chips),"blocks":blocks,"reason":"SOXX技术趋势、相对SPY的5日表现、半导体样本广度及短期回撤（规则评分）"}


def fetch_news():
    cutoff = NOW - timedelta(days=5)
    all_items = []
    seen = set()
    for category, terms in NEWS_QUERIES:
        url = "https://news.google.com/rss/search?" + urlencode({"q": terms + " when:3d", "hl":"en-US", "gl":"US", "ceid":"US:en"})
        try:
            root = ETXML.fromstring(get(url, timeout=12).content)
            for entry in root.findall("./channel/item")[:10]:
                title = re.sub(r"\s+", " ", entry.findtext("title") or "").strip()
                link = entry.findtext("link") or ""
                if not title or not link:
                    continue
                try:
                    published = parsedate_to_datetime(entry.findtext("pubDate") or "").astimezone(timezone.utc)
                except (ValueError, TypeError, IndexError, OverflowError):
                    continue
                if published < cutoff or published > NOW + timedelta(hours=2):
                    continue
                key = re.sub(r"\W+", "", title.lower())[:110]
                if key in seen:continue
                seen.add(key)
                publisher = title.rsplit(" - ", 1)[-1] if " - " in title else "Google News RSS"
                all_items.append({"title":title,"url":link,"published_at":published.isoformat(),
                                  "publisher":publisher,"category":category,
                                  "potentially_material":bool(MATERIAL.search(title)),
                                  "verified":False,
                                  "note":"RSS新闻标题，事件重要性由关键词粗筛；未经独立核实"})
        except Exception as exc:
            LOG.warning("News %s unavailable: %s", category, str(exc)[:150])
    all_items.sort(key=lambda x: (x["potentially_material"], x["published_at"]),reverse=True)
    return all_items[:35]


def alert_for(s):
    warnings = []
    d1 = s.get("change_1d")
    d5 = s.get("change_5d")
    vol = s.get("volume_multiple")
    if d1 is not None and abs(d1) >= 5:
        warnings.append(f"单日{'上涨' if d1>0 else '下跌'}{abs(d1):.1f}%")
    if vol is not None and vol >= 2 and s.get("volume",0)>0:
        warnings.append(f"量比约{vol:.1f}×（相对前20交易日完整日成交量）")
    if d5 is not None and abs(d5) >= 10:
        warnings.append(f"5交易日{'上涨' if d5>0 else '下跌'}{abs(d5):.1f}%")
    return warnings


def update_history(health, semi):
    previous = []
    if HISTORY.exists():
        try:
            previous = json.loads(HISTORY.read_text(encoding="utf-8")).get("points",[])
        except (ValueError, OSError):
            pass
    today = NOW.astimezone(ET).date().isoformat()
    record = {"date":today,"market":health.get("score"),"semiconductors":semi.get("score"), "coverage":health.get("coverage",0), "methodology_version":"1.1"}
    previous = [v for v in previous if v.get("date") != today]
    if health.get("score") is not None or semi.get("score") is not None:
        previous.append(record)
    previous.sort(key=lambda x:x.get("date", ""))
    HISTORY.write_text(json.dumps({"points":previous[-120:]},ensure_ascii=False,indent=2)+"\n",encoding="utf-8")


def quote_universe(display_watchlist):
    return list(dict.fromkeys(
        [symbol for symbol, _, _ in display_watchlist]
        + list(SCORE_STOCKS) + CHIPS
        + [symbol for symbol, _ in BENCHMARKS] + SECTORS
    ))


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    LOG.info("Starting daily snapshot %s", NOW.isoformat())
    mapping = {symbol:{"symbol":symbol,"name":name,"category":category} for symbol,name,category in WATCHLIST}
    universe = quote_universe(WATCHLIST)
    quotes = {}
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {pool.submit(quote_one,(s,)):s for s in universe}
        for f in as_completed(futures):
            sym = futures[f]
            try:
                q = f.result()
                if q:quotes[sym]=q
            except Exception as exc:
                LOG.warning("Quote %s failed: %s",sym,exc)
    stocks = {}
    for sym, meta in mapping.items():
        q = quotes.get(sym)
        if q:
            q.update(meta)
            q["alerts"] = alert_for(q)
            stocks[sym] = q
    indices = {k:quotes[k] for k in [x[0] for x in BENCHMARKS]+SECTORS if k in quotes}
    macro = load_fred()
    score_stocks = {symbol:quotes[symbol] for symbol in set(SCORE_STOCKS) | set(CHIPS) if symbol in quotes}
    health = build_health(score_stocks, indices, macro)
    semi = build_semi_health(score_stocks, indices)
    news = fetch_news()
    age = sorted({s["date"] for s in stocks.values()},reverse=True)
    data = {"meta":{"status":"ready" if stocks else "unavailable", "generated_at":NOW.isoformat(),
                    "generated_et":NOW.astimezone(ET).isoformat(),
                    "market_data_dates":age,"market_data_source":"Yahoo Finance unofficial daily historical chart; Stooq fallback",
                    "macro_source":"Federal Reserve FRED public CSV（限流时回退 Yahoo Finance 同类标的，页面标注实际来源）", "news_source":"Google News RSS (unverified headlines)",
                    "refresh":"每日北京时间/美东时间晚间，通过GitHub Actions计划运行；不提供实时逐笔行情",
                    "quote_count":len(stocks),"watchlist_size":len(WATCHLIST),
                    "errors":"部分数据源可能限流，缺失则留空，不会使用旧截图填充。"},
            "health":health,"semiconductors":semi,
            "benchmarks":[{**quotes[k],"name":name} for k,name in BENCHMARKS if k in quotes],
            "stocks":[stocks[s] for s in mapping if s in stocks],
            "missing_stocks":[sym for sym in mapping if sym not in stocks],
            "macro":list(macro.values()),"news":news,
            "notices":[{"symbol":s["symbol"],"name":s["name"],"price_date":s["date"],"alerts":s["alerts"],
                        "change_1d":s["change_1d"],"price":s["price"],"currency":s["currency"]}
                       for s in stocks.values() if s["alerts"]],
            "methodology_version":"1.1"}
    data["notices"].sort(key=lambda x:max([abs(x.get("change_1d") or 0)]+[0]),reverse=True)
    # Safeguard: do not overwrite a published market dashboard with a nearly empty source outage.
    if len(score_stocks) < 18 or "SPY" not in indices or "SOXX" not in indices:
        sys.exit(f"Insufficient scoring quote coverage ({len(score_stocks)}/{len(SCORE_STOCKS)}, SPY={'SPY' in indices}, SOXX={'SOXX' in indices}); retained previous published snapshot")
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2)+"\n",encoding="utf-8")
    update_history(health, semi)
    LOG.info("Wrote %s: %d/%d stocks, %d macros, %d news, health=%s/%s coverage=%s",OUT,len(stocks),len(WATCHLIST),len(macro),len(news),health["score"],semi["score"],health["coverage"])


if __name__ == "__main__":
    main()
