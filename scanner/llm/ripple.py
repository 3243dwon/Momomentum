"""Tier 3b — Opus 4.7. Forward second-order catalyst ("ripple") prediction.

The synthesis tier (Sonnet) explains why a ticker *already moved*, reading only
that ticker's own news. But the highest-value catalysts are relational: a deal
about NVDA/GOOGL that names INTC as the backup foundry moves INTC, yet the story
is tagged to NVDA/GOOGL — so synthesis never sees it, and you find out late.

This tier closes that gap and runs forward, not backward. For each high-impact
news item on a *popular* stock, Opus reasons about which OTHER US-listed names
the story helps or hurts (suppliers, customers, competitors, backup vendors,
JV partners, pure-play peers) — with an explicit mechanism, direction, and
confidence. Each predicted name is then cross-referenced against the live scan:
the gold is a name that *hasn't moved yet* ("not yet priced in"), because that's
the call you can still act on.

Cost is bounded hard: only popular triggers, only high-impact company news,
deduped to one Opus call per story, capped at MAX_RIPPLE_EVENTS_PER_SCAN.
"""
from __future__ import annotations

import json
import logging

from scanner import config, universe
from scanner.llm.client import LLMClient

log = logging.getLogger(__name__)

# ── output schema ────────────────────────────────────────────────────
_AFFECTED_ITEM = {
    "type": "object",
    "properties": {
        "ticker": {"type": "string"},
        "rationale": {
            "type": "string",
            "description": "Specific transmission mechanism — supply/customer/competitor link, "
            "revenue exposure, capacity backup, JV/licensing tie. NOT 'positive sentiment'.",
        },
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        "horizon": {"type": "string", "enum": ["intraday", "days", "weeks", "months"]},
    },
    "required": ["ticker", "rationale", "confidence", "horizon"],
}

RIPPLE_TOOL = {
    "name": "ripple_prediction",
    "description": "Predict which OTHER tickers a company's news will help or hurt, with mechanism.",
    "input_schema": {
        "type": "object",
        "properties": {
            "event_summary": {
                "type": "string",
                "description": "One plain-English sentence describing what happened.",
            },
            "primary_drivers": {
                "type": "array",
                "items": {"type": "string"},
                "description": "The 1-3 underlying mechanisms driving the ripple (e.g. 'second-source "
                "qualification', 'capex pull-forward', 'pricing umbrella lifted').",
            },
            "beneficiaries": {"type": "array", "items": _AFFECTED_ITEM, "maxItems": 6},
            "losers": {"type": "array", "items": _AFFECTED_ITEM, "maxItems": 6},
        },
        "required": ["event_summary", "primary_drivers", "beneficiaries", "losers"],
    },
}

SYSTEM_PROMPT = """You are the forward-looking ripple tier of a stock momentum scanner.

You receive ONE piece of high-impact news about a single, widely-held company,
plus that company's live price action. Your job is NOT to explain that company's
move. Your job is to predict which OTHER US-listed companies this news will move
— ideally before they move — with an explicit causal mechanism for each.

## The job

- Map the transmission. A supply deal helps the supplier and the backup supplier,
  and can hurt the incumbent it displaces. A capacity expansion helps the equipment
  makers. A price cut hurts direct competitors. Guidance up/down re-rates the whole
  read-through group. Name the specific companies on each side.
- Think second-order, not the obvious one. The company the news is ABOUT is already
  moving on its own — do NOT list it. List the names the market hasn't connected yet.
- Mechanism, not vibes. "Benefits from positive sentiment" is rejected. State the
  actual link: who supplies whom, % revenue exposure, who gets designed in/out, whose
  pricing umbrella just changed, which pure-play peer re-rates on the read-through.

## Calibrated confidence — be honest

- `high`: direct, well-established exposure (named in the deal, sole/primary supplier,
  pure-play peer with the same end-market). Rare.
- `medium`: a clear but second-order link with one inference step.
- `low`: plausible but multi-step or speculative — use freely for rumor/M&A chatter,
  where the read-through is real but uncertain.

## Horizon

- intraday/days = a flow/sentiment read-through. weeks/months = the event genuinely
  changes the other company's order book or earnings outlook. Don't claim weeks+ for
  a sentiment trade.

## What NOT to do

- Do not list the company the news is about.
- Do not name megacaps (AAPL, MSFT, AMZN, GOOGL) reflexively — only if truly exposed.
- Do not invent tickers. Use real, commonly-traded US tickers.
- Do not pad. 2-3 well-supported names beat 6 stretches. Empty lists are valid and
  honest when the news has no real read-through to other companies.
"""


# ── trigger selection (cost gate) ────────────────────────────────────
def select_trigger_events(
    ticker_news_enriched: dict[str, list[dict]],
    popular: set[str],
    rows: list[dict],
    cap: int,
) -> list[list[dict]]:
    """Pick the high-impact, popular-stock news stories worth an Opus ripple call.

    Returns a list of event groups (each a list of news items sharing a
    dedup_group). Gated to: impact=high, ticker scope, type in
    RIPPLE_TRIGGER_TYPES, primary ticker in `popular`. Deduped per story, then
    ranked by the trigger ticker's live move/volume so the most market-relevant
    stories win the (capped) budget.
    """
    if cap <= 0:
        return []
    by_ticker = {r["ticker"]: r for r in rows}
    trigger_types = set(config.RIPPLE_TRIGGER_TYPES)

    groups: dict[str, list[dict]] = {}
    for ticker, items in ticker_news_enriched.items():
        if popular and ticker not in popular:
            continue
        for n in items:
            if n.get("scope") != "ticker":
                continue
            if n.get("impact") != "high":
                continue
            if (n.get("type") or "") not in trigger_types:
                continue
            g = n.get("dedup_group") or n["id"]
            groups.setdefault(g, []).append(n)

    def group_score(items: list[dict]) -> float:
        # The trigger ticker is the items' shared primary ticker; score by its
        # live move + volume so a story on a name the tape already cares about
        # outranks a quiet one when we're over the cap.
        t = items[0].get("ticker")
        row = by_ticker.get(t or "")
        if not row:
            return 0.0
        return abs(row.get("pct_1d") or 0) * 2 + min(row.get("rel_volume") or 0, 10)

    ranked = sorted(groups.values(), key=group_score, reverse=True)
    return ranked[:cap]


# ── Opus call + universe filter ──────────────────────────────────────
def _format_user(trigger_ticker: str, trigger_row: dict | None, items: list[dict]) -> str:
    payload = {
        "company": trigger_ticker,
        "company_price_action": {
            "pct_1d": (trigger_row or {}).get("pct_1d"),
            "pct_5d": (trigger_row or {}).get("pct_5d"),
            "rel_volume": (trigger_row or {}).get("rel_volume"),
        },
        "news": [
            {
                "publisher": n.get("publisher", n.get("source", "")),
                "title": n["title"],
                "type": n.get("type"),
                "published_at": n["published_at"],
                "url": n.get("url"),
            }
            for n in items
        ],
    }
    return json.dumps(payload, indent=2)


_universe_cache: set[str] | None = None


def _universe() -> set[str]:
    global _universe_cache
    if _universe_cache is None:
        _universe_cache = set(universe.load_tags().keys())
    return _universe_cache


def _filter_to_universe(result: dict, trigger_ticker: str) -> dict:
    """Drop names not in our universe, and never let the trigger ticker itself
    appear in its own ripple list (the news already explains that one)."""
    uni = _universe()
    for key in ("beneficiaries", "losers"):
        kept = []
        for b in result.get(key, []) or []:
            tk = str(b.get("ticker", "")).upper().lstrip("$")
            if not tk or tk == trigger_ticker:
                continue
            if uni and tk not in uni:
                continue
            b["ticker"] = tk
            kept.append(b)
        result[key] = kept
    return result


# ── price cross-reference: the "report before" classification ────────
def _priced_in(direction: str, pct_1d: float | None) -> str:
    """Where does the live tape sit relative to the prediction?

    'no'          → hasn't moved meaningfully in our direction yet (the call you
                    can still act on — this is what we push).
    'partial'     → started moving our way.
    'yes'         → already moved our way (the read-through is largely priced).
    'contradicted'→ moved hard against us (the tape disagrees with the thesis).
    """
    thr = config.RIPPLE_PRICED_IN_PCT
    if pct_1d is None:
        return "no"  # not even a mover this scan → definitely not priced in
    fav = pct_1d if direction == "bullish" else -pct_1d
    if fav >= 2 * thr:
        return "yes"
    if fav >= thr:
        return "partial"
    if fav <= -thr:
        return "contradicted"
    return "no"


def _flatten(event: dict, rows_by_ticker: dict[str, dict]) -> list[dict]:
    """Turn one event's beneficiaries/losers into per-ticker prediction records,
    each annotated with the live move + priced_in classification."""
    out: list[dict] = []
    for key, direction in (("beneficiaries", "bullish"), ("losers", "bearish")):
        for b in event.get(key, []) or []:
            t = b["ticker"]
            row = rows_by_ticker.get(t)
            pct = row.get("pct_1d") if row else None
            out.append(
                {
                    "ticker": t,
                    "direction": direction,
                    "rationale": b.get("rationale", ""),
                    "confidence": b.get("confidence", "low"),
                    "horizon": b.get("horizon", "days"),
                    "priced_in": _priced_in(direction, pct),
                    "pct_1d": pct,
                    "rel_volume": row.get("rel_volume") if row else None,
                    "trigger_ticker": event["trigger_ticker"],
                    "event_summary": event.get("event_summary", ""),
                    "news_url": event.get("news_url"),
                    "source_news_ids": event.get("source_news_ids", []),
                }
            )
    return out


_PRICED_IN_RANK = {"no": 0, "partial": 1, "contradicted": 2, "yes": 3}
_CONF_RANK = {"high": 0, "medium": 1, "low": 2}


def analyze(
    trigger_groups: list[list[dict]],
    rows: list[dict],
    client: LLMClient,
) -> tuple[list[dict], list[dict]]:
    """Run Opus on each trigger story; return (events, predictions).

    events      — one analysis object per story (for the web's event view + audit).
    predictions — the flattened, price-annotated per-ticker calls (for alerts,
                  the dashboard cards, and accuracy tracking), newest/freshest first.
    """
    if not trigger_groups:
        return [], []

    rows_by_ticker = {r["ticker"]: r for r in rows}
    log.info("Opus ripple: analyzing %d trigger stories", len(trigger_groups))

    def worker(items: list[dict]) -> dict | None:
        trigger_ticker = items[0].get("ticker")
        trigger_row = rows_by_ticker.get(trigger_ticker or "")
        result = client.call_structured(
            model=config.OPUS_MODEL,
            system=SYSTEM_PROMPT,
            user=_format_user(trigger_ticker, trigger_row, items),
            output_tool=RIPPLE_TOOL,
            audit_tier="opus_ripple",
            audit_key=trigger_ticker,
            max_tokens=2048,
        )
        if not result:
            return None
        result = _filter_to_universe(result, trigger_ticker)
        if not result.get("beneficiaries") and not result.get("losers"):
            return None  # honest empty — no read-through, nothing to surface
        result["trigger_ticker"] = trigger_ticker
        result["source_news_ids"] = [n["id"] for n in items]
        result["headlines"] = [n["title"] for n in items]
        result["news_url"] = next((n.get("url") for n in items if n.get("url")), None)
        return result

    results = client.batch_structured(trigger_groups, worker, max_workers=4)
    events = [r for _t, r in results if r]

    predictions: list[dict] = []
    for ev in events:
        predictions.extend(_flatten(ev, rows_by_ticker))

    # Freshest (not-yet-priced-in) and highest-confidence first — that's the
    # ordering the dashboard, the Feishu push, and tracking all want.
    predictions.sort(
        key=lambda p: (_PRICED_IN_RANK.get(p["priced_in"], 9), _CONF_RANK.get(p["confidence"], 9))
    )
    log.info("Opus ripple: %d events → %d predictions (%d not yet priced in)",
             len(events), len(predictions),
             sum(1 for p in predictions if p["priced_in"] == "no"))
    return events, predictions
