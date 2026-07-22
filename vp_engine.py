"""
Volume Profile Engine
Computes VAH, VAL, POC from Binance OHLCV data.
ALL rules here are FIXED - never modified by RAG or news.
"""
import requests
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class VPLevels:
    vah: float
    val: float
    poc: float
    va_spread: float
    bias: str
    setup_type: str
    close_vs_va: str
    histogram: dict = field(default_factory=dict)
    candles: list = field(default_factory=list)
    session_high: float = 0
    session_low: float = 0


def fetch_candles(symbol="BTCUSDT", interval="5m", limit=12) -> list:
    """Fetch OHLCV from Binance public API. No API key needed."""
    try:
        r = requests.get(
            "https://api.binance.com/api/v3/klines",
            params={"symbol": symbol, "interval": interval, "limit": limit},
            timeout=10
        )
        r.raise_for_status()
        return [{"open_time": c[0], "open": float(c[1]), "high": float(c[2]),
                 "low": float(c[3]), "close": float(c[4]), "volume": float(c[5])}
                for c in r.json()]
    except Exception as e:
        print(f"[Binance] fetch error: {e}")
        return []


def fetch_price(symbol="BTCUSDT") -> Optional[float]:
    try:
        r = requests.get("https://api.binance.com/api/v3/ticker/price",
                         params={"symbol": symbol}, timeout=5)
        return float(r.json()["price"])
    except:
        return None


def compute_vp(candles: list, tick_size=10.0, va_pct=0.40) -> Optional[VPLevels]:
    """Build price-volume histogram, find POC, VAH, VAL."""
    if not candles:
        return None
    histogram = {}
    for c in candles:
        low_t  = round(c["low"]  / tick_size) * tick_size
        high_t = round(c["high"] / tick_size) * tick_size
        if high_t == low_t: high_t += tick_size
        n = max(1, int((high_t - low_t) / tick_size))
        vpx = c["volume"] / n
        p = low_t
        while p <= high_t + 0.01:
            k = round(p, 2)
            histogram[k] = histogram.get(k, 0) + vpx
            p += tick_size

    if not histogram: return None
    poc    = max(histogram, key=histogram.get)
    prices = sorted(histogram.keys())
    poc_i  = prices.index(poc)
    target = sum(histogram.values()) * va_pct
    acc    = histogram[poc]
    ui, li = poc_i, poc_i

    while acc < target:
        cu = ui < len(prices) - 1
        cd = li > 0
        if cu and cd:
            vu = histogram.get(prices[ui+1], 0)
            vd = histogram.get(prices[li-1], 0)
            if vu >= vd: ui += 1; acc += vu
            else:        li -= 1; acc += vd
        elif cu: ui += 1; acc += histogram.get(prices[ui], 0)
        elif cd: li -= 1; acc += histogram.get(prices[li], 0)
        else: break

    vah, val   = prices[ui], prices[li]
    last_close = candles[-1]["close"]
    s_high     = max(c["high"] for c in candles)
    s_low      = min(c["low"]  for c in candles)

    if   last_close > vah: cva, bias = "above", "bullish"
    elif last_close < val: cva, bias = "below", "bearish"
    else:                  cva, bias = "inside", "neutral"

    return VPLevels(vah=vah, val=val, poc=poc,
                    va_spread=round(vah-val, 2),
                    bias=bias, setup_type="none",
                    close_vs_va=cva, histogram=histogram,
                    candles=candles, session_high=s_high, session_low=s_low)


def detect_setup(curr: VPLevels, prev: Optional[VPLevels], price: float) -> tuple:
    """
    Detect VP setup type. FIXED rules - never changed by RAG or news.
    Returns (setup_type, trade_bias, description)
    """
    if not prev:
        return "none", curr.bias, f"Bias: {curr.bias} | Close {curr.close_vs_va} VA"

    sp = curr.va_spread

    # Top-heavy: spiked above VAH but closed inside
    if curr.session_high > curr.vah + sp*0.25 and curr.close_vs_va == "inside":
        return ("top_heavy", "bearish",
                f"Spike to {curr.session_high:.0f} above VAH but closed inside VA — exhaustion")

    # Bottom-heavy: spiked below VAL but closed inside
    if curr.session_low < curr.val - sp*0.25 and curr.close_vs_va == "inside":
        return ("bottom_heavy", "bullish",
                f"Spike to {curr.session_low:.0f} below VAL but snapped back — failed breakdown")

    # Retracement: prev directional, price in prev VA
    buf = (prev.vah - prev.val) * 0.15
    in_prev = prev.val - buf <= price <= prev.vah + buf

    if prev.close_vs_va == "above" and in_prev:
        return ("retracement", "bullish",
                f"Retraced into prev bullish VA ({prev.val:.0f}–{prev.vah:.0f})")

    if prev.close_vs_va == "below" and in_prev:
        return ("retracement", "bearish",
                f"Retested prev bearish VA ({prev.val:.0f}–{prev.vah:.0f})")

    # Rollover
    if prev.close_vs_va == "above" and curr.close_vs_va == "inside" and price < curr.poc:
        return "rollover", "bearish", "Value at highs, rolling under POC — bearish"

    if prev.close_vs_va == "below" and curr.close_vs_va == "inside" and price > curr.poc:
        return "rollover", "bullish", "Value at lows, rolling above POC — bullish"

    return "none", curr.bias, f"Bias: {curr.bias} | Close {curr.close_vs_va} VA"


def compute_trade_params(setup: str, bias: str, vp: VPLevels) -> dict:
    """Compute entry/stop/target. FIXED rules."""
    sp = vp.va_spread
    r  = {"entry": None, "stop": None, "target_1": None, "target_2": None, "r_ratio": None}

    if   setup == "retracement" and bias == "bullish":
        r["entry"] = round(vp.vah, 0);         r["stop"] = round(vp.val - sp*0.1, 0)
        r["target_1"] = round(vp.vah + sp*1.2, 0); r["target_2"] = round(vp.vah + sp*2.5, 0)
    elif setup == "retracement" and bias == "bearish":
        r["entry"] = round(vp.val, 0);          r["stop"] = round(vp.vah + sp*0.1, 0)
        r["target_1"] = round(vp.val - sp*1.2, 0); r["target_2"] = round(vp.val - sp*2.5, 0)
    elif setup == "rollover" and bias == "bullish":
        r["entry"] = round(vp.poc + sp*0.05, 0); r["stop"] = round(vp.val - sp*0.15, 0)
        r["target_1"] = round(vp.vah, 0);         r["target_2"] = round(vp.vah + sp, 0)
    elif setup == "rollover" and bias == "bearish":
        r["entry"] = round(vp.poc - sp*0.05, 0); r["stop"] = round(vp.vah + sp*0.15, 0)
        r["target_1"] = round(vp.val, 0);         r["target_2"] = round(vp.val - sp, 0)
    elif setup == "top_heavy":
        r["entry"] = round(vp.poc, 0);            r["stop"] = round(vp.session_high + sp*0.1, 0)
        r["target_1"] = round(vp.val, 0);         r["target_2"] = round(vp.val - sp*0.8, 0)
    elif setup == "bottom_heavy":
        r["entry"] = round(vp.poc, 0);            r["stop"] = round(vp.session_low - sp*0.1, 0)
        r["target_1"] = round(vp.vah, 0);         r["target_2"] = round(vp.vah + sp*0.8, 0)

    if r["entry"] and r["stop"] and r["target_1"]:
        risk   = abs(r["entry"] - r["stop"])
        reward = abs(r["target_1"] - r["entry"])
        r["r_ratio"] = round(reward/risk, 1) if risk > 0 else None
    return r
