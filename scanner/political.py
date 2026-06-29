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
import os
import re
import time
from datetime import datetime, timedelta, timezone

import httpx

from scanner import config

log = logging.getLogger(__name__)

POLITICAL_FILE = config.DATA_DIR / "political.json"

_BASE = "https://financialmodelingprep.com/stable"
_TIMEOUT_SECONDS = 20
_DAYS_KEPT = 60  # surface only roughly the last 2 months of disclosures

# --- SEC EDGAR (DJT / Trump trust insider activity) -------------------------
# The presidency is exempt from STOCK-Act PTRs, so Trump never appears in the
# Congress feed above. The one place his trading shows up publicly is SEC
# Form 4: as a >10% holder of DJT (Trump Media), any transaction by the
# Donald J. Trump Revocable Trust in DJT shares triggers a Form 4 within 2
# business days. That's the only real-time public Trump-trading data.
#
# Reality check from May 2026: the trust holds 114.75M DJT shares (52% of
# the company) and has NOT transacted since the Dec 2024 transfer-in. Other
# DJT insiders (CEO, officers, directors) file routinely. We surface both:
# trust-status + recent issuer-wide Form 4s with Trump-family rows flagged.
_SEC_BASE = "https://data.sec.gov"
_SEC_ARCHIVE = "https://www.sec.gov/Archives/edgar/data"
_DJT_CIK = "0001849635"
_DJT_CIK_NUM = "1849635"  # archive URLs use the unpadded form
_TRUMP_TRUST_CIK = "0002050191"
# SEC requires the User-Agent to identify a contact (name + email). Their
# policy: https://www.sec.gov/os/accessing-edgar-data. Without an email-like
# string the request gets 403. Override via SEC_USER_AGENT env var if you
# want a different contact than the repo owner's commit email.
_SEC_UA = os.environ.get(
    "SEC_USER_AGENT",
    "Momentum-Scanner makutanaka816@gmail.com",
)
_SEC_REQUEST_GAP_SECONDS = 0.12  # ~8 req/s, comfortably under SEC's 10/s cap
_DJT_FORM4_SCAN_LIMIT = 25  # recent Form 4s to surface in the UI
# Known trust holding from the Form 3 filed 2024-12-20. Hardcoded because it
# only updates when the trust transacts (which it hasn't), and parsing the
# Form 3 XML for one number is more code than it's worth.
_TRUMP_TRUST_HOLDING_SHARES = 114_750_000
_TRUMP_TRUST_HOLDING_AS_OF = "2024-12-20"

# Form 4 transaction-code legend. Used for human-readable labels in the UI.
_TX_CODE_LABELS = {
    "P": "Open-market purchase",
    "S": "Open-market sale",
    "A": "Award / grant",
    "M": "Option exercise",
    "F": "Tax withholding",
    "G": "Gift",
    "D": "Conversion",
    "I": "Discretionary",
    "J": "Other",
    "V": "Voluntary report",
    "X": "Option-only exercise",
    "C": "Conversion of derivative",
}


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


def _sec_get(url: str) -> httpx.Response | None:
    """One SEC fetch with the compliance UA. Returns the response or None on
    any failure — every caller treats None as "skip this filing"."""
    try:
        return httpx.get(url, headers={"User-Agent": _SEC_UA}, timeout=_TIMEOUT_SECONDS)
    except Exception as e:
        log.warning("SEC fetch failed for %s: %s", url, e)
        return None


def _is_trump_owner(name: str | None) -> bool:
    return "trump" in (name or "").lower()


def _parse_form4(xml_text: str) -> dict:
    """Extract reporting owners + non-derivative transactions from one Form 4.

    Regex-based on purpose: Form 4 XML namespaces vary across years and the
    field structure is shallow enough that regex is faster + more resilient
    than a namespace-aware ET pass. Each transaction returns
    {date, code, acquired_disposed, shares, price}."""
    owners = [n.strip() for n in re.findall(r"<rptOwnerName>\s*([^<]+?)\s*</rptOwnerName>", xml_text)]

    txs: list[dict] = []
    for m in re.finditer(r"<nonDerivativeTransaction>(.*?)</nonDerivativeTransaction>", xml_text, re.DOTALL):
        block = m.group(1)

        def grab(field: str) -> str | None:
            # Try unwrapped form first: <field>value</field>
            mm = re.search(rf"<{field}>\s*([^<\s][^<]*?)\s*</{field}>", block)
            if mm:
                return mm.group(1).strip()
            # Then the more common <field><value>value</value></field>
            mm = re.search(rf"<{field}>.*?<value>\s*([^<]+?)\s*</value>", block, re.DOTALL)
            return mm.group(1).strip() if mm else None

        txs.append({
            "date": grab("transactionDate"),
            "code": grab("transactionCode"),
            "acquired_disposed": grab("transactionAcquiredDisposedCode"),
            "shares": grab("transactionShares"),
            "price": grab("transactionPricePerShare"),
        })

    return {"owners": owners, "transactions": txs}


def _to_float(s: str | None) -> float | None:
    if s is None:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def fetch_djt_insider_activity() -> dict | None:
    """Pull the most recent DJT Form 4s, parse each, return summary structure
    suitable for the /political page. Returns None when SEC is unreachable."""
    resp = _sec_get(f"{_SEC_BASE}/submissions/CIK{_DJT_CIK}.json")
    if resp is None or resp.status_code != 200:
        log.warning("DJT submissions fetch returned %s", resp.status_code if resp else "no-response")
        return None
    try:
        sub = resp.json()
    except Exception as e:
        log.warning("DJT submissions parse failed: %s", e)
        return None

    issuer = sub.get("name", "Trump Media & Technology Group Corp.")
    tickers = sub.get("tickers") or ["DJT"]
    recent = sub.get("filings", {}).get("recent", {}) or {}
    forms = recent.get("form", [])
    dates = recent.get("filingDate", [])
    accs = recent.get("accessionNumber", [])
    pdocs = recent.get("primaryDocument", [])

    out_txs: list[dict] = []
    trump_filings = 0
    scanned = 0
    for f, dt, acc, pdoc in zip(forms, dates, accs, pdocs):
        if not f.startswith("4"):
            continue
        # Some 425 filings get mis-categorized as form 4 in the index — skip
        # anything whose primary document isn't XML.
        if not pdoc.endswith(".xml"):
            continue
        if scanned >= _DJT_FORM4_SCAN_LIMIT:
            break

        time.sleep(_SEC_REQUEST_GAP_SECONDS)
        acc_clean = acc.replace("-", "")
        # `primaryDocument` is the XSL-rendered HTML path (xslF345X*/...);
        # the raw XML lives at the folder root with the same filename. Strip
        # the prefix so we get parseable data, not the styled view.
        raw_pdoc = pdoc.split("/", 1)[1] if "/" in pdoc else pdoc
        url = f"{_SEC_ARCHIVE}/{_DJT_CIK_NUM}/{acc_clean}/{raw_pdoc}"
        xml_resp = _sec_get(url)
        if xml_resp is None or xml_resp.status_code != 200:
            continue

        parsed = _parse_form4(xml_resp.text)
        is_trump = any(_is_trump_owner(n) for n in parsed["owners"])
        if is_trump:
            trump_filings += 1

        primary_owner = parsed["owners"][0] if parsed["owners"] else None
        filing_link = f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={_DJT_CIK}&type=4&dateb=&owner=include&count=40"
        for tx in parsed["transactions"]:
            out_txs.append({
                "filed_at": dt,
                "accession": acc,
                "owner": primary_owner,
                "is_trump_family": is_trump,
                "transaction_date": tx["date"],
                "code": tx["code"],
                "code_label": _TX_CODE_LABELS.get(tx["code"] or "", tx["code"]),
                "acquired_disposed": tx["acquired_disposed"],
                "shares": _to_float(tx["shares"]),
                "price": _to_float(tx["price"]),
                "link": filing_link,
            })
        scanned += 1

    trust_status = {
        "trust_name": "Donald J. Trump Revocable Trust dated April 7, 2014",
        "trust_cik": _TRUMP_TRUST_CIK,
        "holding_shares_known": _TRUMP_TRUST_HOLDING_SHARES,
        "holding_as_of": _TRUMP_TRUST_HOLDING_AS_OF,
        "trump_family_filings_in_last_scan": trump_filings,
        "form4s_scanned": scanned,
        "note": (
            "Trump is exempt from STOCK-Act periodic transaction reports as "
            "President. His personal trading is not publicly disclosed. The "
            "Trump trust holds 114.75M DJT shares but does not file Form 4s "
            "unless it transacts — which it hasn't, since the Dec 2024 "
            "transfer-in. Trades by Trump-family members (Don Jr, Eric) "
            "appear here when filed and are highlighted."
        ),
    }

    return {
        "issuer": issuer,
        "tickers": tickers,
        "trust_status": trust_status,
        "recent_transactions": out_txs[:60],
    }


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

    Two sources merged:
      1. FMP Senate + House STOCK-Act PTRs (needs FMP_API_KEY, free 250/day)
      2. SEC EDGAR DJT Form 4 filings (no key, free) for Trump-trust activity
         + DJT insider context

    Source #2 always runs because it's free and answers the "where's Trump?"
    question with the only real-time public Trump-related trading data.
    Source #1 gracefully no-ops when FMP_API_KEY is unset.
    """
    now = now or datetime.now(timezone.utc)

    if not _should_refresh(now):
        log.info("Political: cache fresh (< %ds old), skipping fetch",
                 config.POLITICAL_REFRESH_SECONDS)
        try:
            return json.loads(POLITICAL_FILE.read_text())
        except Exception:
            pass  # fall through and re-fetch

    # --- Congress feed (FMP) ---
    trades: list[dict] = []
    if config.FMP_API_KEY:
        senate = _fetch("senate-latest", config.FMP_API_KEY)
        house = _fetch("house-latest", config.FMP_API_KEY)
        for raw in senate:
            norm = _normalize(raw, "senate")
            if norm:
                trades.append(norm)
        for raw in house:
            norm = _normalize(raw, "house")
            if norm:
                trades.append(norm)
        trades = _filter_recent(trades, _DAYS_KEPT)
        trades.sort(key=lambda e: (e.get("filed_at") or e.get("transaction_date") or ""), reverse=True)
    else:
        log.info("Political: FMP_API_KEY unset, skipping Congress feed")

    by_ticker = _bucket_by_ticker(trades)

    # --- Trump / DJT (SEC) — free, no key required ---
    djt = None
    try:
        djt = fetch_djt_insider_activity()
    except Exception as e:
        log.warning("DJT insider fetch raised: %s", e)

    has_congress = bool(trades)
    has_djt = djt is not None
    if has_congress and has_djt:
        status = "ok"
    elif has_djt and not config.FMP_API_KEY:
        status = "djt_only"  # FMP unset but DJT works → render with a note
    elif has_congress:
        status = "ok"
    elif config.FMP_API_KEY or has_djt:
        status = "empty"
    else:
        status = "no_key"

    payload = {
        "generated_at": now.isoformat(),
        "status": status,
        "source": "FMP /stable/{senate,house}-latest + SEC EDGAR Form 4 (DJT)",
        "window_days": _DAYS_KEPT,
        "total_trades": len(trades),
        "unique_tickers": len(by_ticker),
        "trades": trades,
        "by_ticker": by_ticker,
        "djt": djt,  # null if SEC unreachable; structured dict otherwise
    }
    POLITICAL_FILE.write_text(json.dumps(payload, indent=2))
    log.info(
        "Political: wrote %d Congress trades across %d tickers; DJT %s",
        len(trades), len(by_ticker), "ok" if djt else "unavailable",
    )
    return payload
