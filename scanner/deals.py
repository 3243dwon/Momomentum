"""Deal flow — surfaces ripple events as "deals" and pairs each with its
second-order prediction chain and the grades those calls earned.

A "deal" here is a ripple trigger event: a high-impact catalyst on a popular
stock — an M&A move, a partnership, a supply/foundry win, a capex guide — that
the ripple tier (scanner/llm/ripple.py) reasoned forward from. Each deal carries

  - the primary mover (the trigger ticker) and, when the headline names a second
    US-listed principal, the counterparty (INTC <-> GOOGL), resolved against
    company_aliases.json so "Intel"/"Google" become tickers;
  - the predicted second-order names — each with mechanism, direction,
    confidence, and whether it is priced in yet (the still-actionable ones);
  - the grades those predictions earned, joined from the public ledger by
    (ticker, thesis) because the ledger thesis is the prediction rationale
    verbatim.

data/deals.json is a rolling window: each scan merges the current ripple events
into it (upsert by deal id), refreshes every deal's grades from the latest
ledger, and prunes anything older than the window — so /deals stays populated
even on the (common) scans that surface no new deal.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime, timedelta, timezone

from scanner import config

log = logging.getLogger(__name__)

DEALS_FILE = config.DATA_DIR / "deals.json"
ALIASES_FILE = config.DATA_DIR / "company_aliases.json"
WINDOW_DAYS = 30

_DIR = {"bullish": "long", "bearish": "short"}


# ── counterparty resolution ──────────────────────────────────────────
def _name_to_ticker() -> dict[str, str]:
    """Invert company_aliases into {lowercased name: ticker} for headline scans."""
    try:
        aliases = json.loads(ALIASES_FILE.read_text()).get("aliases", {})
    except (OSError, json.JSONDecodeError):
        return {}
    out: dict[str, str] = {}
    for ticker, names in aliases.items():
        for name in names:
            out[name.lower()] = ticker
    return out


def _counterparty(headline: str, primary: str, name_map: dict[str, str]) -> str | None:
    """The other listed principal named in the deal headline, if any.

    Matches company names on word boundaries (case-insensitive) so "Intel wins
    Google foundry deal" with primary INTC yields GOOGL. Returns the first
    distinct ticker found; deal headlines rarely name a third principal.
    """
    h = headline.lower()
    for name, ticker in name_map.items():
        if ticker == primary:
            continue
        if re.search(rf"\b{re.escape(name)}\b", h):
            return ticker
    return None


# ── grade join ───────────────────────────────────────────────────────
def _grade_index(ledger: dict | None) -> dict[tuple[str, str], dict]:
    """Index graded ripple predictions by (ticker, thesis) for the join."""
    idx: dict[tuple[str, str], dict] = {}
    for e in (ledger or {}).get("entries", []):
        if e.get("kind") != "prediction":
            continue
        idx[(e.get("ticker", ""), (e.get("thesis") or "").strip())] = e
    return idx


# ── build ────────────────────────────────────────────────────────────
def _deal_id(primary: str, headline: str, ts: str) -> str:
    raw = f"{primary}|{headline}|{ts[:10]}"
    return hashlib.sha1(raw.encode()).hexdigest()[:12]


def _build_one(event: dict, preds: list[dict], grades: dict[tuple[str, str], dict],
               name_map: dict[str, str]) -> dict | None:
    """One deal: the event plus its prediction chain with joined grades."""
    headline = (event.get("event_summary") or "").strip()
    if not headline or not preds:
        return None
    primary = preds[0].get("trigger_ticker") or ""
    ts = min((p.get("created_at") or "" for p in preds), default="") or _now_iso()

    chain = []
    graded = hit = 0
    for p in preds:
        rationale = (p.get("rationale") or "").strip()
        g = grades.get((p.get("ticker", ""), rationale))
        outcomes = g.get("outcomes") if g else {"1d": None, "3d": None, "5d": None}
        status = g.get("status", "pending") if g else "pending"
        if status in ("hit", "miss"):
            graded += 1
            hit += status == "hit"
        chain.append({
            "ticker": p.get("ticker"),
            "direction": _DIR.get(p.get("direction", ""), "long"),
            "mechanism": rationale,
            "confidence": p.get("confidence"),
            "horizon": p.get("horizon"),
            "priced_in": p.get("priced_in"),
            "outcomes": outcomes,
            "status": status,
        })

    return {
        "id": _deal_id(primary, headline, ts),
        "ts": ts,
        "primary_ticker": primary,
        "counterparty": _counterparty(headline, primary, name_map),
        "headline": headline,
        "drivers": event.get("primary_drivers", []),
        "news_url": next((p.get("news_url") for p in preds if p.get("news_url")), None),
        "predictions": chain,
        "stats": {"calls": len(chain), "graded": graded, "hit": hit},
    }


def build_deals(predictions_data: dict | None, ledger: dict | None) -> list[dict]:
    """Build deals from one scan's ripple events + predictions, grades joined."""
    if not predictions_data:
        return []
    events = predictions_data.get("events", [])
    preds = predictions_data.get("predictions", [])
    if not events or not preds:
        return []
    grades = _grade_index(ledger)
    name_map = _name_to_ticker()

    # Group predictions by their trigger event summary (the ripple writes one
    # event per trigger and tags every prediction with that event_summary).
    by_event: dict[str, list[dict]] = {}
    for p in preds:
        by_event.setdefault((p.get("event_summary") or "").strip(), []).append(p)

    deals = []
    for event in events:
        summary = (event.get("event_summary") or "").strip()
        deal = _build_one(event, by_event.get(summary, []), grades, name_map)
        if deal:
            deals.append(deal)
    return deals


# ── rolling persistence ──────────────────────────────────────────────
def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _prune(deals: list[dict], now: datetime, window_days: int) -> list[dict]:
    cutoff = now - timedelta(days=window_days)
    kept = []
    for d in deals:
        try:
            ts = datetime.fromisoformat(d["ts"])
        except (KeyError, ValueError):
            continue
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        if ts >= cutoff:
            kept.append(d)
    return kept


def write_deals(now: datetime, predictions_data: dict | None, ledger: dict | None,
                window_days: int = WINDOW_DAYS) -> dict:
    """Merge this scan's deals into the rolling data/deals.json and write it.

    Existing deals are kept (identity by id) but their grades are refreshed from
    the current ledger every scan, so a call flips pending -> hit/miss in place
    as outcomes land. Deals older than the window are pruned.
    """
    try:
        existing = json.loads(DEALS_FILE.read_text()).get("deals", [])
    except (OSError, json.JSONDecodeError):
        existing = []

    fresh = build_deals(predictions_data, ledger)
    fresh_by_id = {d["id"]: d for d in fresh}

    # Re-grade existing deals against the current ledger so old calls update.
    grades = _grade_index(ledger)
    merged: dict[str, dict] = {}
    for d in existing:
        if d["id"] in fresh_by_id:
            continue  # the fresh build supersedes it (same identity, newer join)
        merged[d["id"]] = _regrade(d, grades)
    for d in fresh:
        merged[d["id"]] = d

    deals = _prune(list(merged.values()), now, window_days)
    deals.sort(key=lambda d: d.get("ts", ""), reverse=True)

    payload = {
        "generated_at": now.isoformat(),
        "window_days": window_days,
        "deal_count": len(deals),
        "deals": deals,
    }
    DEALS_FILE.write_text(json.dumps(payload, indent=1))
    log.info("Wrote deals.json: %d deals (%dd window)", len(deals), window_days)
    return payload


def _regrade(deal: dict, grades: dict[tuple[str, str], dict]) -> dict:
    """Refresh a stored deal's prediction outcomes from the current ledger."""
    graded = hit = 0
    for p in deal.get("predictions", []):
        g = grades.get((p.get("ticker", ""), (p.get("mechanism") or "").strip()))
        if g:
            p["outcomes"] = g.get("outcomes", p.get("outcomes"))
            p["status"] = g.get("status", p.get("status"))
        if p.get("status") in ("hit", "miss"):
            graded += 1
            hit += p.get("status") == "hit"
    deal["stats"] = {"calls": len(deal.get("predictions", [])), "graded": graded, "hit": hit}
    return deal
