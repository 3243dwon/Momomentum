"""Yahoo Finance chart-API quotes for A-share / HK / US tickers.

The mom_digest 建议关注 list is A-share (.SH/.SZ) and HK (.HK) names, which the
US-only Alpaca feed (technicals.py) cannot price. To mark those picks to market we
hit Yahoo's public chart endpoint directly via `requests` (already a dependency —
no fragile yfinance). Yahoo serves Shanghai/Shenzhen/HK daily closes + currency.

Symbol mapping (card convention -> Yahoo):
  Shanghai  .SH  -> .SS    601899.SH -> 601899.SS
  Shenzhen  .SZ  -> .SZ    002594.SZ -> 002594.SZ (unchanged)
  Hong Kong .HK  -> .HK    700.HK    -> 0700.HK   (numeric part padded to >=4)
  US        AAPL -> AAPL   (unchanged)

Everything here is best-effort and fail-soft: any network/parse failure returns
None so a missing quote degrades a pick to status='untracked' instead of raising.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

import requests

log = logging.getLogger(__name__)

_HOSTS = ("https://query1.finance.yahoo.com", "https://query2.finance.yahoo.com")
_UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15) AppleWebKit/537.36"}

# A card code looks like "601899.SH", "002594.SZ", "0700.HK", "513180.SH", or a
# bare US ticker. Capture the numeric/alpha root + optional exchange suffix.
_CODE_RE = re.compile(r"^\s*([0-9A-Za-z]+)\s*\.?\s*(SH|SZ|SS|HK)?\s*$", re.IGNORECASE)


def to_yahoo(code: str | None) -> str | None:
    """Normalize a card code to a Yahoo symbol, or None if unparseable."""
    if not code or not isinstance(code, str):
        return None
    m = _CODE_RE.match(code.strip())
    if not m:
        return None
    root, suffix = m.group(1), (m.group(2) or "").upper()
    if suffix in ("SH", "SS"):
        return f"{root}.SS"           # Shanghai
    if suffix == "SZ":
        return f"{root}.SZ"           # Shenzhen
    if suffix == "HK":
        return f"{root.zfill(4)}.HK"  # HK codes are zero-padded to >=4 digits
    # Bare 6-digit A-share code, no suffix — infer the exchange from the prefix.
    # Shanghai 5/6/9 (60x, 688 STAR, 5xx funds/ETFs, 900 B); Shenzhen 0/1/2/3
    # (00x, 30x ChiNext, 15x/16x ETFs, 200 B). The instrument-type guard in
    # is_trackable() catches any mis-inference, so this can't silently misprice.
    if root.isdigit() and len(root) == 6:
        return f"{root}.SS" if root[0] in "569" else f"{root}.SZ"
    # Otherwise treat an all-alpha root as a US ticker.
    if root.isalpha():
        return root.upper()
    return None


def expected_currency(yahoo_sym: str | None) -> str | None:
    """Currency a resolved symbol should report (None = don't enforce, e.g. US)."""
    if not yahoo_sym:
        return None
    if yahoo_sym.endswith((".SS", ".SZ")):
        return "CNY"
    if yahoo_sym.endswith(".HK"):
        return "HKD"
    return None


_TRACKABLE_TYPES = {"EQUITY", "ETF"}


def is_trackable(hist: dict | None, yahoo_sym: str) -> bool:
    """Reject indices / funds / currency pairs and currency mismatches.

    Guards the worst failure mode: a hallucinated-but-parseable code resolving to a
    DIFFERENT instrument that still returns a valid price (e.g. 000001.SS is the SSE
    Composite *index*, not Ping An Bank) — which would otherwise be tracked and
    pollute the hit-rate with a fabricated return.
    """
    if not hist:
        return False
    itype = (hist.get("instrument_type") or "").upper()
    if itype and itype not in _TRACKABLE_TYPES:
        return False
    exp = expected_currency(yahoo_sym)
    cur = (hist.get("currency") or "").upper()
    if exp and cur and cur != exp:
        return False
    return True


def _parse_chart(payload: dict) -> dict | None:
    try:
        res = payload["chart"]["result"][0]
        meta = res["meta"]
        gmtoffset = meta.get("gmtoffset", 0) or 0
        timestamps = res.get("timestamp") or []
        closes_raw = res["indicators"]["quote"][0].get("close") or []
        closes: list[tuple[str, float]] = []
        for ts, c in zip(timestamps, closes_raw):
            if c is None:
                continue
            # Convert epoch to the exchange-local date so day-counting matches the
            # market's trading sessions (avoids off-by-one across the dateline).
            local = datetime.fromtimestamp(ts + gmtoffset, tz=timezone.utc).date()
            closes.append((local.isoformat(), float(c)))
        price = meta.get("regularMarketPrice")
        if price is None and closes:
            price = closes[-1][1]
        if price is None:
            return None
        # Exchange-local "today" so callers can pick a SETTLED close as the entry
        # (avoids anchoring on a still-forming intraday bar during an open session).
        as_of_date = datetime.fromtimestamp(
            datetime.now(timezone.utc).timestamp() + gmtoffset, tz=timezone.utc
        ).date().isoformat()
        return {
            "price": float(price),
            "currency": meta.get("currency"),
            "instrument_type": meta.get("instrumentType"),
            "as_of_date": as_of_date,
            "closes": closes,  # ascending by date
        }
    except (KeyError, IndexError, TypeError, ValueError):
        return None


def fetch_history(yahoo_sym: str, range_: str = "3mo") -> dict | None:
    """{price, currency, closes:[(date_iso, close)...]} or None. Tries both hosts."""
    if not yahoo_sym:
        return None
    for host in _HOSTS:
        url = f"{host}/v8/finance/chart/{yahoo_sym}"
        try:
            r = requests.get(
                url, params={"range": range_, "interval": "1d"}, headers=_UA, timeout=12
            )
            if r.status_code != 200:
                continue
            parsed = _parse_chart(r.json())
            if parsed:
                return parsed
        except (requests.RequestException, ValueError) as e:
            log.debug("Yahoo fetch failed for %s via %s: %s", yahoo_sym, host, e)
            continue
    return None


def close_after(closes: list, entry_date_iso: str, trading_days: int) -> tuple[str, float] | None:
    """The (date, close) that is `trading_days` sessions strictly after entry_date.

    Counts actual trading sessions present in `closes`, so weekends/holidays are
    handled correctly. Returns None if not enough sessions have elapsed yet.
    """
    later = [(d, c) for (d, c) in closes if d > entry_date_iso]
    if len(later) < trading_days:
        return None
    return later[trading_days - 1]
