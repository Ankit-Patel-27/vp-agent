"""
VP Agent Server v2 — with backtesting support
Run: python server.py
Open: http://localhost:5000
"""
from flask import Flask, jsonify, send_file, request
from datetime import datetime, timezone, timedelta
import time

from vp_engine import fetch_candles, fetch_price, compute_vp, detect_setup, compute_trade_params
from news_engine import fetch_headlines, fetch_fear_greed, compute_sentiment, confidence_modifier
from rag_store import RAGStore
from claude_agent import analyze
from paper_trader import start_background, get_paper_data

app = Flask(__name__)
rag = RAGStore()

try:
    from flask_cors import CORS; CORS(app)
except: pass

# ── Backtest cache ──
_bt_cache = {}   # symbol -> list of all candles fetched


def get_historical_candles(symbol: str, start_ms: int, end_ms: int, interval="5m") -> list:
    """Fetch historical candles from Binance for a specific time window."""
    import requests as req
    all_candles = []
    current = start_ms
    while current < end_ms:
        try:
            r = req.get(
                "https://api.binance.com/api/v3/klines",
                params={"symbol": symbol, "interval": interval,
                        "startTime": current, "endTime": end_ms, "limit": 500},
                timeout=15
            )
            r.raise_for_status()
            data = r.json()
            if not data: break
            candles = [{"open_time": c[0], "open": float(c[1]), "high": float(c[2]),
                        "low": float(c[3]), "close": float(c[4]), "volume": float(c[5])}
                       for c in data]
            all_candles.extend(candles)
            current = data[-1][0] + 1
            if len(data) < 500: break
            time.sleep(0.1)
        except Exception as e:
            print(f"[Backtest] fetch error: {e}")
            break
    return all_candles


@app.route("/")
def index():
    return send_file("dashboard.html")


@app.route("/api/analysis")
def api_analysis():
    """Live analysis — current market."""
    symbol = request.args.get("symbol", "BTCUSDT")
    candles      = fetch_candles(symbol=symbol, interval="5m", limit=12)
    prev_candles = fetch_candles(symbol=symbol, interval="5m", limit=24)
    price        = fetch_price(symbol=symbol)

    if not candles:
        return jsonify({"error": "Cannot reach Binance. Check internet."}), 500

    return _build_response(symbol, candles, prev_candles[:12] if prev_candles else [], price)


@app.route("/api/backtest/load")
def backtest_load():
    """
    Load historical candles for a date range.
    Returns list of hourly timestamps available.
    """
    symbol    = request.args.get("symbol", "BTCUSDT")
    date_str  = request.args.get("date", "")   # YYYY-MM-DD
    days      = int(request.args.get("days", 3))

    if not date_str:
        return jsonify({"error": "date parameter required"}), 400

    try:
        start_dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except:
        return jsonify({"error": "Invalid date format. Use YYYY-MM-DD"}), 400

    end_dt   = start_dt + timedelta(days=days)
    start_ms = int(start_dt.timestamp() * 1000)
    end_ms   = int(end_dt.timestamp() * 1000)
    now_ms   = int(datetime.now(timezone.utc).timestamp() * 1000)
    end_ms   = min(end_ms, now_ms)

    print(f"[Backtest] Loading {symbol} from {start_dt.date()} for {days} days...")
    candles = get_historical_candles(symbol, start_ms, end_ms)

    if not candles:
        return jsonify({"error": "No candle data found for this date range"}), 404

    # Group into hourly windows (each = 12 x 5m candles)
    windows = []
    for i in range(12, len(candles)):
        window_candles = candles[i-12:i]
        ts = window_candles[-1]["open_time"]
        dt = datetime.fromtimestamp(ts/1000, tz=timezone.utc)
        windows.append({
            "index": i - 12,
            "timestamp": ts,
            "datetime": dt.strftime("%Y-%m-%d %H:%M UTC"),
            "close": window_candles[-1]["close"]
        })

    cache_key = f"{symbol}_{date_str}_{days}"
    _bt_cache[cache_key] = candles

    return jsonify({
        "cache_key": cache_key,
        "total_windows": len(windows),
        "windows": windows,
        "date_from": start_dt.strftime("%Y-%m-%d"),
        "date_to":   end_dt.strftime("%Y-%m-%d"),
    })


@app.route("/api/backtest/step")
def backtest_step():
    """
    Analyse a specific hourly window from cached backtest data.
    window_idx = which hour to analyse.
    """
    cache_key  = request.args.get("cache_key", "")
    window_idx = int(request.args.get("window_idx", 0))
    symbol     = request.args.get("symbol", "BTCUSDT")

    if cache_key not in _bt_cache:
        return jsonify({"error": "Cache expired. Please reload the date range."}), 404

    all_candles = _bt_cache[cache_key]
    start       = window_idx
    end         = window_idx + 12

    if end > len(all_candles):
        return jsonify({"error": "No more candles in this window"}), 400

    curr_candles = all_candles[start:end]
    prev_candles = all_candles[max(0, start-12):start] if start >= 12 else []
    price        = curr_candles[-1]["close"]

    # Build next few candles for "reveal" (what actually happened)
    future_candles = all_candles[end:end+6] if end+6 <= len(all_candles) else all_candles[end:]

    resp = _build_response(symbol, curr_candles, prev_candles, price, is_backtest=True)
    data = resp.get_json()
    data["future_candles"] = future_candles
    data["window_idx"]     = window_idx
    data["max_idx"]        = max(0, len(all_candles) - 12)
    data["backtest_dt"]    = datetime.fromtimestamp(
        curr_candles[-1]["open_time"]/1000, tz=timezone.utc
    ).strftime("%Y-%m-%d %H:%M UTC")
    return jsonify(data)


def _build_response(symbol, candles, prev_candles, price, is_backtest=False):
    curr_vp  = compute_vp(candles)
    prev_vp  = compute_vp(prev_candles) if prev_candles else None

    if not curr_vp:
        return jsonify({"error": "VP computation failed"}), 500

    setup_type, trade_bias, description = detect_setup(curr_vp, prev_vp, price or curr_vp.poc)
    curr_vp.setup_type = setup_type
    trade_params = compute_trade_params(setup_type, trade_bias, curr_vp)

    # News — skip for backtest (historical news not available)
    if not is_backtest:
        headlines = fetch_headlines()
        fg        = fetch_fear_greed()
    else:
        headlines = []
        fg        = {"value": 50, "label": "N/A (backtest)", "regime": "neutral",
                     "note": "News context not available for historical data"}

    sentiment = compute_sentiment(headlines, fg)
    news_ctx  = {"sentiment": sentiment, "fear_greed": fg, "headlines": headlines[:10]}
    conf_mod  = confidence_modifier(sentiment, fg, trade_bias)

    case = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "asset": symbol, "setup_type": setup_type, "trade_bias": trade_bias,
        "vp": {"vah": curr_vp.vah, "val": curr_vp.val, "poc": curr_vp.poc,
               "va_spread": curr_vp.va_spread, "close_vs_va": curr_vp.close_vs_va,
               "session_high": curr_vp.session_high, "session_low": curr_vp.session_low},
        "news": {"direction": sentiment["direction"], "score": sentiment["score"],
                 "fg_regime": fg["regime"]},
        "trade_params": trade_params,
        "outcome": {"result": "pending"}
    }

    similar  = rag.find_similar(case, n=3)
    rag_ctx  = rag.context_text(similar)
    case_id  = rag.store(case)

    analysis = analyze(
        vp={"vah": curr_vp.vah, "val": curr_vp.val, "poc": curr_vp.poc,
            "va_spread": curr_vp.va_spread, "close_vs_va": curr_vp.close_vs_va,
            "session_high": curr_vp.session_high, "session_low": curr_vp.session_low,
            "bias": curr_vp.bias},
        setup={"setup_type": setup_type, "trade_bias": trade_bias, "description": description},
        trade_params=trade_params,
        news=news_ctx, rag_ctx=rag_ctx, conf_mod=conf_mod
    )

    return jsonify({
        "candles": candles, "price": price,
        "vp": {"vah": curr_vp.vah, "val": curr_vp.val, "poc": curr_vp.poc,
               "va_spread": curr_vp.va_spread, "close_vs_va": curr_vp.close_vs_va,
               "session_high": curr_vp.session_high, "session_low": curr_vp.session_low,
               "bias": curr_vp.bias, "histogram": curr_vp.histogram},
        "setup": {"type": setup_type, "bias": trade_bias, "description": description},
        "trade_params": trade_params, "analysis": analysis,
        "news": news_ctx, "similar_cases": similar,
        "case_id": case_id, "stats": rag.stats(),
        "confidence_modifier": conf_mod,
        "is_backtest": is_backtest,
    })


@app.route("/api/outcome", methods=["POST"])
def log_outcome():
    d  = request.json
    ok = rag.log_outcome(d["case_id"], d["result"],
                         d["exit_price"], d["r_achieved"], d.get("notes",""))
    return jsonify({"success": ok, "stats": rag.stats()})


@app.route("/api/stats")
def stats():
    return jsonify(rag.stats())


@app.route("/api/paper")
def api_paper():
    """Return live paper trading data — open trades + completed + stats."""
    return jsonify(get_paper_data())


if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5000))
    print("\n" + "="*52)
    print("  VP AGENT v4  —  Live + Backtest Dashboard")
    print("="*52)
    print(f"  Running on port: {port}")
    print(f"  Dashboard : http://localhost:{port}")
    print(f"  Journal   : http://localhost:{port}/journal")
    print("="*52 + "\n")
    # Start 24/7 paper trader in background
    start_background()
    app.run(debug=False, port=port, host="0.0.0.0")
