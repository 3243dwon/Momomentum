"""Portfolio catalyst calendar.

For each holding in data/portfolio.json, surface the next dated catalysts —
earnings, ex-dividend — plus a US macro calendar (FOMC / CPI / jobs / PCE) and
the quarterly triple-witching, so the /catalysts page and Feishu can flag the
add/trim windows ahead of time.

Dates come from Financial Modeling Prep (the same free key the political feed
uses; ~2 calls per holding + 1 macro call, throttled to twice a day, stays far
under the 250/day cap). Witching is computed locally. An Opus pass
(scanner.llm.catalyst_notes) then writes a per-holding "trim/add read".

Honesty: forward earnings dates from FMP are aggregator ESTIMATES, not company-
confirmed — they're labeled "estimated". Declared dividends, scheduled macro
prints, and witching are "confirmed". Not investment advice.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from datetime import date, datetime, timedelta, timezone

import httpx

from scanner import config, portfolio
from scanner.llm import catalyst_notes

log = logging.getLogger(__name__)

CATALYST_FILE = config.DATA_DIR / "catalysts.json"
NOTIFIED_FILE = config.CACHE_DIR / "catalyst_notified.json"

_BASE = "https://financialmodelingprep.com/stable"
_TIMEOUT_SECONDS = 20
_SITE_URL = os.environ.get("SITE_URL", "https://momomentum.vercel.app")
_SOURCE = "FMP /stable/{earnings,dividends,economic-calendar} + computed triple-witching"

# US macro events worth surfacing for an equity book. Matched case-insensitively
# against FMP's economic-calendar `event` names; everything else is dropped so
# the macro list stays a tight, decision-relevant set rather than every print.
_MACRO_PATTERNS = re.compile(
    r"(fomc|federal funds|fed interest rate|interest rate decision|"
    r"\bcpi\b|consumer price|\bpce\b|personal consumption|core inflation|"
    r"nonfarm|non-farm|employment situation|unemployment rate|"
    r"\bgdp\b|jobs report|jolts)",
    re.IGNORECASE,
)
_MACRO_MAX = 24
_US_COUNTRIES = {"US", "USA", "USD", "UNITED STATES"}


# --- FMP fetch (defensive, mirrors scanner.political) -----------------------

def _fetch(endpoint: str, params: dict) -> list[dict]:
    """One FMP call; returns [] on any failure (no key, network, auth, parse)."""
    if not config.FMP_API_KEY:
        return []
    url = f"{_BASE}/{endpoint}"
    try:
        resp = httpx.get(
            url,
            params={**params, "apikey": config.FMP_API_KEY},
            timeout=_TIMEOUT_SECONDS,
            headers={"User-Agent": config.USER_AGENT},
        )
    except Exception as e:
        log.warning("Catalyst fetch %s failed: %s", endpoint, e)
        return []
    if resp.status_code != 200:
        log.warning("Catalyst fetch %s returned HTTP %d: %s", endpoint, resp.status_code, resp.text[:160])
        return []
    try:
        data = resp.json()
    except Exception:
        return []
    return data if isinstance(data, list) else []


def _first(*candidates):
    for c in candidates:
        if c not in (None, ""):
            return c
    return None


def _as_date(value) -> date | None:
    """FMP dates arrive as 'YYYY-MM-DD' or 'YYYY-MM-DD HH:MM:SS'. Take the date."""
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


# --- Triple witching (deterministic, no API) --------------------------------

def _third_friday(year: int, month: int) -> date:
    first = date(year, month, 1)
    offset = (4 - first.weekday()) % 7  # weekday(): Mon=0 .. Fri=4
    return first + timedelta(days=offset + 14)


def _witching_events(today: date, horizon_end: date) -> list[dict]:
    out: list[dict] = []
    for year in (today.year, today.year + 1):
        for month in (3, 6, 9, 12):
            wd = _third_friday(year, month)
            if today <= wd <= horizon_end:
                out.append({
                    "type": "witching",
                    "label": "Triple witching",
                    "date": wd.isoformat(),
                    "impact": "medium",
                    "confidence": "confirmed",
                    "detail": ("Quarterly simultaneous expiry of index futures, index "
                               "options & single-stock options — volume/volatility spike "
                               "and pinning risk in the most options-heavy names."),
                    "source": "computed",
                })
    return out


# --- Per-holding fetchers ---------------------------------------------------

def _next_earnings(ticker: str, today: date) -> dict | None:
    rows = _fetch("earnings", {"symbol": ticker, "limit": 12})
    upcoming = [
        (d, r)
        for r in rows
        if (d := _as_date(_first(r.get("date"), r.get("earningsDate")))) and d >= today
    ]
    if not upcoming:
        return None
    upcoming.sort(key=lambda x: x[0])
    d, r = upcoming[0]
    when = (_first(r.get("time")) or "").lower()
    when_label = {"bmo": "before open", "amc": "after close"}.get(when)
    detail_bits = []
    if when_label:
        detail_bits.append(when_label)
    eps_est = r.get("epsEstimated")
    if eps_est not in (None, ""):
        try:
            detail_bits.append(f"EPS est {float(eps_est):.2f}")
        except (TypeError, ValueError):
            pass
    return {
        "type": "earnings",
        "label": "Next earnings (est.)",
        "date": d.isoformat(),
        "impact": "high",
        "confidence": "estimated",  # FMP forward dates are aggregator estimates
        "detail": " · ".join(detail_bits) or "Quarterly results",
        "source": "fmp:earnings",
    }


def _next_dividend(ticker: str, today: date) -> dict | None:
    rows = _fetch("dividends", {"symbol": ticker, "limit": 12})
    upcoming = [
        (ex, r)
        for r in rows
        if (ex := _as_date(_first(r.get("date"), r.get("exDividendDate"), r.get("recordDate")))) and ex >= today
    ]
    if not upcoming:
        return None
    upcoming.sort(key=lambda x: x[0])
    ex, r = upcoming[0]
    amt = _first(r.get("dividend"), r.get("adjDividend"))
    label = "Ex-dividend"
    if amt not in (None, ""):
        try:
            label = f"Ex-dividend (${float(amt):.2f})"
        except (TypeError, ValueError):
            pass
    detail_bits = []
    pay = _as_date(_first(r.get("paymentDate")))
    if pay:
        detail_bits.append(f"pay {pay.isoformat()}")
    return {
        "type": "ex_dividend",
        "label": label,
        "date": ex.isoformat(),
        "impact": "low",
        "confidence": "confirmed",  # declared dividends only
        "detail": " · ".join(detail_bits) or "Hold through the ex-date to receive the payout.",
        "source": "fmp:dividends",
    }


def _macro_events(today: date, horizon_end: date) -> list[dict]:
    rows = _fetch("economic-calendar", {"from": today.isoformat(), "to": horizon_end.isoformat()})
    seen: set[tuple] = set()
    out: list[dict] = []
    for r in rows:
        country = (_first(r.get("country"), r.get("countryCode")) or "").upper()
        if country not in _US_COUNTRIES:
            continue
        name = _first(r.get("event")) or ""
        if not _MACRO_PATTERNS.search(name):
            continue
        d = _as_date(_first(r.get("date")))
        if not d or not (today <= d <= horizon_end):
            continue
        key = (d.isoformat(), name.lower())
        if key in seen:
            continue
        seen.add(key)
        detail_bits = []
        est = _first(r.get("estimate"))
        prev = _first(r.get("previous"))
        if est not in (None, ""):
            detail_bits.append(f"est {est}")
        if prev not in (None, ""):
            detail_bits.append(f"prev {prev}")
        out.append({
            "type": "macro",
            "label": name,
            "date": d.isoformat(),
            "impact": (_first(r.get("impact")) or "high").lower(),
            "confidence": "confirmed",
            "detail": " · ".join(str(b) for b in detail_bits),
            "source": "fmp:econ",
        })
    out.sort(key=lambda e: e["date"])
    return out[:_MACRO_MAX]


# --- Build ------------------------------------------------------------------

def _event_id(ticker: str, typ: str, key: str) -> str:
    return hashlib.sha1(f"{ticker}|{typ}|{key}".encode()).hexdigest()[:12]


def _days_until(iso_date: str, today: date) -> int:
    return (date.fromisoformat(iso_date) - today).days


def build(holdings: list[dict], now: datetime) -> dict:
    today = now.date()
    horizon_end = today + timedelta(days=config.CATALYST_HORIZON_DAYS)

    by_ticker: dict[str, list[dict]] = {}
    for h in holdings:
        t = h["ticker"]
        events: list[dict] = []
        for fetch_fn in (_next_earnings, _next_dividend):
            try:
                ev = fetch_fn(t, today)
            except Exception as e:
                log.warning("Catalyst %s for %s raised: %s", fetch_fn.__name__, t, e)
                ev = None
            if ev:
                ev["ticker"] = t
                ev["id"] = _event_id(t, ev["type"], ev["date"])
                ev["days_until"] = _days_until(ev["date"], today)
                events.append(ev)
        events.sort(key=lambda e: e["date"])
        by_ticker[t] = events

    macro = _witching_events(today, horizon_end) + _macro_events(today, horizon_end)
    for ev in macro:
        ev["id"] = _event_id("MACRO", ev["type"], ev["date"] + ev["label"][:12])
        ev["days_until"] = _days_until(ev["date"], today)
    macro.sort(key=lambda e: e["date"])

    ticker_count = sum(len(v) for v in by_ticker.values())
    return {
        "by_ticker": by_ticker,
        "macro": macro,
        "catalyst_count": ticker_count + len(macro),
        "ticker_event_count": ticker_count,
    }


def _should_refresh(now: datetime) -> bool:
    """Honor CATALYST_REFRESH_SECONDS so we don't burn FMP quota or re-run Opus
    on every scan. If catalysts.json is recent enough, skip the whole pass."""
    if not CATALYST_FILE.exists():
        return True
    try:
        gen = json.loads(CATALYST_FILE.read_text()).get("generated_at")
        if not gen:
            return True
        last = datetime.fromisoformat(gen)
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        ref = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
        return (ref - last).total_seconds() >= config.CATALYST_REFRESH_SECONDS
    except Exception:
        return True


def fetch_and_save(client=None, rows=None, syntheses=None, now=None) -> dict | None:
    """Build + write data/catalysts.json. Returns the payload (fresh or cached).

    Throttled to CATALYST_REFRESH_SECONDS: on a cache-fresh scan we return the
    existing payload untouched (so the Feishu notifier can still run off it)
    without hitting FMP or Opus. Fail-soft — a raise here never blocks a scan.
    """
    if not config.CATALYST_ENABLED:
        return None
    now = now or datetime.now(config.MARKET_TZ)
    holdings = portfolio.load_portfolio()

    if not _should_refresh(now):
        log.info("Catalyst: cache fresh (< %ds), skipping FMP + notes", config.CATALYST_REFRESH_SECONDS)
        try:
            return json.loads(CATALYST_FILE.read_text())
        except Exception:
            pass  # unreadable cache → fall through and rebuild

    if not holdings:
        payload = {
            "generated_at": now.isoformat(),
            "status": "no_portfolio",
            "source": _SOURCE,
            "horizon_days": config.CATALYST_HORIZON_DAYS,
            "portfolio_count": 0,
            "holdings": [],
            "catalyst_count": 0,
            "by_ticker": {},
            "macro": _witching_for_macro_only(now),
            "notes_by_ticker": {},
            "disclaimer": _DISCLAIMER,
        }
        CATALYST_FILE.write_text(json.dumps(payload, indent=2))
        log.info("Catalyst: portfolio.json empty; wrote placeholder")
        return payload

    built = build(holdings, now)

    # Per-holding Opus trim/add read. Additive + fail-soft: on any error the
    # calendar still ships, just without the narrative reads.
    notes: dict[str, dict] = {}
    if client is not None:
        try:
            notes = catalyst_notes.generate(
                holdings,
                built["by_ticker"],
                built["macro"],
                rows_by_ticker={r["ticker"]: r for r in (rows or [])},
                syntheses=syntheses or {},
                client=client,
            )
        except Exception as e:
            log.warning("Catalyst notes raised: %s", e)

    payload = {
        "generated_at": now.isoformat(),
        "status": "ok" if config.FMP_API_KEY else "no_key",
        "source": _SOURCE,
        "horizon_days": config.CATALYST_HORIZON_DAYS,
        "portfolio_count": len(holdings),
        "holdings": holdings,
        "catalyst_count": built["catalyst_count"],
        "by_ticker": built["by_ticker"],
        "macro": built["macro"],
        "notes_by_ticker": notes,
        "notes_generated_at": now.isoformat() if notes else None,
        "disclaimer": _DISCLAIMER,
    }
    CATALYST_FILE.write_text(json.dumps(payload, indent=2))
    log.info(
        "Catalyst: wrote %d holding events across %d names (+%d macro), %d notes [%s]",
        built["ticker_event_count"], len(holdings), len(built["macro"]),
        len(notes), payload["status"],
    )
    return payload


_DISCLAIMER = (
    "Forward earnings dates are third-party aggregator estimates, not company-"
    "confirmed — confirm against the company's IR release (~2 weeks ahead). "
    "Dividends, macro prints and witching are scheduled/confirmed. "
    "Not investment advice."
)


def _witching_for_macro_only(now: datetime) -> list[dict]:
    """Macro calendar with no portfolio — still useful, so include witching."""
    today = now.date()
    macro = _witching_events(today, today + timedelta(days=config.CATALYST_HORIZON_DAYS))
    for ev in macro:
        ev["id"] = _event_id("MACRO", ev["type"], ev["date"] + ev["label"][:12])
        ev["days_until"] = _days_until(ev["date"], today)
    return macro


# --- Feishu notify ----------------------------------------------------------

def _load_notified() -> dict:
    if not NOTIFIED_FILE.exists():
        return {}
    try:
        return json.loads(NOTIFIED_FILE.read_text())
    except Exception:
        return {}


def _save_notified(state: dict) -> None:
    cutoff = datetime.now(timezone.utc) - timedelta(days=60)
    pruned: dict[str, str] = {}
    for k, v in state.items():
        try:
            ts = datetime.fromisoformat(v)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if ts >= cutoff:
                pruned[k] = v
        except Exception:
            continue
    NOTIFIED_FILE.write_text(json.dumps(pruned, indent=2))


def notify_due_catalysts(payload: dict | None, now: datetime) -> int:
    """Push a single Feishu card for any portfolio catalyst now within
    CATALYST_NOTIFY_DAYS that hasn't been pinged yet. Deduped via a cache-side
    notified-set so each event fires at most once. Returns the count pushed."""
    from scanner.alerts import feishu

    if not payload or payload.get("status") == "no_portfolio":
        return 0

    notified = _load_notified()
    now_iso = (now if now.tzinfo else now.replace(tzinfo=timezone.utc)).isoformat()

    due: list[tuple[str, dict, str]] = []
    for ticker, events in (payload.get("by_ticker") or {}).items():
        for ev in events:
            du = ev.get("days_until")
            if du is None or du < 0 or du > config.CATALYST_NOTIFY_DAYS:
                continue
            key = f"{ev['id']}:soon"
            if key in notified:
                continue
            due.append((ticker, ev, key))

    if not due:
        return 0

    due.sort(key=lambda x: x[1]["days_until"])

    def when_label(du: int) -> str:
        return "today" if du == 0 else "tomorrow" if du == 1 else f"in {du}d"

    lines = []
    for ticker, ev, _ in due:
        est = " · est." if ev.get("confidence") == "estimated" else ""
        lines.append(
            f"**{ticker}** {ev['label']} — {when_label(ev['days_until'])} "
            f"({ev['date']}){est} [→]({_SITE_URL}/t/{ticker})"
        )

    lead_ticker, lead_ev, _ = due[0]
    title = f"🗓 {lead_ticker} {lead_ev['label']} {when_label(lead_ev['days_until'])}"
    if len(due) > 1:
        title += f" · +{len(due) - 1} more"
    body = "\n".join(lines)
    body += f"\n\n_Add/trim windows · [full calendar →]({_SITE_URL}/catalysts)_"

    alert = {
        "type": "catalyst",
        "title": title[:60],
        "body_md": body,
        "link": f"{_SITE_URL}/catalysts",
    }
    if not feishu.send(alert):
        return 0

    for _, _, key in due:
        notified[key] = now_iso
    _save_notified(notified)
    log.info("Catalyst: pushed %d due catalyst(s) to Feishu", len(due))
    return len(due)
