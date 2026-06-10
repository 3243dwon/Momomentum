"""Scan briefing — one structured Sonnet call per scan → data/briefing.json.

Condenses what the scan already computed (regime, top movers, desk takes,
catalyst alerts, not-priced-in ripple calls, macro events) into the one-screen
answer to "what matters this scan": a headline, the actionable takes with
levels, a short watch list, what changed since the last briefing, and honest
caveats about data age.

Fail-soft by design: any error (no client, API failure, malformed output)
skips the write and keeps the previous briefing.json in place. Gated behind
config.BRIEFING_ENABLED (default True). One call per scan, no extra retries
beyond the client's defaults.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime

from scanner import config
from scanner.llm.client import LLMClient

log = logging.getLogger(__name__)

BRIEFING_FILE = config.DATA_DIR / "briefing.json"

MAX_ACTIONS = 3
MAX_WATCH = 5
MAX_CHANGED = 3
MAX_CAVEATS = 2

BRIEFING_TOOL = {
    "name": "scan_briefing",
    "description": "Produce the one-screen trader briefing for this scan.",
    "input_schema": {
        "type": "object",
        "properties": {
            "headline": {
                "type": "string",
                "description": "≤120 chars. The one-sentence answer to 'what matters this scan'.",
            },
            "market_state": {
                "type": "object",
                "properties": {
                    "regime": {"type": "string", "description": "The regime label from the input (risk_on/risk_off/mixed/unknown)."},
                    "line": {"type": "string", "description": "≤140 chars. One line on the tape — SPY/QQQ trend, vol, what it means for entries."},
                },
                "required": ["regime", "line"],
            },
            "actions": {
                "type": "array",
                "maxItems": MAX_ACTIONS,
                "description": "ONLY the desk decision=='take' picks from the input. Empty if none.",
                "items": {
                    "type": "object",
                    "properties": {
                        "ticker": {"type": "string"},
                        "direction": {"type": "string", "enum": ["long", "short"]},
                        "entry": {"type": ["number", "null"]},
                        "stop": {"type": ["number", "null"]},
                        "target": {"type": ["number", "null"]},
                        "line": {"type": "string", "description": "One terse line: the setup + the PM's reasoning."},
                    },
                    "required": ["ticker", "direction", "entry", "stop", "target", "line"],
                },
            },
            "watch": {
                "type": "array",
                "maxItems": MAX_WATCH,
                "description": "Names worth watching but not actionable yet — from catalysts, ripple calls, movers in the input.",
                "items": {
                    "type": "object",
                    "properties": {
                        "ticker": {"type": "string"},
                        "type": {"type": "string", "description": "Why it's here: catalyst, ripple, mover, macro."},
                        "line": {"type": "string", "description": "One terse line."},
                    },
                    "required": ["ticker", "type", "line"],
                },
            },
            "changed": {
                "type": "array",
                "maxItems": MAX_CHANGED,
                "items": {"type": "string"},
                "description": "What's different vs the previous briefing headline. Empty if nothing meaningful changed.",
            },
            "caveats": {
                "type": "array",
                "maxItems": MAX_CAVEATS,
                "items": {"type": "string"},
                "description": "Honest limits. MUST include data window/age context (scan window, how stale prices may be).",
            },
        },
        "required": ["headline", "market_state", "actions", "watch", "changed", "caveats"],
    },
}

SYSTEM_PROMPT = """You write the one-screen briefing for a stock momentum scanner's front page.

You receive everything one scan computed: market regime, the top movers, the
agent desk's vetted "take" picks with trade levels, catalyst alerts, forward
ripple predictions that haven't priced in yet, macro events, and the previous
briefing's headline.

## Voice

- Terse trader voice. Short declaratives. Numbers over adjectives.
- No hedging boilerplate ("investors should note", "it remains to be seen",
  "this is not financial advice"). No filler. No "amid".

## Hard rules

- Tickers ONLY from the provided data. NEVER invent or recall a ticker that
  isn't in the input.
- `actions` come ONLY from the desk_takes input (decision=="take"). Use their
  entry/stop/target as given. If desk_takes is empty, actions is empty —
  do not promote watch names into actions.
- `watch` names come from the catalysts / ripple_not_priced_in / top_movers /
  macro inputs. ≤5, highest-signal first.
- `changed`: compare against previous_headline. New leadership, regime flip,
  a take appearing/disappearing. If this is the first briefing or nothing
  meaningfully changed, return [].
- `caveats` (≤2) MUST include data window/age context: which scan window this
  is (RTH / pre-market / after-hours / overnight / weekend) and that prices
  are as of scan time. Add one real analytical caveat if there is one.
- Respect the length limits: headline ≤120 chars, market_state.line ≤140 chars.
"""


def _previous_headline() -> str | None:
    try:
        prev = json.loads(BRIEFING_FILE.read_text())
        return prev.get("headline")
    except Exception:
        return None


def _assemble_inputs(
    regime: dict,
    rows: list[dict],
    recommendations: dict,
    alerts: list[dict],
    ripple_predictions: list[dict],
    macro_analyses: list[dict],
    window_name: str,
    now: datetime,
) -> dict:
    movers = sorted(
        (r for r in rows if r.get("pct_1d") is not None),
        key=lambda r: abs(r["pct_1d"]),
        reverse=True,
    )[:10]

    desk_takes = []
    for side in ("longs", "shorts"):
        for rec in (recommendations or {}).get(side, []):
            desk = rec.get("desk") or {}
            if desk.get("decision") != "take":
                continue
            levels = rec.get("levels") or {}
            desk_takes.append({
                "ticker": rec.get("ticker"),
                "direction": rec.get("direction", "long"),
                "entry": levels.get("entry"),
                "stop": levels.get("stop"),
                "target": levels.get("target"),
                "size": desk.get("size"),
                "pm_rationale": desk.get("rationale"),
            })

    catalysts = [
        {"ticker": a.get("ticker"), "title": a.get("title")}
        for a in (alerts or [])
        if a.get("type") == "catalyst"
    ]

    ripple_fresh = [
        {
            "ticker": p.get("ticker"),
            "direction": p.get("direction"),
            "confidence": p.get("confidence"),
            "trigger_ticker": p.get("trigger_ticker"),
            "rationale": (p.get("rationale") or "")[:200],
        }
        for p in (ripple_predictions or [])
        if p.get("priced_in") == "no"
    ][:8]

    macro = [
        {
            "event": m.get("event_summary", ""),
            "primary_drivers": m.get("primary_drivers", []),
        }
        for m in (macro_analyses or [])
    ][:5]

    return {
        "scan_time": now.isoformat(),
        "window": window_name,
        "regime": {
            "label": (regime or {}).get("label", "unknown"),
            "spy_pct_1d": (regime or {}).get("spy_pct_1d"),
            "spy_above_50d": (regime or {}).get("spy_above_50d"),
            "spy_above_200d": (regime or {}).get("spy_above_200d"),
            "qqq_pct_1d": (regime or {}).get("qqq_pct_1d"),
            "vxx_stress_ratio": (regime or {}).get("vxx_stress_ratio"),
        },
        "top_movers": [
            {
                "ticker": r["ticker"],
                "pct_1d": r.get("pct_1d"),
                "rel_volume": r.get("rel_volume"),
                "flags": r.get("flags") or [],
            }
            for r in movers
        ],
        "desk_takes": desk_takes,
        "catalysts": catalysts,
        "ripple_not_priced_in": ripple_fresh,
        "macro_events": macro,
        "previous_headline": _previous_headline(),
    }


def _num_or_none(v) -> float | None:
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def _sanitize(result: dict, inputs: dict, window_name: str, now: datetime) -> dict:
    """Clamp lengths, enforce the ticker provenance rules, fill required
    fields — the web codes against this shape exactly."""
    take_tickers = {t.get("ticker") for t in inputs.get("desk_takes", [])}
    allowed = set(take_tickers)
    for key in ("top_movers", "catalysts", "ripple_not_priced_in"):
        allowed.update(item.get("ticker") for item in inputs.get(key, []))
    allowed.discard(None)

    ms = result.get("market_state") or {}
    market_state = {
        "regime": str(ms.get("regime") or inputs["regime"].get("label") or "unknown"),
        "line": str(ms.get("line") or "")[:140],
    }

    actions = []
    for a in result.get("actions") or []:
        if not isinstance(a, dict) or a.get("ticker") not in take_tickers:
            continue
        direction = a.get("direction")
        if direction not in ("long", "short"):
            continue
        actions.append({
            "ticker": a["ticker"],
            "direction": direction,
            "entry": _num_or_none(a.get("entry")),
            "stop": _num_or_none(a.get("stop")),
            "target": _num_or_none(a.get("target")),
            "line": str(a.get("line") or ""),
        })
    actions = actions[:MAX_ACTIONS]

    watch = []
    for w in result.get("watch") or []:
        if not isinstance(w, dict) or w.get("ticker") not in allowed:
            continue
        watch.append({
            "ticker": w["ticker"],
            "type": str(w.get("type") or ""),
            "line": str(w.get("line") or ""),
        })
    watch = watch[:MAX_WATCH]

    changed = [str(c) for c in (result.get("changed") or []) if c][:MAX_CHANGED]

    caveats = [str(c) for c in (result.get("caveats") or []) if c][:MAX_CAVEATS]
    if not caveats:
        caveats = [
            f"Data from the {window_name} scan window as of "
            f"{now.strftime('%H:%M %Z')}; prices may lag by up to a scan cycle."
        ]

    return {
        "generated_at": now.isoformat(),
        "window": window_name,
        "headline": str(result.get("headline") or "")[:120],
        "market_state": market_state,
        "actions": actions,
        "watch": watch,
        "changed": changed,
        "caveats": caveats,
    }


def run(
    *,
    client: LLMClient | None,
    regime: dict,
    rows: list[dict],
    recommendations: dict,
    alerts: list[dict],
    ripple_predictions: list[dict],
    macro_analyses: list[dict],
    window,
    now: datetime,
) -> dict | None:
    """Build + write data/briefing.json. Returns the payload, or None when
    skipped/failed (previous file stays in place either way)."""
    if not config.BRIEFING_ENABLED:
        log.info("Briefing disabled (BRIEFING_ENABLED)")
        return None
    if client is None:
        log.info("Briefing: no LLM client, skipping (previous briefing kept)")
        return None

    window_name = getattr(window, "value", str(window))
    try:
        inputs = _assemble_inputs(
            regime or {}, rows or [], recommendations or {}, alerts or [],
            ripple_predictions or [], macro_analyses or [], window_name, now,
        )
        result = client.call_structured(
            model=config.SONNET_MODEL,
            system=SYSTEM_PROMPT,
            user=json.dumps(inputs, indent=2),
            output_tool=BRIEFING_TOOL,
            audit_tier="sonnet_briefing",
            audit_key=window_name,
            max_tokens=1500,
        )
        if not result:
            log.warning("Briefing: model returned no result; previous briefing kept")
            return None
        if not (result.get("headline") or "").strip():
            log.warning("Briefing: empty headline; previous briefing kept")
            return None

        payload = _sanitize(result, inputs, window_name, now)
        BRIEFING_FILE.write_text(json.dumps(payload, indent=2))
        log.info(
            "Wrote briefing.json: %d action(s), %d watch, headline: %s",
            len(payload["actions"]), len(payload["watch"]), payload["headline"],
        )
        return payload
    except Exception as e:
        log.warning("Briefing failed (previous briefing kept): %s", e)
        return None
