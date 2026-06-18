"""Portfolio holdings loader.

data/portfolio.json is the one place you hand-edit what you own. The catalyst
calendar (scanner.catalysts) reads it to build your dated add/trim event
calendar at /catalysts. Only `ticker` is required; `shares` and `cost_basis`
are optional and only used to label position size / unrealized P&L.
"""
from __future__ import annotations

import json
import logging

from scanner import config

log = logging.getLogger(__name__)

PORTFOLIO_FILE = config.DATA_DIR / "portfolio.json"


def load_portfolio() -> list[dict]:
    """Return the list of holding dicts ({ticker, shares?, cost_basis?, note?}).
    Empty list when the file is absent or unparseable — every caller treats an
    empty portfolio as "nothing to do", never an error."""
    if not PORTFOLIO_FILE.exists():
        return []
    try:
        data = json.loads(PORTFOLIO_FILE.read_text())
    except Exception as e:
        log.warning("portfolio.json unreadable: %s", e)
        return []

    out: list[dict] = []
    seen: set[str] = set()
    for h in data.get("holdings", []) or []:
        if not isinstance(h, dict):
            continue
        ticker = (h.get("ticker") or "").strip().upper()
        if not ticker or ticker in seen:
            continue
        seen.add(ticker)
        out.append({
            "ticker": ticker,
            "shares": h.get("shares"),
            "cost_basis": h.get("cost_basis"),
            "note": h.get("note"),
        })
    return out


def portfolio_tickers() -> list[str]:
    """Just the tickers, upper-cased and de-duplicated."""
    return [h["ticker"] for h in load_portfolio()]
