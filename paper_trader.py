"""
Paper Trading Engine v1
Runs as a background thread inside the Flask server.
Scans symbols every 5 minutes, detects VP setups, logs paper trades.
No real money involved — simulation only.
"""
import json, time, threading, os
from datetime import datetime, timezone
from pathlib import Path

PAPER_FILE    = Path("paper_trades.json")
SCAN_INTERVAL = 300   # 5 minutes
MAX_OPEN      = 3     # max simultaneous open paper trades

# Symbols to scan — reduce if hitting API rate limits
SCAN_SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT",          # Crypto
    "NIFTY50", "BANKNIFTY",                    # Indian indices
    "RELIANCE", "TCS", "HDFCBANK",             # Indian stocks
]


def _load() -> dict:
    try:
        return json.loads(PAPER_FILE.read_text())
    except Exception:
        return {"trades": [], "stats": {}, "last_scan": None}


def _save(data: dict):
    PAPER_FILE.write_text(json.dumps(data, indent=2))


def _compute_stats(trades: list) -> dict:
    completed = [t for t in trades if t["status"] != "open"]
    wins      = [t for t in completed if t["result"] == "win"]
    losses    = [t for t in completed if t["result"] == "loss"]
    n         = len(completed)
    equity    = 100.0
    for t in sorted(completed, key=lambda x: x["opened_at"]):
        equity += equity * ((t["pnl"] or 0) / 100)
    return {
        "total_trades": len(trades),
        "open":         len([t for t in trades if t["status"] == "open"]),
        "completed":    n,
        "wins":         len(wins),
        "losses":       len(losses),
        "win_rate":     round(len(wins) / n * 100, 1) if n else 0,
        "net_pnl":      round(equity - 100, 2),
        "equity":       round(equity, 2),
    }


def scan_once():
    """One scan cycle — detect new setups + check existing open trades."""
    try:
        from vp_engine import (fetch_candles, fetch_price, compute_vp,
                               detect_setup, compute_trade_params, SYMBOL_REGISTRY)
    except ImportError as e:
        print(f"[Paper] Import error: {e}")
        return

    data   = _load()
    trades = data.get("trades", [])
    now    = datetime.now(timezone.utc).isoformat()
    open_trades = [t for t in trades if t["status"] == "open"]

    # ── CHECK EXISTING OPEN TRADES ────────────────────────────────────
    for t in open_trades:
        try:
            sym = t["symbol"]
            c   = fetch_candles(symbol=sym, interval="1h", limit=2)
            if not c:
                continue
            last = c[-1]
            bias = t["bias"]

            if bias == "bullish":
                if t["stop"] and last["low"] <= t["stop"]:
                    t.update(status="closed", result="loss",
                             pnl=-1.0, closed_at=now,
                             note="Stop hit")
                    print(f"[Paper] ✗ STOP HIT  {sym} {t['setup']}")
                elif t["target_1"] and last["high"] >= t["target_1"]:
                    rr = t.get("r_ratio") or 1.5
                    t.update(status="closed", result="win",
                             pnl=round(rr * 1.0, 2), closed_at=now,
                             note="T1 hit")
                    print(f"[Paper] ✓ TARGET HIT {sym} {t['setup']} +{t['pnl']}%")
            else:  # bearish
                if t["stop"] and last["high"] >= t["stop"]:
                    t.update(status="closed", result="loss",
                             pnl=-1.0, closed_at=now,
                             note="Stop hit")
                    print(f"[Paper] ✗ STOP HIT  {sym} {t['setup']}")
                elif t["target_1"] and last["low"] <= t["target_1"]:
                    rr = t.get("r_ratio") or 1.5
                    t.update(status="closed", result="win",
                             pnl=round(rr * 1.0, 2), closed_at=now,
                             note="T1 hit")
                    print(f"[Paper] ✓ TARGET HIT {sym} {t['setup']} +{t['pnl']}%")
        except Exception as e:
            print(f"[Paper] Check error {t.get('symbol','?')}: {e}")

    # ── SCAN FOR NEW SETUPS ───────────────────────────────────────────
    open_syms = [t["symbol"] for t in trades if t["status"] == "open"]
    open_count = len(open_syms)

    if open_count < MAX_OPEN:
        for sym in SCAN_SYMBOLS:
            if sym in open_syms:
                continue
            if open_count >= MAX_OPEN:
                break
            try:
                tf = "1h"
                c  = fetch_candles(symbol=sym, interval=tf, limit=12)
                pc = fetch_candles(symbol=sym, interval=tf, limit=24)
                if not c:
                    continue
                price   = fetch_price(sym) or c[-1]["close"]
                curr_vp = compute_vp(c)
                prev_vp = compute_vp(pc[:12]) if pc else None
                if not curr_vp:
                    continue

                setup, bias, desc = detect_setup(curr_vp, prev_vp, price)
                if setup == "none":
                    continue

                tp = compute_trade_params(setup, bias, curr_vp)
                if not tp["entry"]:
                    continue

                info = SYMBOL_REGISTRY.get(sym, (sym, "binance", sym, "$"))
                trade = {
                    "id":        f"{sym}_{int(time.time())}",
                    "symbol":    sym,
                    "label":     info[2],
                    "currency":  info[3],
                    "setup":     setup,
                    "bias":      bias,
                    "description": desc,
                    "price_at_signal": round(price, 4),
                    "entry":     tp["entry"],
                    "stop":      tp["stop"],
                    "target_1":  tp["target_1"],
                    "target_2":  tp["target_2"],
                    "r_ratio":   tp["r_ratio"],
                    "vah":       curr_vp.vah,
                    "val":       curr_vp.val,
                    "poc":       curr_vp.poc,
                    "status":    "open",
                    "result":    None,
                    "pnl":       None,
                    "note":      None,
                    "opened_at": now,
                    "closed_at": None,
                }
                trades.append(trade)
                open_syms.append(sym)
                open_count += 1
                print(f"[Paper] ➤ NEW TRADE  {sym} | {setup.upper()} | {bias.upper()} "
                      f"| Entry={tp['entry']} Stop={tp['stop']} T1={tp['target_1']}")
            except Exception as e:
                print(f"[Paper] Scan error {sym}: {e}")

    data["trades"]    = trades[-500:]   # keep last 500 trades
    data["stats"]     = _compute_stats(trades)
    data["last_scan"] = now
    _save(data)


def get_paper_data() -> dict:
    return _load()


def _run_loop():
    print("[Paper Trader] 🟢 Started — scanning every 5 minutes")
    while True:
        try:
            scan_once()
        except Exception as e:
            print(f"[Paper Trader] Loop error: {e}")
        time.sleep(SCAN_INTERVAL)


def start_background():
    t = threading.Thread(target=_run_loop, daemon=True, name="paper-trader")
    t.start()
    return t
