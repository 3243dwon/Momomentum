"""Per-scan LLM cost rollup.

The LLMClient records token usage for every call it makes. At the end of a
scan we roll those into ``data/cost.json`` — a committed, human-readable
daily ledger — so weekly spend is visible in git history instead of buried
in ephemeral, gitignored audit files.

The dollar figures are estimates: they depend on the pricing table below,
which must be updated by hand if Anthropic changes prices. The estimate only
affects reporting, never scanner behavior.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime

from scanner import config

log = logging.getLogger(__name__)

COST_FILE = config.DATA_DIR / "cost.json"
MAX_DAYS = 60  # keep the ledger trimmed to the last ~2 months

# USD per million tokens. Cache writes bill at 1.25x the input rate; cache
# reads at 0.10x. Update these if Anthropic pricing changes.
PRICING_USD_PER_MTOK = {
    "haiku":  {"input": 1.0,  "output": 5.0},
    "sonnet": {"input": 3.0,  "output": 15.0},
    "opus":   {"input": 15.0, "output": 75.0},
}
_CACHE_WRITE_MULT = 1.25
_CACHE_READ_MULT = 0.10


def _tier_for_model(model: str) -> str:
    m = (model or "").lower()
    if "haiku" in m:
        return "haiku"
    if "opus" in m:
        return "opus"
    return "sonnet"  # default — also covers sonnet explicitly


def _call_cost_usd(model: str, usage: dict) -> float:
    rate = PRICING_USD_PER_MTOK[_tier_for_model(model)]
    inp = usage.get("input_tokens", 0) or 0
    out = usage.get("output_tokens", 0) or 0
    cw = usage.get("cache_creation_input_tokens", 0) or 0
    cr = usage.get("cache_read_input_tokens", 0) or 0
    total = (
        inp * rate["input"]
        + out * rate["output"]
        + cw * rate["input"] * _CACHE_WRITE_MULT
        + cr * rate["input"] * _CACHE_READ_MULT
    )
    return total / 1_000_000


def _empty_tier() -> dict:
    return {
        "calls": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_tokens": 0,
        "usd": 0.0,
    }


def summarize(calls: list[dict]) -> dict:
    """Roll call records into a per-tier summary.

    Buckets by audit-tier label (haiku_classify, sonnet_synth, macro,
    opus_mom, …) so the ledger shows *what* spent the money, not just which
    model. Each call is still priced by its own model, so dollar figures stay
    correct even when a tier's model changes (e.g. macro Opus→Sonnet).
    """
    summary = {"calls": len(calls), "by_tier": {}, "total_usd": 0.0}
    for c in calls:
        usage = c.get("usage") or {}
        model = c.get("model", "")
        tier = c.get("tier") or "unknown"
        cost = _call_cost_usd(model, usage)
        bt = summary["by_tier"].setdefault(tier, _empty_tier())
        bt["calls"] += 1
        bt["input_tokens"] += usage.get("input_tokens", 0) or 0
        bt["output_tokens"] += usage.get("output_tokens", 0) or 0
        bt["cache_read_tokens"] += usage.get("cache_read_input_tokens", 0) or 0
        bt["usd"] += cost
        summary["total_usd"] += cost
    summary["total_usd"] = round(summary["total_usd"], 4)
    for bt in summary["by_tier"].values():
        bt["usd"] = round(bt["usd"], 4)
    return summary


def record_scan(calls: list[dict], now: datetime | None = None) -> dict:
    """Fold this scan's costs into ``data/cost.json``'s daily ledger.

    Returns the per-scan summary (for logging). Never raises — a cost-logging
    failure must not abort a scan.
    """
    summary = summarize(calls)
    try:
        now = now or datetime.now(config.MARKET_TZ)
        day = now.date().isoformat()

        ledger: dict = {}
        if COST_FILE.exists():
            try:
                ledger = json.loads(COST_FILE.read_text())
            except Exception:
                ledger = {}
        daily = ledger.setdefault("daily", {})
        entry = daily.setdefault(
            day, {"scans": 0, "calls": 0, "total_usd": 0.0, "by_tier": {}}
        )
        entry["scans"] += 1
        entry["calls"] += summary["calls"]
        entry["total_usd"] = round(entry["total_usd"] + summary["total_usd"], 4)
        for tier, bt in summary["by_tier"].items():
            et = entry["by_tier"].setdefault(tier, _empty_tier())
            et["calls"] += bt["calls"]
            et["input_tokens"] += bt["input_tokens"]
            et["output_tokens"] += bt["output_tokens"]
            et["cache_read_tokens"] += bt["cache_read_tokens"]
            et["usd"] = round(et["usd"] + bt["usd"], 4)

        # Trim to the last MAX_DAYS calendar days.
        if len(daily) > MAX_DAYS:
            for old in sorted(daily)[:-MAX_DAYS]:
                del daily[old]

        COST_FILE.write_text(json.dumps(ledger, indent=2))
    except Exception as e:  # never let cost logging break a scan
        log.warning("Cost log write failed: %s", e)
    return summary
