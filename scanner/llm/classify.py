"""Tier 1 — Haiku 4.5. Classify, dedup, extract entities, gate synthesis.

Runs over fresh news items (ticker + macro). Returns per-item:
  - type           (earnings, m&a, product, guidance, macro_*, rumor, litigation, analyst, other)
  - impact         (high | medium | low)
  - dedup_group    (a normalized topic slug — same story across outlets shares this)
  - tickers_mentioned (extra tickers explicitly named in the headline body)
  - route_to_synthesis (boolean — only "high" impact + ticker scope reaches Sonnet)
"""
from __future__ import annotations

import json
import logging
from typing import Iterable

from scanner import config
from scanner.llm.client import LLMClient

log = logging.getLogger(__name__)

BATCH_SIZE = 15

NEWS_TYPES = [
    "earnings",
    "guidance",
    "ma",
    "product",
    "analyst",
    "litigation",
    "rumor",
    "macro_fed",
    "macro_econ",
    "macro_geopol",
    "macro_commodity",
    "other",
]

CLASSIFY_TOOL = {
    "name": "classify_news_batch",
    "description": "Classify a batch of news items. Output one entry per input id.",
    "input_schema": {
        "type": "object",
        "properties": {
            "classifications": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "type": {"type": "string", "enum": NEWS_TYPES},
                        "impact": {"type": "string", "enum": ["high", "medium", "low"]},
                        "dedup_group": {
                            "type": "string",
                            "description": (
                                "Lowercase slug naming the underlying story. "
                                "The SAME slug must be used for identical stories "
                                "across outlets (e.g. 'fed_april_minutes_dovish_pivot')."
                            ),
                        },
                        "tickers_mentioned": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Tickers explicitly named in the title beyond the article's primary ticker.",
                        },
                        "route_to_synthesis": {
                            "type": "boolean",
                            "description": (
                                "True if this item is high-impact AND fresh enough that "
                                "Sonnet should write a 'why' synthesis using it. "
                                "Default false for stale, low-signal, or routine items."
                            ),
                        },
                    },
                    "required": ["id", "type", "impact", "dedup_group", "tickers_mentioned", "route_to_synthesis"],
                },
            }
        },
        "required": ["classifications"],
    },
}

SYSTEM_PROMPT = """You are the classification tier of a stock momentum scanner.

You receive a batch of news headlines and return a structured classification per item.
You do NOT write prose, summaries, or analysis — only the structured output.

## Type taxonomy

- **earnings**: a company reported quarterly/annual earnings results.
- **guidance**: forward-looking outlook revisions from a company (raised/lowered guidance).
- **ma**: M&A activity — acquisitions, mergers, divestitures, takeover speculation backed by sourcing.
- **product**: a product launch, recall, contract win, partnership, supply deal, regulatory approval/denial.
- **analyst**: sell-side action — upgrades, downgrades, target changes, initiations, model updates.
- **litigation**: lawsuit filed/dismissed, settlement, regulatory enforcement action, DOJ/SEC charges.
- **rumor**: unsourced or weakly-sourced speculation; NOT a confirmed corporate event.
- **macro_fed**: Federal Reserve communications — FOMC, minutes, speeches, balance-sheet actions.
- **macro_econ**: economic data releases — CPI, jobs, PCE, GDP, ISM, retail sales, housing.
- **macro_geopol**: geopolitics, war, sanctions, tariffs, elections.
- **macro_commodity**: oil/gas, gold, copper, crypto-as-asset-class moves driven by supply or policy.
- **other**: anything not covered above (use sparingly).

## Impact scoring (be honest — most items are low)

- **high**: directly explains a 3%+ move OR materially changes the investment thesis OR is a genuine surprise that the market hasn't already priced.
- **medium**: notable for the ticker but unlikely to drive >2% on its own; useful context.
- **low**: routine coverage, recap pieces, recycled angles, low-conviction analyst notes, weekend think-pieces.

## Dedup grouping

Group items that report the SAME underlying event under a single slug like
`fed_april_2026_minutes_dovish` or `nvda_q1_blackwell_beat`. Different outlets
covering the same story → same slug. Different angles on the same story → same slug.
Different stories that happen to mention the same ticker → DIFFERENT slugs.

## Routing to synthesis

Set `route_to_synthesis: true` ONLY when ALL of the following hold:
1. impact is `high`
2. it's a ticker-scoped item (not macro_*)
3. the item plausibly explains *today's* move (recent, material)

For macro items, leave `route_to_synthesis: false` — those go to a separate macro tier.

## Tickers_mentioned

If the headline names other tickers beyond the primary one (e.g. "NVDA-AMD price war heats up"),
list them here in uppercase. Empty list if none.

## Output discipline

- One classification object per input id, in the same order.
- Never invent items not in the input.
- Never omit items — if uncertain, classify as `other`/`low`/`route_to_synthesis: false`.
"""


def _format_batch(items: list[dict]) -> str:
    payload = [
        {
            "id": item["id"],
            "scope": item["scope"],
            "ticker": item.get("ticker"),
            "publisher": item.get("publisher", ""),
            "title": item["title"],
            "published_at": item["published_at"],
        }
        for item in items
    ]
    return json.dumps(payload, indent=2)


def classify(items: list[dict], client: LLMClient) -> dict[str, dict]:
    """Returns {item_id: classification_dict}. Items missing from output get a low/other default."""
    if not items:
        return {}

    by_id = {item["id"]: item for item in items}
    out: dict[str, dict] = {}

    for i in range(0, len(items), BATCH_SIZE):
        batch = items[i : i + BATCH_SIZE]
        result = client.call_structured(
            model=config.HAIKU_MODEL,
            system=SYSTEM_PROMPT,
            user=_format_batch(batch),
            output_tool=CLASSIFY_TOOL,
            audit_tier="haiku_classify",
            audit_key=f"batch_{i}",
            max_tokens=2048,
        )
        if not result:
            log.warning("Haiku batch %d returned no result; defaulting to low/other", i)
            for item in batch:
                out[item["id"]] = _default_classification(item["id"])
            continue

        for cls in result.get("classifications", []):
            iid = cls.get("id")
            if iid in by_id:
                out[iid] = cls

        for item in batch:
            if item["id"] not in out:
                out[item["id"]] = _default_classification(item["id"])

    log.info("Haiku classified %d items", len(out))
    return out


def _default_classification(item_id: str) -> dict:
    return {
        "id": item_id,
        "type": "other",
        "impact": "low",
        "dedup_group": f"unclassified_{item_id}",
        "tickers_mentioned": [],
        "route_to_synthesis": False,
    }


def attach(items: Iterable[dict], classifications: dict[str, dict]) -> list[dict]:
    """Merge classification fields back into the original news items."""
    enriched = []
    for item in items:
        cls = classifications.get(item["id"]) or _default_classification(item["id"])
        merged = dict(item)
        merged.update(
            {
                "type": cls.get("type", "other"),
                "impact": cls.get("impact", "low"),
                "dedup_group": cls.get("dedup_group"),
                "tickers_mentioned": cls.get("tickers_mentioned", []),
                "route_to_synthesis": cls.get("route_to_synthesis", False),
            }
        )
        enriched.append(merged)
    return enriched


def dedup(items: list[dict]) -> list[dict]:
    """Keep one item per dedup_group — prefer high impact, then earlier publish time."""
    by_group: dict[str, dict] = {}
    for item in items:
        g = item.get("dedup_group")
        if not g:
            by_group[item["id"]] = item
            continue
        existing = by_group.get(g)
        if not existing:
            by_group[g] = item
        else:
            new_impact = {"high": 2, "medium": 1, "low": 0}.get(item["impact"], 0)
            old_impact = {"high": 2, "medium": 1, "low": 0}.get(existing["impact"], 0)
            if new_impact > old_impact:
                by_group[g] = item
            elif new_impact == old_impact and item["published_at"] < existing["published_at"]:
                by_group[g] = item
    return list(by_group.values())
