"""Tier 2 — Sonnet 4.6. Per-ticker 'why' synthesis.

For each routed ticker that has at least one routed-to-synthesis news item,
ask Sonnet: given today's price/volume + these headlines, what's the most
honest one-paragraph explanation of the move? Cite the news that supports it.
"""
from __future__ import annotations

import json
import logging

from scanner import config
from scanner.llm.client import LLMClient

log = logging.getLogger(__name__)

SYNTH_TOOL = {
    "name": "synthesize_ticker_move",
    "description": "Explain why this ticker moved today, citing the supplied news.",
    "input_schema": {
        "type": "object",
        "properties": {
            "summary": {
                "type": "string",
                "description": "1-3 sentences. No marketing tone. Plain English. Cite the news mechanism, not the headline verbatim.",
            },
            "supporting_news_ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": "IDs of the input news items that materially support the explanation. May be empty if no news explains it.",
            },
            "verdict": {
                "type": "string",
                "enum": ["news_explains_move", "partial_explanation", "move_unexplained_by_news"],
            },
            "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        },
        "required": ["summary", "supporting_news_ids", "verdict", "confidence"],
    },
}

SYSTEM_PROMPT = """You are the synthesis tier of a stock momentum scanner.

You receive ONE ticker's price/volume readings plus a small set of news items
already classified as high-impact. Your job: write the most honest, concise
explanation of today's move.

## Output discipline

- 1-3 sentences. No filler. No hedging language ("appears to", "may have").
- Plain English. No marketing tone. No "rallying on bullish sentiment" platitudes.
- Cite the news *mechanism* (what changed for the company), not the headline verbatim.
- Always include `supporting_news_ids` for items you actually relied on. Empty if the news doesn't explain the move.

## Verdict calibration — be honest, not generous

- `news_explains_move`: ≥1 high-impact news item directly explains the magnitude and direction.
  Example: "+4% on Q1 beat with raised FY guidance" — earnings news fully accounts for it.
- `partial_explanation`: news provides context but doesn't fully account for the move's size or timing.
  Example: stock up 6% but news is just an analyst note — the note explains some, not all.
- `move_unexplained_by_news`: nothing in the supplied news plausibly explains today's move.
  Use this freely. Most "mystery moves" really are unexplained — peer rotation, options flow, or
  flows you can't see. Don't invent reasons. Empty `supporting_news_ids` is correct here.

## Confidence calibration

- `high`: clear causal link between news and move, magnitude proportional.
- `medium`: plausible link but other factors likely involved.
- `low`: weak inference, lots of guessing.

## What you should NOT do

- Do not fabricate news that isn't in the input.
- Do not claim "investors are reacting to..." unless an input headline says so.
- Do not use the word "amid" — it's the tell of bad financial copy.
- Do not list all news items in supporting_news_ids — only the ones doing real explanatory work.
"""


def _format_user(ticker: str, technicals: dict, news_items: list[dict]) -> str:
    payload = {
        "ticker": ticker,
        "technicals": {
            "price": technicals.get("price"),
            "pct_1d": technicals.get("pct_1d"),
            "pct_5d": technicals.get("pct_5d"),
            "rel_volume": technicals.get("rel_volume"),
            "rsi_14": technicals.get("rsi_14"),
            "macd_cross": technicals.get("macd_cross"),
            "flags": technicals.get("flags", []),
        },
        "news": [
            {
                "id": n["id"],
                "publisher": n.get("publisher", ""),
                "title": n["title"],
                "type": n.get("type"),
                "impact": n.get("impact"),
                "published_at": n["published_at"],
            }
            for n in news_items
        ],
    }
    return json.dumps(payload, indent=2)


def _synthesize_one(client: LLMClient, ticker: str, technicals: dict, news_items: list[dict]) -> dict | None:
    return client.call_structured(
        model=config.SONNET_MODEL,
        system=SYSTEM_PROMPT,
        user=_format_user(ticker, technicals, news_items),
        output_tool=SYNTH_TOOL,
        audit_tier="sonnet_synth",
        audit_key=ticker,
        max_tokens=1024,
    )


def synthesize(
    enriched_news_by_ticker: dict[str, list[dict]],
    technicals_by_ticker: dict[str, dict],
    client: LLMClient,
    must_synthesize: set[str] | None = None,
) -> dict[str, dict]:
    """Produce one 'why' per ticker.

    Synthesizes for:
      - any ticker with high-impact news flagged route_to_synthesis (default), AND
      - every ticker in must_synthesize (typically watchlist + new top-20 entrants),
        even if no news exists — Sonnet will return verdict='move_unexplained_by_news'.
    """
    must_synthesize = must_synthesize or set()
    target_tickers: set[str] = set()

    for ticker, items in enriched_news_by_ticker.items():
        if any(n.get("route_to_synthesis") for n in items):
            target_tickers.add(ticker)

    for ticker in must_synthesize:
        if ticker in technicals_by_ticker:
            target_tickers.add(ticker)

    targets: list[tuple[str, dict, list[dict]]] = []
    for ticker in target_tickers:
        tech = technicals_by_ticker.get(ticker)
        if not tech:
            continue
        items = enriched_news_by_ticker.get(ticker, [])
        # Prefer routed/high-impact news; fall back to any news; then empty.
        routed = [n for n in items if n.get("route_to_synthesis")]
        news_for_call = routed or items[:5]
        targets.append((ticker, tech, news_for_call))

    if not targets:
        log.info("Sonnet: no tickers reached synthesis tier")
        return {}

    log.info("Sonnet: synthesizing %d tickers concurrently", len(targets))

    def worker(target):
        ticker, tech, routed = target
        return _synthesize_one(client, ticker, tech, routed)

    results = client.batch_structured(targets, worker, max_workers=8)

    out: dict[str, dict] = {}
    for (ticker, _tech, _routed), result in results:
        if result:
            out[ticker] = result
    log.info("Sonnet: produced %d syntheses", len(out))
    return out
