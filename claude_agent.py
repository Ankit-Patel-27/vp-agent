"""
Claude Agent — AI reasoning layer.
Tries in order: Groq → Gemini → Claude → rule-based fallback.
Set env vars: GROQ_API_KEY, GEMINI_API_KEY, or ANTHROPIC_API_KEY.
VP rules are NEVER changed by AI output.
"""
import os, json, requests

GROQ_KEY     = os.getenv("GROQ_API_KEY", "")
GEMINI_KEY   = os.getenv("GEMINI_API_KEY", "")
ANTHROPIC_KEY = os.getenv("ANTHROPIC_API_KEY", "")


def analyze(vp, setup, trade_params, news, rag_ctx, conf_mod) -> dict:
    prompt = _build_prompt(vp, setup, trade_params, news, rag_ctx, conf_mod)

    # Try Groq first (fastest, nearly free)
    if GROQ_KEY:
        result = _call_groq(prompt)
        if result: return result

    # Try Gemini
    if GEMINI_KEY:
        result = _call_gemini(prompt)
        if result: return result

    # Try Claude
    if ANTHROPIC_KEY:
        result = _call_claude(prompt)
        if result: return result

    # Fallback — rule-based
    return _rule_based(setup, trade_params, news, conf_mod)


def _build_prompt(vp, setup, tp, news, rag_ctx, conf_mod) -> str:
    base_conf = 50
    mod = conf_mod.get("modifier", 0)
    if setup.get("setup_type") != "none":
        base_conf = 65 if setup["setup_type"] in ("retracement",) else 55
    conf = max(10, min(95, base_conf + mod))
    news_dir = news.get("sentiment", {}).get("direction", "neutral")
    news_score = news.get("sentiment", {}).get("score", 0)
    fg = news.get("fear_greed", {})

    return f"""You are a Volume Profile trading analyst. Analyze this setup and return JSON only.

VOLUME PROFILE:
- VAH: {vp['vah']} | POC: {vp['poc']} | VAL: {vp['val']}
- VA Spread: {vp['va_spread']} | Bias: {vp['bias']}
- Close vs VA: {vp['close_vs_va']}
- Session High: {vp.get('session_high',0)} | Low: {vp.get('session_low',0)}

SETUP DETECTED: {setup['setup_type']} | Bias: {setup['trade_bias']}
Description: {setup['description']}

TRADE PARAMS:
- Entry: {tp.get('entry')} | Stop: {tp.get('stop')}
- T1: {tp.get('target_1')} | T2: {tp.get('target_2')}
- R Ratio: {tp.get('r_ratio')}

NEWS: Direction={news_dir} | Score={news_score} | F&G={fg.get('value',50)} ({fg.get('label','')})
News modifier: {mod:+d}

SIMILAR PAST TRADES:
{rag_ctx}

Return ONLY valid JSON, no markdown:
{{
  "setup_type": "{setup['setup_type']}",
  "trade_bias": "{setup['trade_bias']}",
  "confidence": {conf},
  "r_ratio": {tp.get('r_ratio') or 0},
  "news_impact": "supportive|headwind|neutral",
  "what_to_watch": "one sentence — key level or condition to watch",
  "key_risk": "one sentence — main risk to this trade",
  "reasoning": "2-3 sentence plain English analysis of this setup"
}}"""


def _call_groq(prompt: str) -> dict:
    try:
        r = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_KEY}", "Content-Type": "application/json"},
            json={"model": "llama-3.3-70b-versatile", "max_tokens": 400,
                  "messages": [{"role": "user", "content": prompt}]},
            timeout=15
        )
        text = r.json()["choices"][0]["message"]["content"].strip()
        return _parse_json(text)
    except Exception as e:
        print(f"[Groq] error: {e}")
        return None


def _call_gemini(prompt: str) -> dict:
    try:
        r = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-exp:generateContent?key={GEMINI_KEY}",
            headers={"Content-Type": "application/json"},
            json={"contents": [{"parts": [{"text": prompt}]}],
                  "generationConfig": {"maxOutputTokens": 400}},
            timeout=15
        )
        text = r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
        return _parse_json(text)
    except Exception as e:
        print(f"[Gemini] error: {e}")
        return None


def _call_claude(prompt: str) -> dict:
    try:
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": ANTHROPIC_KEY, "anthropic-version": "2023-06-01",
                     "Content-Type": "application/json"},
            json={"model": "claude-haiku-4-5-20251001", "max_tokens": 400,
                  "messages": [{"role": "user", "content": prompt}]},
            timeout=20
        )
        text = r.json()["content"][0]["text"].strip()
        return _parse_json(text)
    except Exception as e:
        print(f"[Claude] error: {e}")
        return None


def _parse_json(text: str) -> dict:
    # Strip markdown fences if present
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    try:
        return json.loads(text.strip())
    except Exception:
        return None


def _rule_based(setup, tp, news, conf_mod) -> dict:
    """Fallback when no API key is set."""
    s = setup.get("setup_type", "none")
    b = setup.get("trade_bias", "neutral")
    mod = conf_mod.get("modifier", 0)
    news_dir = news.get("sentiment", {}).get("direction", "neutral")

    base = {"retracement": 65, "rollover": 55, "top_heavy": 58, "bottom_heavy": 60}.get(s, 40)
    conf = max(10, min(95, base + mod))

    news_impact = ("supportive" if news_dir == b
                   else "headwind" if news_dir not in ("neutral",) and news_dir != b
                   else "neutral")

    watch_map = {
        "retracement":  f"Watch for candle close confirmation above/below POC ({tp.get('poc', '—')})",
        "rollover":     f"Watch for price to hold above/below POC ({tp.get('poc', '—')})",
        "top_heavy":    f"Watch for rejection at VAH — price should stay inside VA",
        "bottom_heavy": f"Watch for recovery above VAL — failed breakdown signal",
    }
    risk_map = {
        "retracement":  "Trend continuation may override retracement — watch stacked VAs",
        "rollover":     "False rollover — price snaps back through POC invalidates setup",
        "top_heavy":    "Strong momentum may push above VAH and hold — wait for candle close",
        "bottom_heavy": "Continued selling below VAL invalidates setup immediately",
    }

    reasoning = (
        f"No AI API key configured. Rule-based analysis: {setup.get('description', '—')}. "
        f"Confidence {conf}% based on setup quality{f' and {news_impact} news' if news_impact != 'neutral' else ''}. "
        f"Set GROQ_API_KEY, GEMINI_API_KEY, or ANTHROPIC_API_KEY for full AI reasoning."
    )

    return {
        "setup_type":   s,
        "trade_bias":   b,
        "confidence":   conf,
        "r_ratio":      tp.get("r_ratio") or 0,
        "news_impact":  news_impact,
        "what_to_watch": watch_map.get(s, "Watch key VP levels for reaction"),
        "key_risk":      risk_map.get(s, "Setup invalidated if price closes beyond stop level"),
        "reasoning":     reasoning,
    }
