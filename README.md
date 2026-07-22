# VP Agent v4 — Volume Profile AI Trading Dashboard

A complete AI-powered trading analysis system using Volume Profile strategy.
Supports crypto (Binance) and Indian markets (NSE/BSE via Yahoo Finance).

---

## Quick Start

### Mac / Linux
```bash
chmod +x start.sh
./start.sh                          # No AI (rule-based reasoning)
./start.sh gsk_YOUR_GROQ_KEY        # With Groq AI (recommended — free)
./start.sh sk-ant-YOUR_CLAUDE_KEY   # With Claude AI
./start.sh AIzaSy_YOUR_GEMINI_KEY   # With Gemini AI
```

### Windows
```
start.bat
start.bat gsk_YOUR_GROQ_KEY
```

### Open in browser
- **Dashboard** → http://localhost:5000
- **Trade Journal** → http://localhost:5000/journal

---

## Getting a Free AI Key (optional but recommended)

| Provider | Free Tier | Where to get |
|----------|-----------|--------------|
| **Groq** (recommended) | 14,400 req/day free | https://console.groq.com |
| **Gemini** | 1,500 req/day free | https://aistudio.google.com |
| **Claude** | Paid only | https://console.anthropic.com |

Without a key the system still works — it uses rule-based reasoning instead.

---

## Supported Symbols

### Crypto (Binance — real-time)
`BTCUSDT` `ETHUSDT` `SOLUSDT` `BNBUSDT` `XRPUSDT` `ADAUSDT`

### Indian Indices (Yahoo Finance — 15-min delay)
`NIFTY50` `BANKNIFTY` `SENSEX` `NIFTYIT`

### Indian Stocks (Yahoo Finance — 15-min delay)
`RELIANCE` `TCS` `INFY` `HDFCBANK` `ICICIBANK` `WIPRO`
`TATAMOTORS` `AXISBANK` `SBIN` `BAJFINANCE`

---

## Dashboard Modes

### LIVE
Real-time analysis updated every 30 seconds.
- Volume Profile histogram (VAH / POC / VAL)
- 1H candlestick chart with entry/stop/target lines
- 4H context panel showing higher-timeframe VP bias
- AI reasoning + news sentiment (crypto only)
- Stacked VA badge when 2+ consecutive sessions trend same direction
- LOG OUTCOME button to save trade result to memory

### BACKTEST
Step through historical data hour by hour.
- Pick any date + number of days (1–7)
- PREV / NEXT to step candle by candle
- FAST FWD auto-advances every 1.2 seconds
- REVEAL shows next 6 candles + auto-detects if target or stop was hit

### AUTO BT
Automated 30/60/90-day backtest on any symbol.
- Equity curve (start = 100, 1% risk per trade)
- Full trade table with Win/Loss per trade
- Stats: Win rate, Avg win, Avg loss, Profit factor, Max drawdown
- Setup performance breakdown

### SCANNER
Scans all 20 symbols simultaneously.
- Shows active setups ranked by confidence
- Stacked VA indicator (↑↑×3 = strong trend)
- Click any card to jump to LIVE view
- Filter by All / Active only / Bullish / Bearish

### HEATMAP
Hourly win-rate heatmap built from backtest data.
- Shows which hours of day produce best results
- Grouped by trading session (morning / afternoon / evening / night)
- Run AUTO BT first for the same symbol to generate data

---

## Trade Journal (http://localhost:5000/journal)

Three tabs:
- **Overview** — equity curve, setup breakdown, asset breakdown
- **All Trades** — filterable table of every logged outcome
- **Report** — printable/exportable performance report

Log outcomes via the **LOG OUTCOME** button in LIVE mode after a trade.

---

## Volume Profile Rules (Fixed — Never Changed)

| Level | Meaning |
|-------|---------|
| **POC** (red) | Most traded price — acts as magnet |
| **VAH** (green) | Top of 40% value area |
| **VAL** (green) | Bottom of 40% value area |
| **HVN** | High Volume Node — price slows/reverses |
| **LVN** | Low Volume Node — price moves fast |

Value Area = **40%** of total volume (not the standard 70%)

### Setups

| Setup | Condition | Bias |
|-------|-----------|------|
| **Retracement** | Prev close above VA → price returns to VA | Long |
| **Retracement** | Prev close below VA → price returns to VA | Short |
| **Rollover** | Value at lows, price crosses above POC | Long |
| **Rollover** | Value at highs, price crosses below POC | Short |
| **Top Heavy** | Spike above VAH, closes inside VA | Short |
| **Bottom Heavy** | Spike below VAL, closes inside VA | Long |

### Bias Rules
- Close **above VAH** = bullish
- Close **below VAL** = bearish
- Close **inside VA** = neutral (no trade)
- **Stacked 2–3 sessions same direction** = strong trend — only trade with it

---

## Design Principles

1. **VP rules are FIXED** — `vp_engine.py` rules never modified by AI, news, or RAG
2. **News = confidence modifier only** — adjusts score ±25 pts max, never changes entry/stop
3. **RAG = context only** — past cases shown for reference, never override rules
4. **Wait for candle close** — never enter mid-candle
5. **Indian market data has 15-min delay** — news sentiment disabled for Indian symbols
6. **AI is optional** — system works fully without any API key

---

## File Structure

```
vp_agent4/
├── server.py           Flask backend — all API endpoints
├── vp_engine.py        VP calculation, setup detection, backtest engine
├── news_engine.py      RSS headlines, Fear & Greed, sentiment scoring
├── rag_store.py        JSON trade memory — stores & retrieves past cases
├── claude_agent.py     AI reasoning — routes to Groq / Gemini / Claude
├── dashboard.html      Full trading terminal UI
├── trade_journal.html  Standalone graphical trade journal
├── requirements.txt    Python dependencies
├── start.sh            Mac/Linux launcher
├── start.bat           Windows launcher
└── README.md           This file
```

---

## API Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /api/analysis?symbol=BTCUSDT&tf=1h` | Live VP analysis |
| `GET /api/htf?symbol=BTCUSDT` | 4H context panel data |
| `GET /api/symbols` | All available symbols by group |
| `GET /api/scanner` | Scan all symbols for active setups |
| `GET /api/heatmap?symbol=BTCUSDT&days=30` | Hourly win-rate heatmap |
| `GET /api/backtest/load?symbol=BTCUSDT&date=2025-01-01&days=3` | Load historical data |
| `GET /api/backtest/step?cache_key=...&window_idx=0` | Step through backtest |
| `GET /api/backtest/auto?symbol=BTCUSDT&days=90` | Auto 90-day backtest |
| `POST /api/outcome` | Log trade outcome to RAG memory |
| `GET /api/journal` | All logged trades for journal view |
| `GET /api/stats` | RAG memory statistics |

---

## Requirements

- Python 3.8+
- `flask` `flask-cors` `requests` `feedparser` `yfinance`
- Internet connection (Binance / Yahoo Finance APIs)
- Optional: Groq / Gemini / Claude API key for AI reasoning

---

*VP Agent v4 — for educational and paper trading purposes.*
*Always validate signals before live trading. Past backtest results do not guarantee future performance.*
