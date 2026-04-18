"""Build the ticker universe: S&P 500 + NASDAQ 100 + NYSE common stocks.

Liquidity and price floors are applied after yfinance returns price data —
this module just assembles the candidate list.
"""
from __future__ import annotations

import io
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

from scanner import config

log = logging.getLogger(__name__)

UNIVERSE_FILE = config.DATA_DIR / "universe.json"

SP500_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
NDX_URL = "https://en.wikipedia.org/wiki/Nasdaq-100"
NYSE_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt"

NON_COMMON_TERMS = re.compile(
    r"\b(preferred|pfd\.?|warrant|right|unit|notes?|depositary|trust units)\b",
    re.IGNORECASE,
)


def _normalize(ticker: str) -> str:
    """yfinance uses dashes, not dots (e.g. BRK-B not BRK.B)."""
    return ticker.strip().upper().replace(".", "-")


def _valid_ticker(t: str) -> bool:
    if not t or len(t) > 5:
        return False
    if any(c in t for c in "^$."):
        return False
    return bool(re.fullmatch(r"[A-Z0-9\-]+", t))


def fetch_sp500() -> set[str]:
    log.info("Fetching S&P 500 from Wikipedia")
    tables = pd.read_html(SP500_URL, storage_options={"User-Agent": config.USER_AGENT})
    df = tables[0]
    col = next((c for c in df.columns if str(c).lower() in ("symbol", "ticker")), None)
    if col is None:
        raise RuntimeError(f"Could not find ticker column in S&P 500 table: {df.columns}")
    return {_normalize(t) for t in df[col].astype(str) if _valid_ticker(_normalize(t))}


def fetch_ndx() -> set[str]:
    log.info("Fetching NASDAQ-100 from Wikipedia")
    tables = pd.read_html(NDX_URL, storage_options={"User-Agent": config.USER_AGENT})
    for df in tables:
        col = next(
            (c for c in df.columns if str(c).lower() in ("ticker", "symbol")), None
        )
        if col is not None and len(df) > 50:
            return {_normalize(t) for t in df[col].astype(str) if _valid_ticker(_normalize(t))}
    raise RuntimeError("Could not find NASDAQ-100 constituents table")


def fetch_nyse() -> set[str]:
    """NYSE common stocks from NASDAQtrader's `otherlisted.txt` (the canonical feed)."""
    log.info("Fetching NYSE listings from nasdaqtrader.com")
    resp = requests.get(NYSE_URL, headers={"User-Agent": config.USER_AGENT}, timeout=30)
    resp.raise_for_status()
    df = pd.read_csv(io.StringIO(resp.text), sep="|")
    df = df[df["Exchange"] == "N"]
    df = df[df.get("ETF", "N") == "N"]
    df = df[df.get("Test Issue", "N") == "N"]
    df = df[~df["Security Name"].astype(str).str.contains(NON_COMMON_TERMS, na=False)]
    tickers = {_normalize(t) for t in df["ACT Symbol"].astype(str) if _valid_ticker(_normalize(t))}
    return tickers


def build() -> dict:
    sp500 = fetch_sp500()
    ndx = fetch_ndx()
    nyse = fetch_nyse()
    combined = sp500 | ndx | nyse
    payload = {
        "built_at": datetime.now(timezone.utc).isoformat(),
        "sources": {
            "sp500": sorted(sp500),
            "ndx": sorted(ndx),
            "nyse": sorted(nyse),
        },
        "tickers": sorted(combined),
    }
    UNIVERSE_FILE.write_text(json.dumps(payload, indent=2))
    log.info(
        "Universe built: %d S&P500 + %d NDX + %d NYSE = %d unique",
        len(sp500), len(ndx), len(nyse), len(combined),
    )
    return payload


def is_stale(path: Path = UNIVERSE_FILE) -> bool:
    if not path.exists():
        return True
    try:
        built = datetime.fromisoformat(json.loads(path.read_text())["built_at"])
        age = (datetime.now(timezone.utc) - built).days
        return age >= config.UNIVERSE_REBUILD_AFTER_DAYS
    except Exception:
        return True


def load(force_rebuild: bool = False) -> list[str]:
    if force_rebuild or is_stale():
        return build()["tickers"]
    return json.loads(UNIVERSE_FILE.read_text())["tickers"]


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    payload = build()
    print(f"Universe: {len(payload['tickers'])} tickers written to {UNIVERSE_FILE}")
