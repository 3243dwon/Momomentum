"""Saturday weekly summary.

Classifies each ticker that saw momentum this week as real vs fakeout, then
asks Opus to predict forward trajectory with key levels and catalysts ahead.

Triggered by .github/workflows/weekly.yml on Saturday 9 AM ET.

Flow:
  1. Load the last 7 days of momentum events (weekly_events.json)
  2. Group by ticker; keep the top ~15 by weekly importance
  3. Pull 2-week daily bars from Alpaca for each
  4. Heuristic classify: real_momentum / fakeout / unclear
  5. Opus: forward prediction per ticker
  6. Write data/weekly.json + send Feishu digest card
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timedelta, timezone

import pandas as pd

from scanner import config, technicals, weekly_events
from scanner.alerts import feishu
from scanner.llm.client import get_client, LLMClient

log = logging.getLogger("weekly")

WEEKLY_FILE = config.DATA_DIR / "weekly.json"
MAX_TICKERS_ANALYZED = 15


# --- Heuristic classifier: real vs fakeout ---

def classify_heuristic(events: list[dict], weekly_bars: pd.DataFrame) -> tuple[str, dict]:
    """Rule-based first pass, before Opus.

    Signals of real momentum:
      - Week's close is near the week's high (low retracement)
      - Volume stayed elevated across multiple days (persistence)
      - More positive days than negative during the move window
    Signals of fakeout:
      - Big early-week spike followed by retracement back near prior level
      - Single-day volume burst then normal volume
      - Close is far below week's high (heavy giveback)
    """
    if weekly_bars is None or weekly_bars.empty or len(weekly_bars) < 4:
        return "unclear", {"reason": "insufficient data"}

    closes = weekly_bars["Close"].astype(float)
    highs = weekly_bars["High"].astype(float)
    lows = weekly_bars["Low"].astype(float)
    volumes = weekly_bars["Volume"].astype(float)

    week_open = float(closes.iloc[0])
    week_close = float(closes.iloc[-1])
    week_high = float(highs.max())
    week_low = float(lows.min())

    week_return = (week_close / week_open - 1) * 100 if week_open else 0
    # How much of the peak move was retained?
    if week_high > week_open and week_open > 0:
        retention = (week_close - week_open) / (week_high - week_open)
    else:
        retention = 1.0 if week_return >= 0 else 0.0

    # Volume persistence: fraction of days where volume > 20d avg (approx)
    avg_vol = float(volumes.mean())
    above_avg_days = int((volumes > avg_vol).sum())
    vol_persistence = above_avg_days / max(1, len(volumes))

    # Event count: how many scans flagged this as notable this week?
    event_count = len(events)
    # Fraction of events that had news
    with_news = sum(1 for e in events if e.get("has_news"))
    news_density = with_news / max(1, event_count)

    metrics = {
        "week_return_pct": round(week_return, 2),
        "week_high": round(week_high, 2),
        "week_low": round(week_low, 2),
        "week_close": round(week_close, 2),
        "retention_of_peak": round(retention, 2),
        "vol_persistence": round(vol_persistence, 2),
        "event_count": event_count,
        "news_density": round(news_density, 2),
    }

    # Heuristic scoring
    real_score = 0
    if retention >= 0.7 and week_return > 0:
        real_score += 2
    if vol_persistence >= 0.5:
        real_score += 1
    if news_density >= 0.4:
        real_score += 1
    if event_count >= 3:
        real_score += 1

    fake_score = 0
    if retention < 0.3 and week_high > week_open * 1.03:  # pop then give back
        fake_score += 2
    if vol_persistence < 0.25:
        fake_score += 1
    if event_count == 1 and abs(week_return) < 2:
        fake_score += 1

    if real_score >= fake_score + 2:
        return "real_momentum", metrics
    if fake_score >= real_score + 2:
        return "fakeout", metrics
    return "unclear", metrics


# --- Ticker selection ---

def select_top_tickers(events: list[dict], limit: int) -> dict[str, list[dict]]:
    """Group events by ticker, rank by weekly importance, keep top N."""
    by_ticker: dict[str, list[dict]] = {}
    for e in events:
        by_ticker.setdefault(e["ticker"], []).append(e)

    def score(tkr_events: list[dict]) -> float:
        max_pct = max((abs(e.get("pct_1d") or 0) for e in tkr_events), default=0)
        max_vol = max((e.get("rel_volume") or 0 for e in tkr_events), default=0)
        with_news = sum(1 for e in tkr_events if e.get("has_news"))
        n = len(tkr_events)
        return max_pct * 2 + min(max_vol, 10) * 2 + with_news * 3 + n
    sorted_tickers = sorted(by_ticker.items(), key=lambda kv: score(kv[1]), reverse=True)
    return dict(sorted_tickers[:limit])


# --- Opus prompt ---

WEEKLY_TOOL = {
    "name": "weekly_ticker_analysis",
    "description": "Analyze this week's momentum events and project forward 1-4 weeks.",
    "input_schema": {
        "type": "object",
        "properties": {
            "classification": {
                "type": "string",
                "enum": ["real_momentum", "fakeout", "unclear"],
                "description": (
                    "real_momentum = sustained buying with follow-through; "
                    "fakeout = spike that gave back most of its gain or had no supporting fundamentals; "
                    "unclear = mixed signals."
                ),
            },
            "classification_reasoning": {
                "type": "string",
                "description": "2-3 sentences on why — cite specific metrics (retention, volume persistence, news).",
            },
            "prediction": {
                "type": "string",
                "enum": ["continuation", "reversal", "rangebound"],
            },
            "prediction_confidence": {"type": "string", "enum": ["high", "medium", "low"]},
            "prediction_rationale": {
                "type": "string",
                "description": "2-3 sentences. What's the base case for next 1-4 weeks and why?",
            },
            "support_level": {"type": "number", "description": "Price level where buyers likely step in."},
            "resistance_level": {"type": "number", "description": "Price level where sellers likely cap upside."},
            "catalysts_ahead": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Named events in the next 1-4 weeks that would shift this forecast (earnings, conferences, product launches, macro prints).",
            },
            "horizon_days": {
                "type": "integer",
                "description": "Time horizon this prediction applies to, in days (typical: 5-20).",
            },
        },
        "required": [
            "classification", "classification_reasoning",
            "prediction", "prediction_confidence", "prediction_rationale",
        ],
    },
}

WEEKLY_SYSTEM = """You are a weekly equities analyst. You see one ticker's week of
momentum events (each scan's snapshot), its 2-week daily OHLCV, and a heuristic
pre-classification of real-vs-fakeout momentum.

Your job: write the sharpest honest take on what really happened this week AND
what you'd expect next 1-4 weeks, with named catalysts that would shift your view.

## Calibration

- Only call it 'real_momentum' if gains were largely retained AND volume persisted
  AND there's a plausible fundamental reason (news, earnings, sector shift). Low
  bar for 'unclear'.
- Only call it 'fakeout' when the spike gave back most of its gain or had no
  supporting catalyst. Short squeezes on low-float tickers are fakeouts — flag them.
- 'continuation' requires BOTH current-week holding AND a near-term catalyst
  or thesis. Don't predict continuation just because the week was green.

## Style

- Cite specific numbers (week return, retention, vol persistence).
- Never use 'amid' or 'investors are reacting to'.
- Don't hedge with 'may' or 'could' — state the base case, then list what would
  change your mind in catalysts_ahead.
- Empty catalysts_ahead is fine if there's nothing concrete on the calendar.

## Levels

Give support/resistance only if you can derive them from the 2-week data
(prior consolidation, week's high/low, gap levels). Skip if nothing clean."""


def build_user_prompt(
    ticker: str,
    events: list[dict],
    weekly_bars: pd.DataFrame,
    classification: str,
    metrics: dict,
) -> str:
    bars_summary = []
    for idx, row in weekly_bars.iterrows():
        date = idx.strftime("%Y-%m-%d") if hasattr(idx, "strftime") else str(idx)[:10]
        bars_summary.append({
            "date": date,
            "open": round(float(row["Open"]), 2),
            "high": round(float(row["High"]), 2),
            "low": round(float(row["Low"]), 2),
            "close": round(float(row["Close"]), 2),
            "volume": int(row["Volume"]),
        })

    event_summaries = []
    for e in events:
        event_summaries.append({
            "ts": e["ts"],
            "pct_1d": e.get("pct_1d"),
            "rel_volume": e.get("rel_volume"),
            "flags": e.get("flags", []),
            "news": e.get("has_news"),
            "synthesis": e.get("synthesis_summary"),
            "synthesis_verdict": e.get("synthesis_verdict"),
        })

    payload = {
        "ticker": ticker,
        "heuristic_classification": classification,
        "heuristic_metrics": metrics,
        "week_events": event_summaries,
        "daily_bars_2w": bars_summary,
    }
    return json.dumps(payload, indent=2)


# --- Main runner ---

def run_weekly() -> int:
    now = datetime.now(config.MARKET_TZ)
    log.info("Weekly summary run at %s", now.isoformat())

    events = weekly_events.load_week(now, days=7)
    if not events:
        log.warning("No events logged this week; weekly.json will be empty")
        _write_weekly([], now)
        return 0

    log.info("Loaded %d events this week", len(events))
    top = select_top_tickers(events, MAX_TICKERS_ANALYZED)
    log.info("Top %d tickers by weekly importance: %s", len(top), list(top.keys()))

    # Fetch 2-week daily bars for each ticker
    symbols = list(top.keys())
    all_bars: dict[str, pd.DataFrame] = {}
    from datetime import timedelta as td
    end_dt = datetime.now(timezone.utc) - td(minutes=20)
    start_dt = end_dt - td(days=16)

    for i in range(0, len(symbols), 100):
        batch = symbols[i : i + 100]
        try:
            from alpaca.data.requests import StockBarsRequest
            from alpaca.data.timeframe import TimeFrame
            from alpaca.data.enums import DataFeed, Adjustment
            req = StockBarsRequest(
                symbol_or_symbols=batch,
                timeframe=TimeFrame.Day,
                start=start_dt,
                end=end_dt,
                feed=DataFeed.IEX,
                adjustment=Adjustment.ALL,
            )
            bars = technicals._CLIENT.get_stock_bars(req)
        except Exception as e:
            log.warning("Daily-bar batch failed: %s", e)
            continue
        if bars.df is None or bars.df.empty:
            continue
        df = bars.df
        if "symbol" not in df.index.names:
            continue
        for symbol in df.index.get_level_values("symbol").unique():
            sub = df.xs(symbol, level="symbol").copy()
            sub = sub.rename(
                columns={"open": "Open", "high": "High", "low": "Low", "close": "Close", "volume": "Volume"}
            )
            all_bars[symbol] = sub

    # Heuristic classification + Opus analysis
    client = get_client()
    analyses: list[dict] = []
    for ticker, ticker_events in top.items():
        bars = all_bars.get(ticker)
        classification, metrics = classify_heuristic(ticker_events, bars if bars is not None else pd.DataFrame())

        opus_result = None
        if client and bars is not None and not bars.empty:
            user_prompt = build_user_prompt(ticker, ticker_events, bars, classification, metrics)
            opus_result = client.call_structured(
                model=config.OPUS_MODEL,
                system=WEEKLY_SYSTEM,
                user=user_prompt,
                output_tool=WEEKLY_TOOL,
                audit_tier="opus_weekly",
                audit_key=ticker,
                max_tokens=2048,
            )

        analyses.append({
            "ticker": ticker,
            "event_count": len(ticker_events),
            "heuristic_classification": classification,
            "metrics": metrics,
            "analysis": opus_result,
        })

    _write_weekly(analyses, now)
    _send_digest(analyses, now)
    return 0


def _write_weekly(analyses: list[dict], now: datetime) -> None:
    payload = {
        "generated_at": now.isoformat(),
        "week_ending": now.strftime("%Y-%m-%d"),
        "ticker_count": len(analyses),
        "analyses": analyses,
    }
    WEEKLY_FILE.write_text(json.dumps(payload, indent=2))
    log.info("Wrote %d analyses to %s", len(analyses), WEEKLY_FILE)


def _send_digest(analyses: list[dict], now: datetime) -> None:
    real = [a for a in analyses if (a.get("analysis") or {}).get("classification") == "real_momentum"][:3]
    fake = [a for a in analyses if (a.get("analysis") or {}).get("classification") == "fakeout"][:3]

    def line(a):
        t = a["ticker"]
        wret = a["metrics"].get("week_return_pct")
        sign = "+" if (wret or 0) >= 0 else ""
        pred = (a.get("analysis") or {}).get("prediction", "—")
        rationale = (a.get("analysis") or {}).get("prediction_rationale", "")[:200]
        return f"  • **{t}** ({sign}{wret}%) → *{pred}*: {rationale}"

    body = f"**Week ending {now.strftime('%a %b %d')}** — {len(analyses)} tickers analyzed\n\n"
    if real:
        body += "**Real momentum (worth watching next week):**\n" + "\n".join(line(a) for a in real) + "\n\n"
    if fake:
        body += "**Fakeouts (don't chase these):**\n" + "\n".join(line(a) for a in fake) + "\n\n"
    body += f"_Full analysis at `/weekly`_"

    alert = {
        "ticker": None,
        "type": "weekly",
        "title": f"📊 Weekly summary — week of {now.strftime('%b %d')}",
        "body_md": body,
        "link": None,
    }
    feishu.send(alert)


def main() -> int:
    parser = argparse.ArgumentParser(description="Weekly momentum summary")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    return run_weekly()


if __name__ == "__main__":
    sys.exit(main())
