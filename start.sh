#!/bin/bash
# VP Agent v4 — Mac/Linux launcher
# Usage:
#   ./start.sh                          # no AI reasoning
#   ./start.sh sk-ant-YOUR-KEY          # Claude AI
#   ./start.sh gsk_YOUR-GROQ-KEY        # Groq (fast + free)
#   ./start.sh AIzaSy-YOUR-GEMINI-KEY   # Gemini

cd "$(dirname "$0")"

if [ ! -z "$1" ]; then
    KEY="$1"
    if [[ "$KEY" == gsk_* ]]; then
        export GROQ_API_KEY="$KEY"
        echo "Using Groq AI"
    elif [[ "$KEY" == AIza* ]]; then
        export GEMINI_API_KEY="$KEY"
        echo "Using Gemini AI"
    elif [[ "$KEY" == sk-ant* ]]; then
        export ANTHROPIC_API_KEY="$KEY"
        echo "Using Claude AI"
    fi
fi

echo "Installing dependencies..."
pip install -q flask flask-cors requests feedparser yfinance 2>/dev/null || \
pip3 install -q flask flask-cors requests feedparser yfinance 2>/dev/null

echo ""
echo "======================================================"
echo "  VP AGENT v4 — Starting..."
echo "======================================================"
echo "  Dashboard : http://localhost:5000"
echo "  Journal   : http://localhost:5000/journal"
echo "======================================================"
echo ""

python3 server.py || python server.py
