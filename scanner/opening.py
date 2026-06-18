"""Opening catch-list — the early-entry tier.

The rest of the scanner ranks by what already moved; you see the winners after
the close, with a LATE flag, once the momentum is spent. This tier runs the
reasoning the other way: once per trading day, on the first regular-hours scan
after the 09:30 open (~10:00 ET), it flags liquid names that gapped overnight
and are STILL HOLDING above (long) / below (short) VWAP on the opening range —
a confirmed-continuation list, price-stamped at the live snapshot price, scored
by-close / +1d / +3d so it proves itself instead of asking to be trusted.

Honest about the data (see docs + technicals.py): the feed is IEX and historical
bars carry a ~20-min lag, so a 10:00 ET scan reads ~09:40 structure. That lag is
an asset here, not a bug — a gap still holding 30 minutes in is exactly the
signal we want, and the unclamped snapshot (live_price / gap_pct) gives a real,
actionable entry price. It works on liquid large-caps; thin IEX coverage makes
small-caps unreliable, so a hard liquidity gate excludes them.

Accountability is built in from day one:
  * every candidate is logged with price_at_entry = the LIVE price (not
    yesterday's close, which every other log stamps);
  * the names that were ELIGIBLE (gapped + liquid) but did NOT fire the
    VWAP-hold gate are logged too, as a control cohort — so the stats can answer
    the only question that matters: does the signal beat just buying any gapper?
  * outcomes are graded against the SETTLED daily close, not a live snapshot.

Pure candidate logic (build_catch_list and its helpers) is stdlib-only and
deterministic so it unit-tests without Alpaca. Disable the whole tier with
OPENING_ENABLED=0.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

from scanner import config, levels, performance, technicals, windows

log = logging.getLogger(__name__)

EARLY_ENTRY_FILE = config.DATA_DIR / "early_entry.json"  # committed; the catch list
# Cap on the control cohort logged per scan — bounds the daily-bar grading cost.
MAX_CONTROL_COHORT = 30


# --- pure candidate logic ----------------------------------------------------

def _gap_band(gap: float | None) -> str:
    a = abs(gap or 0)
    if a >= 8:
        return "8+"
    if a >= 5:
        return "5-8"
    return "3-5"


def _liquid(row: dict) -> bool:
    """IEX prints densely enough to trust the reads only on liquid names."""
    av = row.get("avg_volume_20d") or 0
    mem = set(row.get("membership") or [])
    return av >= config.OPENING_MIN_AVG_VOL or bool(mem & {"sp500", "ndx"})


def _rvol_tod(intraday: dict, avg_volume_20d: float | None) -> float | None:
    """Time-of-day relative volume: cumulative session volume so far ÷ the
    pro-rata share of the 20-day average expected by this point in the session.
    Rough (IEX is fractional volume), so it's a soft rank input, never a gate."""
    sv = intraday.get("session_vol")
    bars = intraday.get("bars") or 0
    if not sv or not avg_volume_20d or bars <= 0:
        return None
    minutes = bars * 5  # 5-min bars; the -20min lag keeps this small near the open
    expected = avg_volume_20d * (minutes / 390.0)  # 390 min in an RTH session
    if expected <= 0:
        return None
    return sv / expected


def _eligible(row: dict) -> str | None:
    """A row is an eligible candidate (gapped + liquid + priced) → return its
    gap-implied direction ('long'/'short'); else None."""
    snap = row.get("snapshot") or {}
    gap = snap.get("gap_pct")
    live = snap.get("live_price")
    if gap is None or live is None:
        return None
    if live < config.MIN_PRICE:
        return None
    if abs(gap) < config.OPENING_MIN_GAP_PCT:
        return None
    if not _liquid(row):
        return None
    return "long" if gap > 0 else "short"


def _fires(row: dict, direction: str, regime: dict | None) -> tuple[bool, float | None]:
    """Does an eligible row fire the actionable gate? Returns (fired, vwap_dist).

    Fires when the gap is HOLDING near VWAP (above for long / below for short,
    within OPENING_MAX_VWAP_DIST_PCT), hasn't given back > OPENING_MAX_GIVEBACK_PCT
    from its opening extreme, and isn't already 'stretched'. Shorts are suppressed
    in a confirmed bull regime (mirrors recommend.py's default)."""
    intr = row.get("intraday") or {}
    snap = row.get("snapshot") or {}
    live = snap.get("live_price")
    vwap = intr.get("vwap")
    bars = intr.get("bars") or 0
    if vwap is None or live is None or vwap <= 0 or bars < 1:
        return False, None

    dist = (live - vwap) / vwap * 100.0  # signed: +above / -below VWAP
    above = intr.get("above_vwap")

    if direction == "long":
        if above is not True or dist < 0 or dist > config.OPENING_MAX_VWAP_DIST_PCT:
            return False, dist
        hod = intr.get("hod")
        if hod and hod > 0 and (hod - live) / hod * 100.0 > config.OPENING_MAX_GIVEBACK_PCT:
            return False, dist
    else:
        if above is not False or dist > 0 or -dist > config.OPENING_MAX_VWAP_DIST_PCT:
            return False, dist
        lod = intr.get("lod")
        if lod and lod > 0 and (live - lod) / lod * 100.0 > config.OPENING_MAX_GIVEBACK_PCT:
            return False, dist

    if row.get("caution_level") == "stretched":
        return False, dist
    if direction == "short" and regime and regime.get("spy_above_50d") is True:
        return False, dist
    return True, dist


def _score(gap: float | None, rvol_tod: float | None, dist: float | None, row: dict) -> float:
    """Rank score: gap strength + time-of-day volume (the leading edge) +
    proximity to VWAP (closer = less chase). Caution shaves points."""
    s = min(abs(gap or 0), 12.0)                       # gap strength, capped
    if rvol_tod is not None:
        s += min(rvol_tod, 5.0) * 2.0                  # volume is the real edge
    if dist is not None:
        s += max(0.0, 3.0 - abs(dist))                 # entering near VWAP scores
    if row.get("caution_level") == "caution":
        s -= 2.0
    return round(s, 2)


def _reasons(gap, direction, rvol_tod, give, dist) -> list[str]:
    out = [f"{gap:+.1f}% gap"]
    out.append("holding above VWAP" if direction == "long" else "holding below VWAP")
    if rvol_tod is not None:
        out.append(f"{rvol_tod:.1f}x vol (time-of-day)")
    if dist is not None:
        out.append(f"{dist:+.1f}% vs VWAP")
    if give is not None:
        out.append(f"{give:.1f}% off {'HOD' if direction == 'long' else 'LOD'}")
    return out


def _build_candidate(row: dict, direction: str, dist: float | None, fired: bool) -> dict:
    snap = row.get("snapshot") or {}
    intr = row.get("intraday") or {}
    live = snap.get("live_price")
    gap = snap.get("gap_pct")
    av = row.get("avg_volume_20d")
    rvol_tod = _rvol_tod(intr, av)

    # Trade levels off the LIVE entry price — not row['price'] (yesterday's
    # close). compute_levels lifts the stop to VWAP when VWAP is the nearer
    # floor, which is exactly the gap-and-hold stop we want.
    lv_row = dict(row)
    lv_row["price"] = live
    lv = levels.compute_levels(lv_row, direction)

    hod, lod = intr.get("hod"), intr.get("lod")
    give = None
    if direction == "long" and hod and hod > 0 and live:
        give = round((hod - live) / hod * 100.0, 2)
    elif direction == "short" and lod and lod > 0 and live:
        give = round((live - lod) / lod * 100.0, 2)

    return {
        "ticker": row["ticker"],
        "direction": direction,
        "fired": fired,
        "gap_pct": gap,
        "gap_band": _gap_band(gap),
        "live_price": live,
        "prev_close": snap.get("prev_close"),
        "vwap": intr.get("vwap"),
        "above_vwap": intr.get("above_vwap"),
        "vwap_dist_pct": round(dist, 2) if dist is not None else None,
        "hod": hod,
        "lod": lod,
        "giveback_pct": give,
        "session_vol": intr.get("session_vol"),
        "rvol_tod": round(rvol_tod, 2) if rvol_tod is not None else None,
        "bars": intr.get("bars"),
        "avg_volume_20d": av,
        "membership": row.get("membership") or [],
        "rsi_14": row.get("rsi_14"),
        "caution_level": row.get("caution_level"),
        "score": _score(gap, rvol_tod, dist, row),
        "reasons": _reasons(gap, direction, rvol_tod, give, dist),
        "levels": lv,
    }


def build_catch_list(enriched_rows: list[dict], regime: dict | None,
                     now: datetime, window) -> dict:
    """Pure: rank gappers into a fired catch list + an eligible-but-passed
    control cohort. `_has_intraday` tells the caller whether opening bars were
    available yet (if not, the caller should retry on the next scan rather than
    burning the once-a-day slot on empty data)."""
    has_intraday = any((r.get("intraday") or {}).get("bars") for r in enriched_rows)

    fired_long: list[dict] = []
    fired_short: list[dict] = []
    passed: list[dict] = []
    for row in enriched_rows:
        direction = _eligible(row)
        if not direction:
            continue
        ok, dist = _fires(row, direction, regime)
        cand = _build_candidate(row, direction, dist, ok)
        if ok:
            (fired_long if direction == "long" else fired_short).append(cand)
        else:
            passed.append(cand)

    fired_long.sort(key=lambda c: -c["score"])
    fired_short.sort(key=lambda c: -c["score"])
    fired = fired_long[: config.OPENING_MAX_PER_SIDE] + fired_short[: config.OPENING_MAX_PER_SIDE]
    passed.sort(key=lambda c: -c["score"])
    passed = passed[:MAX_CONTROL_COHORT]

    et = now.astimezone(config.MARKET_TZ)
    return {
        "generated_at": et.isoformat(),
        "trading_date": et.date().isoformat(),
        "window": getattr(window, "value", str(window)),
        "as_of_note": (
            "First RTH scan after the open (~10:00 ET). IEX feed + ~20-min "
            "historical-bar lag: live price is real-time, the VWAP/opening-range "
            "structure is ~09:40. Liquid names only. Confirmed continuation, not "
            "the opening tick. Not investment advice."
        ),
        "fired": fired,
        "eligible_passed": passed,
        "counts": {"fired": len(fired), "eligible_passed": len(passed)},
        "_has_intraday": has_intraday,
    }


# --- side effects: write, log, guard -----------------------------------------

def write_catch_list(payload: dict, now: datetime) -> None:
    """Write data/early_entry.json (committed) — strips the internal flag."""
    out = {k: v for k, v in payload.items() if not k.startswith("_")}
    EARLY_ENTRY_FILE.write_text(json.dumps(out, indent=2))
    log.info(
        "Wrote early_entry.json: %d fired, %d eligible-passed (control)",
        payload.get("counts", {}).get("fired", 0),
        payload.get("counts", {}).get("eligible_passed", 0),
    )


def log_catch_list(payload: dict, now: datetime, regime: dict | None = None) -> None:
    """Append every candidate (fired AND control) to the early-entry log with
    price_at_entry = the LIVE price, so by-close/+1d/+3d outcomes can be graded
    and the fired-vs-control edge computed."""
    items = list(payload.get("fired", [])) + list(payload.get("eligible_passed", []))
    ts = now.astimezone(timezone.utc).isoformat()
    new_entries = []
    for c in items:
        if c.get("live_price") is None:
            continue
        entry = {
            "ts": ts,
            "ticker": c["ticker"],
            "direction": c["direction"],
            "fired": bool(c.get("fired")),
            "price_at_entry": c["live_price"],
            "gap_pct": c.get("gap_pct"),
            "gap_band": c.get("gap_band"),
            "score": c.get("score"),
            "thesis": "; ".join(c.get("reasons") or [])[:200],
            "evaluations": {},
        }
        if regime:
            entry["regime"] = regime
        new_entries.append(entry)
    if not new_entries:
        return
    with open(performance.EARLY_ENTRY_LOG, "a") as f:
        for e in new_entries:
            f.write(json.dumps(e) + "\n")
    fired_n = sum(1 for e in new_entries if e["fired"])
    log.info(
        "Logged %d early-entry candidates (%d fired / %d control)",
        len(new_entries), fired_n, len(new_entries) - fired_n,
    )


def should_run_today(now: datetime, window) -> bool:
    """True on the first regular-hours scan of the trading day. Keyed off the
    COMMITTED early_entry.json trading_date so it survives Actions cache eviction
    and cron drift — the once-a-day slot fires whenever the first RTH scan lands."""
    if not config.OPENING_ENABLED:
        return False
    if window != windows.Window.RTH:
        return False
    today = now.astimezone(config.MARKET_TZ).date().isoformat()
    try:
        if EARLY_ENTRY_FILE.exists():
            prev = json.loads(EARLY_ENTRY_FILE.read_text())
            if prev.get("trading_date") == today:
                return False
    except Exception:
        pass
    return True


def gapper_candidates(snapshots: dict[str, dict]) -> list[str]:
    """Tickers gapping at least the eligibility threshold — used to admit fresh
    gappers into the intraday-fetch set even if yesterday's tape was quiet (the
    router keys off yesterday's move, so without this they'd never be enriched)."""
    return sorted(
        t for t, s in snapshots.items()
        if abs((s or {}).get("gap_pct") or 0) >= config.OPENING_MIN_GAP_PCT
    )


# --- accountability: settled-close grading + stats ---------------------------

def _et_date(ts) -> "datetime.date | None":
    try:
        return ts.tz_convert(config.MARKET_TZ).date()
    except Exception:
        try:
            return ts.date()
        except Exception:
            return None


def evaluate_pending_early_entries(alpaca_client, now: datetime) -> None:
    """Grade early-entry calls against the SETTLED daily close at horizons
    [0, 1, 3] trading days (0 = entry-day close). Uses daily bars (not a live
    snapshot) and only grades a session once it's strictly in the past, so a
    partial intraday bar can never contaminate a result. Fail-soft."""
    if alpaca_client is None:
        return
    entries = performance._read_entries(performance.EARLY_ENTRY_LOG)
    if not entries:
        return

    today_et = now.astimezone(config.MARKET_TZ).date()

    # Which entries still need any horizon graded?
    need: list[int] = []
    for i, e in enumerate(entries):
        if e.get("price_at_entry") is None:
            continue
        evals = e.get("evaluations", {})
        if any(f"{h}d" not in evals for h in performance.EARLY_HORIZONS):
            need.append(i)
    if not need:
        return

    tickers = sorted({entries[i]["ticker"] for i in need})
    # Robust against a corrupt ts on any single log line — never let it crash
    # grading for every other call.
    parsed = [performance._parse_ts(entries[i]["ts"]) for i in need]
    parsed = [p for p in parsed if p is not None]
    min_ts = min(parsed) if parsed else now
    start_dt = min_ts.astimezone(timezone.utc) - timedelta(days=3)
    end_dt = datetime.now(timezone.utc) - timedelta(minutes=20)

    closes_by_ticker: dict[str, list[tuple]] = {}
    for i in range(0, len(tickers), technicals.BATCH_SIZE):
        batch = tickers[i: i + technicals.BATCH_SIZE]
        per_symbol = technicals._fetch_batch(batch, start_dt, end_dt)
        for sym, df in per_symbol.items():
            try:
                df = df.sort_index()
                series = []
                for ts, brow in df.iterrows():
                    d = _et_date(ts)
                    if d is None:
                        continue
                    series.append((d, float(brow["Close"])))
                closes_by_ticker[sym] = series
            except Exception:
                continue
    if not closes_by_ticker:
        return

    updated = 0
    for i in need:
        e = entries[i]
        series = closes_by_ticker.get(e["ticker"])
        if not series:
            continue
        entry_ts = performance._parse_ts(e["ts"])
        if entry_ts is None:
            continue
        entry_date = entry_ts.astimezone(config.MARKET_TZ).date()
        # Index of the entry day's bar (first bar on/after the entry date).
        idx = next((k for k, (d, _) in enumerate(series) if d >= entry_date), None)
        if idx is None:
            continue
        entry_price = e.get("price_at_entry")
        if not entry_price:
            continue
        sign = 1 if e.get("direction") == "long" else -1
        evals = e.setdefault("evaluations", {})
        for h in performance.EARLY_HORIZONS:
            key = f"{h}d"
            if key in evals:
                continue
            tgt = idx + h
            if tgt >= len(series):
                continue
            sess_date, close = series[tgt]
            if sess_date >= today_et:
                continue  # not a settled session yet
            ret = (close / entry_price - 1) * 100.0
            evals[key] = {
                "close": round(close, 2),
                "date": sess_date.isoformat(),
                "return_pct": round(ret, 2),
                "signed_return_pct": round(ret * sign, 2),
            }
            updated += 1

    if updated:
        performance._write_entries(entries, performance.EARLY_ENTRY_LOG)
        log.info("Evaluated %d pending early-entry horizons", updated)


def _bucket_stats(rets: list[float]) -> dict:
    return performance._horizon_stats(rets)


def compile_early_entry_stats(now: datetime) -> dict:
    """Roll up the last 30 days of early-entry calls. The headline split is
    fired vs control (eligible-but-passed) — if fired doesn't out-earn control,
    the signal isn't beating 'buy any gapper' and the tier should be retired."""
    entries = performance._read_entries(performance.EARLY_ENTRY_LOG)
    cutoff = (now - timedelta(days=30)).astimezone(timezone.utc).isoformat()
    recent = [e for e in entries if e.get("ts", "") >= cutoff]

    def empty() -> dict:
        return {"count": 0, "horizons": {h: [] for h in performance.EARLY_HORIZONS}}

    def add(bucketmap: dict, key: str, e: dict) -> None:
        b = bucketmap.setdefault(key, empty())
        b["count"] += 1
        for h in performance.EARLY_HORIZONS:
            ev = e.get("evaluations", {}).get(f"{h}d")
            if ev and ev.get("signed_return_pct") is not None:
                b["horizons"][h].append(ev["signed_return_pct"])

    by_fired: dict[str, dict] = {}
    by_direction: dict[str, dict] = {}
    by_gap_band: dict[str, dict] = {}
    untracked = 0
    for e in recent:
        if e.get("price_at_entry") is None:
            untracked += 1
        add(by_fired, "fired" if e.get("fired") else "control", e)
        if e.get("fired"):
            add(by_direction, e.get("direction", "long"), e)
            add(by_gap_band, e.get("gap_band", "3-5"), e)

    def finalize(bucketmap: dict) -> dict:
        return {
            key: {
                "count": st["count"],
                "horizons": {f"{h}d": _bucket_stats(rets) for h, rets in st["horizons"].items()},
            }
            for key, st in bucketmap.items()
        }

    fired_stats = finalize(by_fired)

    # The edge that decides the tier's fate: fired avg − control avg per horizon.
    edge: dict[str, float | None] = {}
    for h in performance.EARLY_HORIZONS:
        f = fired_stats.get("fired", {}).get("horizons", {}).get(f"{h}d", {}).get("avg_return_net_pct")
        c = fired_stats.get("control", {}).get("horizons", {}).get(f"{h}d", {}).get("avg_return_net_pct")
        edge[f"{h}d"] = round(f - c, 2) if (f is not None and c is not None) else None

    out = {
        "generated_at": now.isoformat(),
        "window_days": 30,
        "slippage_round_trip_pct": performance.SLIPPAGE_PCT,
        "horizons": [f"{h}d" for h in performance.EARLY_HORIZONS],
        "horizon_note": "0d = entry-day close; graded against the settled daily close",
        "total_calls": len(recent),
        "untracked_count": untracked,
        "fired_vs_control_edge_net": edge,
        "by_fired": fired_stats,
        "by_direction": finalize(by_direction),
        "by_gap_band": finalize(by_gap_band),
    }
    performance.EARLY_ENTRY_PERFORMANCE_FILE.write_text(json.dumps(out, indent=2))
    log.info(
        "Early-entry stats: %d calls in 30d (%d untracked); fired−control edge %s",
        len(recent), untracked, edge,
    )
    return out
