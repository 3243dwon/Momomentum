"""Political-trades feed.

Pulls recently-disclosed stock trades by US Senators + House members from
Financial Modeling Prep (free tier, 250 req/day, no payment). Normalizes the
two endpoints into one schema, dedups, sorts by filing date, and writes
data/political.json for the web app.

Why FMP and not the gov sites directly?
  - Senate efdsearch.senate.gov gates everything behind a "I agree" cookie
    flow; House clerk.house.gov ships PDFs that need OCR for the older ones.
  - The github.com/timothycarambat/senate-stock-watcher-data scraper, which
    used to be the canonical free source, hasn't shipped since March 2021.
  - capitoltrades.com is the best free UI but they client-side render
    everything (Next.js, /_next/data blocked in robots.txt), and there's no
    official API.
  - FMP costs $0/mo on the free tier and gives clean JSON for both chambers.

Cabinet members (the original "Trump" framing of this request) file under
the Executive Branch on OGE Form 278e — that's annual snapshots, not a
real-time trade feed, and not in any commercial aggregator I could find.
Out of scope for v1.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

from scanner import config

log = logging.getLogger(__name__)

POLITICAL_FILE = config.DATA_DIR / "political.json"

_BASE = "https://financialmodelingprep.com/stable"
_TIMEOUT_SECONDS = 20
_DAYS_KEPT = 60  # surface only roughly the last 2 months of disclosures


def _fetch(endpoint: str, api_key: str) -> list[dict]:
    """One FMP call; returns [] on any failure (network, auth, parse)."""
    url = f"{_BASE}/{endpoint}"
    try:
        resp = httpx.get(url, params={"apikey": api_key}, timeout=_TIMEOUT_SECONDS,
                         headers={"User-Agent": config.USER_AGENT})
    except Exception as e:
        log.warning("Political fetch %s failed: %s", endpoint, e)
        return []
    if resp.status_code != 200:
        log.warning("Political fetch %s returned HTTP %d: %s",
                    endpoint, resp.status_code, resp.text[:200])
        return []
    try:
        data = resp.json()
    except Exception as e:
        log.warning("Political fetch %s returned non-JSON: %s", endpoint, e)
        return []
    if not isinstance(data, list):
        log.warning("Political fetch %s returned unexpected shape: %s",
                    endpoint, type(data).__name__)
        return []
    return data


# FMP field names differ slightly between senate-latest and house-latest, and
# they've changed historically. Be defensive: try the common variants and
# return None when nothing matches.
def _first(*candidates):
    for c in candidates:
        if c not in (None, ""):
            return c
    return None


def _normalize(entry: dict, chamber: str) -> dict | None:
    """One FMP row → our flat shape. Returns None when we can't extract enough
    to display (missing ticker AND missing politician name)."""
    ticker = _first(entry.get("symbol"), entry.get("ticker"))
    politician = _first(
        entry.get("representative"),
        entry.get("senator"),
        entry.get("politician"),
        entry.get("name"),
    )
    if not ticker and not politician:
        return None

    raw_type = (_first(entry.get("type"), entry.get("transaction_type")) or "").lower()
    # Normalize to {buy, sell, exchange}. FMP variants: "Purchase", "Sale",
    # "Sale (Partial)", "Sale (Full)", "Exchange", "purchase", etc.
    if raw_type.startswith("purchase") or raw_type == "buy":
        side = "buy"
    elif raw_type.startswith("sale") or raw_type == "sell":
        side = "sell"
    elif raw_type.startswith("exchange"):
        side = "exchange"
    else:
        side = raw_type or "unknown"

    return {
        "chamber": chamber,
        "politician": politician,
        "ticker": (ticker or "").upper() or None,
        "side": side,
        "amount_band": _first(entry.get("amount"), entry.get("amount_range")),
        "transaction_date": _first(entry.get("transactionDate"), entry.get("transaction_date")),
        "filed_at": _first(entry.get("disclosureDate"), entry.get("filed_at")),
        "owner": _first(entry.get("owner"), entry.get("ownerType")),
        "asset_description": _first(entry.get("assetDescription"), entry.get("asset_description")),
        "link": _first(entry.get("link"), entry.get("filingURL"), entry.get("ptr_link")),
    }


def _filter_recent(entries: list[dict], days: int) -> list[dict]:
    """Keep only entries with a filed_at OR transaction_date inside the
    window. Falsy date fields keep the entry — better to show with a missing
    date than to drop silently."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).date().isoformat()
    out = []
    for e in entries:
        ref = e.get("filed_at") or e.get("transaction_date")
        if ref and ref < cutoff:
            continue
        out.append(e)
    return out


def _bucket_by_ticker(entries: list[dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for e in entries:
        t = e.get("ticker")
        if not t:
            continue
        out.setdefault(t, []).append(e)
    return out


def _should_refresh(now: datetime) -> bool:
    """Honor POLITICAL_REFRESH_SECONDS so we don't burn FMP free-tier quota
    on every scan. If the file is recent enough, skip the fetch."""
    if not POLITICAL_FILE.exists():
        return True
    try:
        data = json.loads(POLITICAL_FILE.read_text())
        gen = data.get("generated_at")
        if not gen:
            return True
        last = datetime.fromisoformat(gen)
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        return (now - last).total_seconds() >= config.POLITICAL_REFRESH_SECONDS
    except Exception:
        return True


def fetch_and_save(now: datetime | None = None) -> dict:
    """Fetch + normalize + write data/political.json. Returns the payload.

    No-op when FMP_API_KEY is unset — writes an empty file once so the web
    app can still render the page with a friendly "set FMP_API_KEY" note.
    """
    now = now or datetime.now(timezone.utc)
    if not config.FMP_API_KEY:
        if not POLITICAL_FILE.exists():
            POLITICAL_FILE.write_text(json.dumps({
                "generated_at": now.isoformat(),
                "status": "no_key",
                "trades": [],
                "by_ticker": {},
            }, indent=2))
            log.info("Political: FMP_API_KEY unset, wrote empty placeholder")
        return {"status": "no_key", "trades": []}

    if not _should_refresh(now):
        log.info("Political: cache fresh (< %ds old), skipping fetch",
                 config.POLITICAL_REFRESH_SECONDS)
        try:
            return json.loads(POLITICAL_FILE.read_text())
        except Exception:
            pass  # fall through and re-fetch

    senate = _fetch("senate-latest", config.FMP_API_KEY)
    house = _fetch("house-latest", config.FMP_API_KEY)

    trades: list[dict] = []
    for raw in senate:
        norm = _normalize(raw, "senate")
        if norm:
            trades.append(norm)
    for raw in house:
        norm = _normalize(raw, "house")
        if norm:
            trades.append(norm)

    trades = _filter_recent(trades, _DAYS_KEPT)
    # Most-recently-filed first; fall back to transaction_date when filed_at
    # missing so the sort still produces a reasonable order.
    trades.sort(key=lambda e: (e.get("filed_at") or e.get("transaction_date") or ""), reverse=True)

    by_ticker = _bucket_by_ticker(trades)

    payload = {
        "generated_at": now.isoformat(),
        "status": "ok" if trades else "empty",
        "source": "financialmodelingprep.com/stable/{senate,house}-latest",
        "window_days": _DAYS_KEPT,
        "total_trades": len(trades),
        "unique_tickers": len(by_ticker),
        "trades": trades,
        "by_ticker": by_ticker,
    }
    POLITICAL_FILE.write_text(json.dumps(payload, indent=2))
    log.info("Political: wrote %d trades across %d tickers", len(trades), len(by_ticker))
    return payload
