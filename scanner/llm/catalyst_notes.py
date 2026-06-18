"""Per-holding catalyst read — the portfolio 'trim/add' tier.

For each portfolio holding, given its upcoming dated catalysts plus live price
context, the model writes a short event-driven read: a stance (add-on-weakness /
trim-into-strength / hold / watch / reduce-risk), the reasoning, the next
catalyst that defines the window, and a one-line bull/bear. Mirrors the macro
tier (scanner/llm/macro.py) — one structured Opus call per holding, run
concurrently and capped by the small portfolio size.

Not investment advice — an event-mechanics read tied to scheduled catalysts.
"""
from __future__ import annotations

import json
import logging

from scanner import config
from scanner.llm.client import LLMClient

log = logging.getLogger(__name__)

NOTES_TOOL = {
    "name": "portfolio_holding_read",
    "description": "Write the event-driven add/trim read for one portfolio holding.",
    "input_schema": {
        "type": "object",
        "properties": {
            "stance": {
                "type": "string",
                "enum": ["add-on-weakness", "trim-into-strength", "hold", "watch", "reduce-risk"],
                "description": "The single best-fit stance given the position and its next catalyst.",
            },
            "read": {
                "type": "string",
                "description": "2-3 sentences. The actual reasoning, tied to the specific dated catalyst and the position's context (winner vs underwater, stretched vs cheap). Concrete, not generic.",
            },
            "next_catalyst": {
                "type": "string",
                "description": "The single catalyst that defines the next window, as 'YYYY-MM-DD — what it is'. Use the soonest high-impact dated event for this name.",
            },
            "bull": {"type": "string", "description": "One line: the case for the position into the catalyst."},
            "bear": {"type": "string", "description": "One line: the risk into the catalyst."},
            "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        },
        "required": ["stance", "read", "next_catalyst", "bull", "bear", "confidence"],
    },
}

SYSTEM_PROMPT = """You are the portfolio catalyst-read tier of a momentum scanner.

You receive ONE holding the user actually owns: its ticker, position size, live
price action, and its upcoming DATED catalysts (next earnings, ex-dividend) plus
the macro calendar ahead. You write a short, event-driven read that maps those
catalysts to add/trim windows.

## What makes this useful

- **Tie everything to the dated catalyst.** The point is *when* the window opens,
  not a vibe. Reference the specific event and date.
- **Be position-aware.** A name up large and stretched leans trim-into-strength
  (especially into a binary print); an underwater quality name leans
  add-on-weakness or wait-for-the-catalyst. Use the price action you're given.
- **Respect the confidence label.** If the next earnings date is marked
  "estimated", say so — don't present an aggregator estimate as company-confirmed.
- **One stance, honestly chosen.** Pick the single best-fit stance. `hold` and
  `watch` are valid answers; don't manufacture action.
- **Calibrated confidence.** `high` only when the catalyst is near, dated, and the
  setup is clear. `low` when the date is soft or the read is a stretch.

## What NOT to do

- No generic "monitor the situation" filler. Every line should be specific to THIS
  name and THIS catalyst.
- Don't invent catalysts or dates beyond what you're given.
- Don't give an explicit buy/sell instruction or position sizing — frame it as the
  window the catalyst creates and what would confirm each side.

Keep it tight. This is a glanceable read, not an essay.
"""


def _format_user(holding: dict, events: list[dict], macro: list[dict],
                 row: dict | None, synth: dict | None) -> str:
    position: dict = {}
    if row:
        position = {
            "price": row.get("price"),
            "pct_1d": row.get("pct_1d"),
            "pct_5d": row.get("pct_5d"),
        }
        cost_basis = holding.get("cost_basis")
        shares = holding.get("shares")
        price = row.get("price")
        if cost_basis and shares and price:
            try:
                avg = float(cost_basis) / float(shares)
                if avg:
                    position["unrealized_pct"] = round((price - avg) / avg * 100, 1)
            except (TypeError, ValueError, ZeroDivisionError):
                pass

    payload = {
        "ticker": holding["ticker"],
        "shares": holding.get("shares"),
        "position": position,
        "your_note": holding.get("note"),
        "upcoming_catalysts": [
            {
                "type": e.get("type"),
                "label": e.get("label"),
                "date": e.get("date"),
                "days_until": e.get("days_until"),
                "confidence": e.get("confidence"),
                "detail": e.get("detail"),
            }
            for e in events
        ],
        "macro_ahead": [
            {"label": m.get("label"), "date": m.get("date"), "days_until": m.get("days_until")}
            for m in macro[:6]
        ],
        "recent_read": (synth or {}).get("summary"),
    }
    return json.dumps(payload, indent=2, default=str)


def generate(
    holdings: list[dict],
    by_ticker: dict[str, list[dict]],
    macro: list[dict],
    rows_by_ticker: dict[str, dict],
    syntheses: dict[str, dict],
    client: LLMClient,
) -> dict[str, dict]:
    """Return {ticker: note} for every holding the model could read. Missing
    tickers (model returned nothing) simply don't appear — the page degrades to
    showing the raw catalysts without a note."""
    targets = [h for h in holdings if h.get("ticker")]
    if not targets:
        return {}

    log.info("Catalyst notes: reading %d holdings with %s", len(targets), config.CATALYST_NOTES_MODEL)

    def worker(holding: dict) -> dict | None:
        t = holding["ticker"]
        return client.call_structured(
            model=config.CATALYST_NOTES_MODEL,
            system=SYSTEM_PROMPT,
            user=_format_user(
                holding,
                by_ticker.get(t, []),
                macro,
                rows_by_ticker.get(t),
                syntheses.get(t),
            ),
            output_tool=NOTES_TOOL,
            audit_tier="catalyst_notes",
            audit_key=t,
            max_tokens=900,
        )

    results = client.batch_structured(targets, worker, max_workers=4)
    notes: dict[str, dict] = {}
    for holding, result in results:
        if result:
            notes[holding["ticker"]] = result
    log.info("Catalyst notes: produced %d reads", len(notes))
    return notes
