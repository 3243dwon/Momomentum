"""Tier 3 — Opus 4.7. Macro \u2192 beneficiary/loser reasoning.

This is the differentiator vs commodity scanners. For each macro event
(deduped, high-impact), Opus reasons about second-order beneficiaries and
losers across the US equity universe — with explicit mechanism and confidence.

We constrain the output to tickers in our universe.json so the web app can
link them; anything Opus names that's not in our universe gets dropped.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from scanner import config
from scanner.llm.client import LLMClient

log = logging.getLogger(__name__)

UNIVERSE_FILE = config.DATA_DIR / "universe.json"

MACRO_TOOL = {
    "name": "macro_beneficiary_analysis",
    "description": "Identify second-order beneficiaries and losers from a macro event.",
    "input_schema": {
        "type": "object",
        "properties": {
            "event_summary": {
                "type": "string",
                "description": "One sentence describing the event in plain English.",
            },
            "primary_drivers": {
                "type": "array",
                "items": {"type": "string"},
                "description": "The 1-3 underlying mechanisms (e.g. 'lower discount rate', 'tariff cost passthrough', 'supply chain disruption').",
            },
            "beneficiaries": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "ticker": {"type": "string"},
                        "rationale": {
                            "type": "string",
                            "description": "Specific causal mechanism — not 'benefits from positive sentiment'. Cite revenue exposure, supply chain link, peer correlation, or rate sensitivity explicitly.",
                        },
                        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                        "horizon": {"type": "string", "enum": ["intraday", "days", "weeks", "months"]},
                    },
                    "required": ["ticker", "rationale", "confidence", "horizon"],
                },
                "maxItems": 8,
            },
            "losers": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "ticker": {"type": "string"},
                        "rationale": {"type": "string"},
                        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                        "horizon": {"type": "string", "enum": ["intraday", "days", "weeks", "months"]},
                    },
                    "required": ["ticker", "rationale", "confidence", "horizon"],
                },
                "maxItems": 8,
            },
        },
        "required": ["event_summary", "primary_drivers", "beneficiaries", "losers"],
    },
}

SYSTEM_PROMPT = """You are the macro reasoning tier of a stock momentum scanner.

You receive a single macro event (one or more headlines covering the same story)
and must identify which US-listed equities are most exposed — both beneficiaries
and losers — with explicit causal mechanisms.

## What separates this from generic commentary

- **Mechanism, not vibes.** "Benefits from positive sentiment" is rejected. State the
  actual transmission: revenue exposure %, input cost pass-through, supply chain link,
  rate sensitivity (duration), peer-rotation correlation, regulatory spillover.
- **Specific tickers, not sectors.** Name individual companies. If it's truly sector-wide,
  pick the 2-3 best-pure-play representatives and say why.
- **Calibrated confidence.** `high` is rare and reserved for direct, well-established
  exposure (e.g. tariff on Chinese solar → First Solar gains, near-pure-play domestic
  manufacturer). `medium` is a clear but second-order link. `low` is a reasoning chain
  with multiple uncertain steps.
- **Honest horizon.** Intraday = options/headline trade. Days = sentiment + flows.
  Weeks = positioning shift. Months = thesis change. Don't claim weeks+ unless the
  event genuinely changes earnings outlook.

## What NOT to do

- Do not list 8 beneficiaries when only 2-3 are well-supported. Quality > quantity.
- Do not name megacaps reflexively (AAPL, MSFT, GOOGL, AMZN) unless they really are exposed.
- Do not say "could benefit if X happens" — only direct exposure to THIS event.
- Do not include both a ticker AND its ETF (pick one).
- Do not invent tickers. Use real, US-listed tickers as commonly traded.

## Empty lists are valid

If the event has no clear beneficiaries or losers — for example, a routine FOMC
statement that didn't surprise — return empty `beneficiaries` and `losers`. That's
more useful than a list of stretch reasoning.
"""


_universe_cache: set[str] | None = None


def _universe() -> set[str]:
    global _universe_cache
    if _universe_cache is None:
        if UNIVERSE_FILE.exists():
            _universe_cache = set(json.loads(UNIVERSE_FILE.read_text())["tickers"])
        else:
            _universe_cache = set()
    return _universe_cache


def _format_user(group_items: list[dict]) -> str:
    payload = {
        "headlines": [
            {
                "publisher": item.get("publisher", item.get("source", "")),
                "title": item["title"],
                "published_at": item["published_at"],
                "url": item["url"],
            }
            for item in group_items
        ],
    }
    return json.dumps(payload, indent=2)


def _filter_to_universe(result: dict) -> dict:
    """Drop any ticker Opus named that isn't in our universe."""
    uni = _universe()
    if not uni:
        return result
    for key in ("beneficiaries", "losers"):
        result[key] = [b for b in result.get(key, []) if b["ticker"].upper() in uni]
    return result


def analyze(macro_news: list[dict], client: LLMClient) -> list[dict]:
    """Group macro news by dedup_group, run Opus on each group, return event analyses."""
    if not macro_news:
        return []

    by_group: dict[str, list[dict]] = {}
    for item in macro_news:
        g = item.get("dedup_group") or item["id"]
        by_group.setdefault(g, []).append(item)

    groups = [(g, items) for g, items in by_group.items() if items]
    log.info("Opus: analyzing %d macro event groups", len(groups))

    def worker(target):
        group_id, items = target
        result = client.call_structured(
            model=config.OPUS_MODEL,
            system=SYSTEM_PROMPT,
            user=_format_user(items),
            output_tool=MACRO_TOOL,
            audit_tier="opus_macro",
            audit_key=group_id,
            max_tokens=2048,
        )
        if not result:
            return None
        result = _filter_to_universe(result)
        result["dedup_group"] = group_id
        result["source_news_ids"] = [item["id"] for item in items]
        result["headlines"] = [item["title"] for item in items]
        return result

    results = client.batch_structured(groups, worker, max_workers=4)
    analyses = [r for _t, r in results if r]
    log.info("Opus: produced %d macro analyses", len(analyses))
    return analyses
