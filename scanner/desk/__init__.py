"""Tier-4 agent desk — a panel of perspectives over recommend.py's picks.

recommend.py *generates* candidate picks from a hand-weighted score. The desk
*reviews* each one through four independent disciplines and lets a portfolio
manager reconcile them:

  Signal   (Haiku)  — price action only: clean entry or exhausted chase?
  Research (Haiku)  — catalyst durability: real why, or already priced in?
  Risk     (Haiku)  — the skeptic, holds a VETO: what kills this trade?
  PM       (Sonnet) — reconciles the three + the book + regime; decides + sizes.

Design notes:
  - Each agent is ONE batched call over all candidates (≤12), so a scan costs
    4 LLM calls total, not 4×N. Advisors run on Haiku (cheap), PM on Sonnet.
  - Reviews the recommend.py picks; does NOT replace them. The verdict is
    attached as rec["desk"] and shown on the dashboard.
  - Fails soft: any LLM failure leaves rec["desk"] unset and the picks render
    exactly as before.

See docs/agent-desk.md for the full charter.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from scanner import config
from scanner.llm.client import LLMClient

log = logging.getLogger(__name__)

# Cost control: the desk's LLM calls are the only non-free thing in the
# pipeline. Re-running four agents on every hourly scan is wasteful when the
# picks haven't changed. So we cache verdicts keyed by the pick set's
# signature and only re-run the agents when the picks change or the cache goes
# stale — typically a few times a day instead of ~hourly.
_DESK_CACHE_FILE = config.CACHE_DIR / "desk_cache.json"
_DESK_MAX_AGE_HOURS = 12  # refresh at least this often even if picks are unchanged


def _picks_signature(picks: list[dict]) -> str:
    return ",".join(sorted(f"{p['ticker']}:{p['direction']}" for p in picks))


def _load_cache() -> dict:
    try:
        return json.loads(_DESK_CACHE_FILE.read_text())
    except Exception:
        return {}


def _save_cache(signature: str, now: datetime, verdicts: dict[str, dict]) -> None:
    try:
        _DESK_CACHE_FILE.write_text(json.dumps(
            {"signature": signature, "ts": now.isoformat(), "verdicts": verdicts}, indent=2
        ))
    except Exception as e:
        log.warning("Desk: could not persist cache: %s", e)


def _cache_fresh(ts: str | None, now: datetime) -> bool:
    if not ts:
        return False
    try:
        t = datetime.fromisoformat(ts)
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
    except Exception:
        return False
    return (now - t).total_seconds() < _DESK_MAX_AGE_HOURS * 3600


# --- Per-agent data diets ----------------------------------------------------
# Each agent sees only its slice of the candidate, by design — that's what makes
# the perspectives independent rather than four copies of the same view.

def _signal_view(rec: dict, row: dict) -> dict:
    intr = row.get("intraday") or {}
    return {
        "ticker": rec["ticker"],
        "direction": rec["direction"],
        "pct_1d": row.get("pct_1d"),
        "pct_5d": row.get("pct_5d"),
        "rel_volume": row.get("rel_volume"),
        "rsi_14": row.get("rsi_14"),
        "macd_cross": row.get("macd_cross"),
        "above_vwap": intr.get("above_vwap"),
        "spark": (row.get("spark") or [])[-8:],
    }


def _research_view(rec: dict, row: dict) -> dict:
    syn = row.get("synthesis") or {}
    return {
        "ticker": rec["ticker"],
        "direction": rec["direction"],
        "sector": row.get("sector"),
        "tier": row.get("tier"),
        "news_count": row.get("news_count"),
        "synthesis_verdict": syn.get("verdict"),
        "synthesis_confidence": syn.get("confidence"),
        "synthesis_summary": (syn.get("summary") or "")[:280],
        "reasons": rec.get("reasons", []),
    }


def _risk_view(rec: dict, row: dict, regime: dict) -> dict:
    return {
        "ticker": rec["ticker"],
        "direction": rec["direction"],
        "pct_1d": row.get("pct_1d"),
        "pct_5d": row.get("pct_5d"),
        "rsi_14": row.get("rsi_14"),
        "caution_level": row.get("caution_level"),
        "caution_reasons": row.get("caution_reasons", []),
        "regime_label": regime.get("label"),
        "spy_above_50d": regime.get("spy_above_50d"),
        "spy_above_200d": regime.get("spy_above_200d"),
        "vxx_stress_ratio": regime.get("vxx_stress_ratio"),
    }


# --- Tool schemas (structured output) ----------------------------------------

def _advisor_tool(name: str, vote_desc: str) -> dict:
    return {
        "name": name,
        "description": f"Return one verdict per candidate. {vote_desc}",
        "input_schema": {
            "type": "object",
            "properties": {
                "verdicts": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "ticker": {"type": "string"},
                            "vote": {"type": "string", "enum": ["agree", "neutral", "against"]},
                            "conviction": {"type": "integer", "minimum": 1, "maximum": 5},
                            "note": {"type": "string", "description": "≤12 words, specific."},
                        },
                        "required": ["ticker", "vote", "conviction", "note"],
                    },
                }
            },
            "required": ["verdicts"],
        },
    }


_RISK_TOOL = {
    "name": "risk_review",
    "description": "Flag the reason NOT to take each trade. Veto only when you'd refuse the trade.",
    "input_schema": {
        "type": "object",
        "properties": {
            "verdicts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "ticker": {"type": "string"},
                        "veto": {"type": "boolean"},
                        "severity": {"type": "string", "enum": ["low", "medium", "high"]},
                        "concern": {"type": "string", "description": "≤12 words. The single biggest risk."},
                    },
                    "required": ["ticker", "veto", "severity", "concern"],
                },
            }
        },
        "required": ["verdicts"],
    },
}

_PM_TOOL = {
    "name": "pm_decision",
    "description": "Reconcile the three advisor verdicts into a final call + size + written plan per candidate.",
    "input_schema": {
        "type": "object",
        "properties": {
            "verdicts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "ticker": {"type": "string"},
                        "decision": {"type": "string", "enum": ["take", "pass"]},
                        "size": {"type": "string", "enum": ["full", "half", "quarter", "none"]},
                        "agreement": {"type": "string", "enum": ["unanimous", "majority", "split", "pm_override"]},
                        "rationale": {"type": "string", "description": "≤16 words. The decision in a line; cite the disagreement if any."},
                        "plan": {
                            "type": "string",
                            "description": (
                                "2-4 sentences, plain language, like advice to a friend. For a "
                                "'take': how to enter (the provided entry/support), where the stop "
                                "and first target sit (use the provided levels + R:R), the one-line "
                                "thesis, and the main risk to watch. For a 'pass': one sentence on "
                                "why you'd skip it. No jargon dumps, no hedging."
                            ),
                        },
                    },
                    "required": ["ticker", "decision", "size", "agreement", "rationale", "plan"],
                },
            }
        },
        "required": ["verdicts"],
    },
}


# --- Agent prompts -----------------------------------------------------------

_SIGNAL_SYS = (
    "You are the SIGNAL agent on a momentum desk. You judge PRICE ACTION ONLY — "
    "ignore news and fundamentals, that's not your job. For each candidate (and "
    "its trade direction), decide whether the entry is clean (fresh momentum, "
    "room to run) or poor (already extended, exhausted, chasing). 'agree' = good "
    "entry for the stated direction; 'against' = bad entry; 'neutral' = mixed. "
    "Be a hard grader on late entries."
)
_RESEARCH_SYS = (
    "You are the RESEARCH agent on a momentum desk. You judge CATALYST DURABILITY. "
    "A move with a real, fresh catalyst that can sustain = 'agree'. A move that is "
    "pure technical noise, or news already fully priced in = 'against'. No catalyst "
    "but clean technical = 'neutral'. Don't reward stale news."
)
_RISK_SYS = (
    "You are the RISK agent on a momentum desk — the skeptic. Your job is to find "
    "the reason NOT to take each trade: wrong regime (e.g. shorting strength when "
    "SPY > 50d, or buying into a risk-off tape), crowded/late entry, RSI extreme, "
    "stretched caution. Set veto=true only for trades you would refuse. Default "
    "skeptical; a clean trade in the right regime gets veto=false, severity=low."
)
_PM_SYS = (
    "You are the PORTFOLIO MANAGER on a momentum desk. You see three advisor "
    "verdicts (signal/research/risk) per candidate, the regime, whether it's on "
    "the book (watchlist), and pre-computed trade levels (entry, support/"
    "resistance, stop, target, R:R). Reconcile the advisors into a final decision "
    "and size. Honor the Risk veto unless you have a strong reason to override "
    "(say so via agreement='pm_override'). 'take' with size full/half/quarter; "
    "'pass' = none. Unanimous + clean risk → larger size; disagreement → smaller "
    "or pass.\n\n"
    "Then write `plan` — a short, plain-language trade plan a busy trader can act "
    "on. Use the PROVIDED level numbers (don't invent your own). Sound like a "
    "sharp colleague giving advice, not a textbook: where to get in, where the "
    "stop and first target are, the one-line why, and the one thing that would "
    "make you wrong. Concrete over hedged."
)


def _call(client: LLMClient, model: str, system: str, payload: list[dict],
          tool: dict, audit_tier: str) -> dict[str, dict]:
    """One batched agent call → {ticker: verdict}. Empty dict on failure."""
    user = "Candidates:\n" + json.dumps(payload, separators=(",", ":"))
    out = client.call_structured(
        model=model, system=system, user=user, output_tool=tool,
        max_tokens=1500, audit_tier=audit_tier,
    )
    if not out or not isinstance(out.get("verdicts"), list):
        return {}
    return {v["ticker"]: v for v in out["verdicts"] if v.get("ticker")}


def review(recommendations: dict, rows: list[dict], regime: dict | None,
           watchlist: set[str], client: LLMClient | None,
           now: datetime | None = None) -> int:
    """Run the desk over the recommend.py picks, attaching rec['desk'] in place.
    Returns the number of picks reviewed. No-op (0) when no client or no picks.

    Cost guard: if the pick set is unchanged from the last run and the cache is
    still fresh, reuse cached verdicts and make ZERO LLM calls."""
    if client is None:
        return 0
    now = now or datetime.now(timezone.utc)
    regime = regime or {}
    by_ticker = {r["ticker"]: r for r in rows}
    picks = [
        rec for rec in (recommendations.get("longs", []) + recommendations.get("shorts", []))
        if rec.get("ticker") in by_ticker
    ]
    if not picks:
        return 0

    # --- Cache check: same picks + fresh → reuse, no LLM spend ---
    signature = _picks_signature(picks)
    cache = _load_cache()
    if cache.get("signature") == signature and _cache_fresh(cache.get("ts"), now):
        cached = cache.get("verdicts", {})
        n = 0
        for r in picks:
            v = cached.get(r["ticker"])
            if v:
                r["desk"] = v
                n += 1
        log.info("Desk: pick set unchanged + cache fresh — reused %d verdicts, 0 LLM calls", n)
        return n

    # Three advisor passes (Haiku), one batched call each.
    signal = _call(client, config.HAIKU_MODEL, _SIGNAL_SYS,
                   [_signal_view(r, by_ticker[r["ticker"]]) for r in picks],
                   _advisor_tool("signal_review", "agree=clean entry, against=poor entry."),
                   "desk_signal")
    research = _call(client, config.HAIKU_MODEL, _RESEARCH_SYS,
                     [_research_view(r, by_ticker[r["ticker"]]) for r in picks],
                     _advisor_tool("research_review", "agree=durable catalyst, against=priced-in/noise."),
                     "desk_research")
    risk = _call(client, config.HAIKU_MODEL, _RISK_SYS,
                 [_risk_view(r, by_ticker[r["ticker"]], regime) for r in picks],
                 _RISK_TOOL, "desk_risk")

    # PM pass (Sonnet): sees the three verdicts + book membership + regime.
    pm_payload = []
    for r in picks:
        t = r["ticker"]
        pm_payload.append({
            "ticker": t,
            "direction": r["direction"],
            "score": r.get("score"),
            "on_watchlist": t in watchlist,
            "regime_label": regime.get("label"),
            "levels": r.get("levels"),
            "signal": signal.get(t),
            "research": research.get(t),
            "risk": risk.get(t),
        })
    pm = _call(client, config.SONNET_MODEL, _PM_SYS, pm_payload, _PM_TOOL, "desk_pm")

    reviewed = 0
    for r in picks:
        t = r["ticker"]
        s, rs, rk, p = signal.get(t), research.get(t), risk.get(t), pm.get(t)
        if not (s or rs or rk or p):
            continue
        r["desk"] = {
            "decision": (p or {}).get("decision"),
            "size": (p or {}).get("size"),
            "agreement": (p or {}).get("agreement"),
            "rationale": (p or {}).get("rationale"),
            "plan": (p or {}).get("plan"),
            "signal": s,
            "research": rs,
            "risk": rk,
        }
        reviewed += 1

    # Persist verdicts keyed by the pick signature so the next scans with the
    # same picks reuse them instead of paying for the agents again.
    _save_cache(signature, now, {r["ticker"]: r["desk"] for r in picks if r.get("desk")})

    log.info("Desk: reviewed %d/%d picks via LLM (signal=%d research=%d risk=%d pm=%d)",
             reviewed, len(picks), len(signal), len(research), len(risk), len(pm))
    return reviewed
