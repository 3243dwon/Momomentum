"""Stable, self-scoring tracker for the mom_digest 建议关注 (watchlist) picks.

WHY: the 建议关注 list used to be free-text invented fresh every scan with no
memory and no scoring, so it regressed to the same obvious liquid names (紫金矿业)
and nobody could tell whether the calls worked. This module gives the picks:

  1. STABILITY — picks are persisted with a stable identity (code+direction) and a
     first_seen date; recent picks + their running return are fed back into the Opus
     prompt so the model carries names forward instead of churning them every scan.
  2. ACCOUNTABILITY — each pick captures an entry price (Yahoo, via mom_quotes, which
     can price A-share/HK unlike the US-only Alpaca feed) and is marked-to-market at
     3/5/10 TRADING days, producing a rolling hit-rate shown on the card.

Mirrors the proven performance.py loop (log → evaluate → compile → committed JSON)
but for CN/HK names. Everything is fail-soft: a network/parse miss degrades a pick to
status='untracked' and never raises into the scan.
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone

from scanner import config, mom_quotes

log = logging.getLogger(__name__)

WATCHLIST_FILE = config.DATA_DIR / "mom_watchlist.json"
PERF_FILE = config.DATA_DIR / "mom_watchlist_performance.json"

HORIZONS = (3, 5, 10)          # trading days
PRIMARY_HORIZON = 5            # the horizon that decides hit/miss + the headline hit-rate
WINDOW_DAYS = 30              # rolling window for compiled stats
# A pick stays active until its longest horizon is recorded OR this many CALENDAR
# days elapse. 10 trading days span ~14 calendar days clean, but CN/HK week-long
# holidays (Golden Week, Spring Festival) push that to ~21 — so the cushion must
# clear that, otherwise the 10d cell would be archived away before it ever lands.
ACTIVE_MAX_AGE_DAYS = 28
MAX_PICKS = 300              # cap stored history

# A pick is "benched" — suppressed from re-recommendation — once it has lost at
# EVERY horizon we've marked so far, across at least BENCH_MIN_HORIZONS of them
# (the 连续跑输 pattern, e.g. 紫金矿业: 3d −2.2% then 5d −9.2%). One isolated bad
# mark isn't enough, and a single green horizon clears it. The bench is a COOLDOWN
# not a ban: it lifts once a name hasn't been recommended for BENCH_LOOKBACK_DAYS,
# and a genuine direction flip is a different pick id so it's never caught.
BENCH_MIN_HORIZONS = 2
BENCH_LOOKBACK_DAYS = 28

_DIR_LONG = {"long", "buy", "多", "看多", "做多", "bull", "bullish"}
_DIR_SHORT = {"short", "sell", "空", "看空", "做空", "bear", "bearish"}


# ── state io ───────────────────────────────────────────────────────────────
def _load() -> dict:
    if not WATCHLIST_FILE.exists():
        return {"picks": []}
    try:
        return json.loads(WATCHLIST_FILE.read_text())
    except Exception:
        return {"picks": []}


def _save(state: dict) -> None:
    state["generated_at"] = datetime.now(timezone.utc).isoformat()
    picks = state.get("picks", [])
    # newest-first by last_seen, capped
    picks.sort(key=lambda p: p.get("last_seen", ""), reverse=True)
    state["picks"] = picks[:MAX_PICKS]
    WATCHLIST_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False))


# ── parsing / identity ──────────────────────────────────────────────────────
def _norm_direction(value: str | None) -> str:
    v = (value or "").strip().lower()
    if v in _DIR_SHORT:
        return "short"
    return "long"  # default & _DIR_LONG


def _normalize_pick(item) -> dict | None:
    """Accept the new object form {name_zh, code, direction, reason_zh} or the
    legacy string form '中文名 (代码)'. Return a normalized dict or None."""
    if isinstance(item, dict):
        code = (item.get("code") or "").strip()
        name = (item.get("name_zh") or item.get("name") or "").strip()
        direction = _norm_direction(item.get("direction"))
        thesis = (item.get("reason_zh") or item.get("thesis_zh") or "").strip()
    elif isinstance(item, str):
        import re
        m = re.search(r"^(.*?)[（(]\s*([0-9A-Za-z.]+)\s*[)）]", item.strip())
        if not m:
            return None
        name, code = m.group(1).strip(), m.group(2).strip()
        direction, thesis = "long", ""
    else:
        return None
    if not code:
        return None
    return {"name_zh": name, "code": code, "direction": direction, "thesis_zh": thesis}


def _pick_id(code: str, direction: str) -> str:
    # Key identity on the CANONICAL Yahoo symbol so trivial format drift in the
    # model's output (601899.SH vs 601899.SS, 700.HK vs 0700.HK) maps to ONE pick
    # and carry-forward survives — otherwise a reformatted code would orphan the
    # prior call and reset its track record, reintroducing the churn we're killing.
    canon = mom_quotes.to_yahoo(code) or (code or "").strip().upper()
    return hashlib.sha1(f"{canon}|{direction}".encode()).hexdigest()[:12]


def _signed(return_pct: float, direction: str) -> float:
    return return_pct * (1.0 if direction == "long" else -1.0)


def _running_return(pick: dict) -> float | None:
    """Latest available signed return for display: prefer 5d, then 3d, then 10d."""
    ev = pick.get("evaluations", {})
    for h in (PRIMARY_HORIZON, 3, 10):
        cell = ev.get(f"{h}d")
        if cell and cell.get("signed_return_pct") is not None:
            return cell["signed_return_pct"]
    return None


def _signed_marks(pick: dict) -> list[float]:
    """Every recorded horizon mark (signed return), in 3/5/10-day order."""
    ev = pick.get("evaluations", {}) or {}
    out = []
    for h in HORIZONS:
        cell = ev.get(f"{h}d")
        if cell and cell.get("signed_return_pct") is not None:
            out.append(cell["signed_return_pct"])
    return out


def _is_sustained_loser(pick: dict) -> bool:
    """True if the pick went the wrong way at EVERY measured horizon, across at
    least BENCH_MIN_HORIZONS of them — the 连续跑输 pattern. Signed, so it respects
    direction (a short that fell is a winner, not a loser)."""
    marks = _signed_marks(pick)
    return len(marks) >= BENCH_MIN_HORIZONS and all(m < 0 for m in marks)


def _active_picks(state: dict) -> list[dict]:
    return [p for p in state.get("picks", []) if not p.get("archived")]


# ── read-only views (card + prompt) ─────────────────────────────────────────
def preview(raw_watchlist: list) -> list[dict]:
    """Read-only enrichment for the card: mark each pick carried-vs-new and attach
    its running return, WITHOUT persisting or hitting the network."""
    try:
        state = _load()
        by_id = {p["id"]: p for p in _active_picks(state)}
        out = []
        for item in raw_watchlist or []:
            norm = _normalize_pick(item)
            if not norm:
                continue
            pid = _pick_id(norm["code"], norm["direction"])
            existing = by_id.get(pid)
            out.append({
                **norm,
                "carried": bool(existing),
                "first_seen": existing.get("first_seen") if existing else None,
                "running_return_pct": _running_return(existing) if existing else None,
                "status": existing.get("status") if existing else "new",
                "trackable": mom_quotes.to_yahoo(norm["code"]) is not None,
            })
        return out
    except Exception as e:
        log.warning("mom_watchlist.preview failed: %s", e)
        return []


def track_record() -> dict:
    """Headline scoreboard for the card / prompt: {hit_rate, n_evaluated, ...}."""
    try:
        if not PERF_FILE.exists():
            return {}
        perf = json.loads(PERF_FILE.read_text())
        cell = (perf.get("by_horizon") or {}).get(f"{PRIMARY_HORIZON}d", {})
        return {
            "primary_horizon": PRIMARY_HORIZON,
            "hit_rate": cell.get("hit_rate"),
            "n_evaluated": cell.get("evaluated", 0),
            "avg_return_pct": cell.get("avg_return_pct"),
            "window_days": perf.get("window_days", WINDOW_DAYS),
            "total_tracked": perf.get("total_tracked", 0),
        }
    except Exception:
        return {}


def benched_map(now: datetime | None = None) -> dict[str, dict]:
    """Pick ids currently benched for sustained underperformance → a small reason
    dict (for the prompt, the card, and logging). Keyed on the canonical pick id
    (code+direction) so it lines up with commit()/preview() identity.

    A name is benched when its freshest pick is a 连续跑输 loser AND was last
    recommended within BENCH_LOOKBACK_DAYS — so the bench is a cooldown, not a ban.
    """
    now = now or datetime.now(timezone.utc)
    try:
        state = _load()
    except Exception:
        return {}
    # Freshest pick per id — an id recurs (archived + active) when a name is
    # re-recommended after its prior call aged out; judge on the latest one.
    latest: dict[str, dict] = {}
    for p in state.get("picks", []):
        pid = p.get("id")
        if not pid:
            continue
        cur = latest.get(pid)
        if cur is None or p.get("last_seen", "") > cur.get("last_seen", ""):
            latest[pid] = p
    out: dict[str, dict] = {}
    for pid, p in latest.items():
        if _age_days(p.get("last_seen", ""), now) > BENCH_LOOKBACK_DAYS:
            continue
        if _is_sustained_loser(p):
            out[pid] = {
                "name_zh": p.get("name_zh"),
                "code": p.get("code"),
                "direction": p.get("direction"),
                "running_return_pct": _running_return(p),
                "marks": _signed_marks(p),
            }
    return out


def recent_context(limit: int = 8, now: datetime | None = None) -> dict:
    """What to feed the Opus prompt: the still-active picks (so it carries them
    forward) + the rolling track record (so it's anchored to reality) + the benched
    names (so it stops re-recommending sustained losers like 紫金矿业)."""
    try:
        state = _load()
        benched = benched_map(now)
        active = [
            p for p in sorted(_active_picks(state), key=lambda p: p.get("last_seen", ""), reverse=True)
            if p.get("id") not in benched  # don't nudge Opus to carry a benched name
        ]
        picks = [{
            "name_zh": p.get("name_zh"),
            "code": p.get("code"),
            "direction": p.get("direction"),
            "thesis_zh": p.get("thesis_zh"),  # so Opus can judge if the catalyst still holds
            "first_seen": p.get("first_seen"),
            "running_return_pct": _running_return(p),
            "status": p.get("status"),
        } for p in active[:limit]]
        benched_list = [{
            "name_zh": b.get("name_zh"),
            "code": b.get("code"),
            "direction": b.get("direction"),
            "running_return_pct": b.get("running_return_pct"),
        } for b in benched.values()]
        return {"previously_recommended": picks, "track_record": track_record(), "benched": benched_list}
    except Exception as e:
        log.warning("mom_watchlist.recent_context failed: %s", e)
        return {"previously_recommended": [], "track_record": {}, "benched": []}


def filter_benched(raw_watchlist: list, now: datetime | None = None) -> tuple[list, list]:
    """Split Opus's raw watchlist into (kept, dropped) by the bench list — the
    DETERMINISTIC backstop. Even if Opus re-recommends a benched name despite the
    prompt, it never reaches the card or the tracker. Matching is on canonical
    (code+direction) id, so a real direction flip (a fresh thesis) is NOT dropped."""
    benched = benched_map(now)
    if not benched:
        return list(raw_watchlist or []), []
    kept, dropped = [], []
    for item in raw_watchlist or []:
        norm = _normalize_pick(item)
        if not norm:
            kept.append(item)  # unparseable — leave it for downstream to skip
            continue
        pid = _pick_id(norm["code"], norm["direction"])
        if pid in benched:
            dropped.append({**norm, **benched[pid]})
        else:
            kept.append(item)  # preserve Opus's original object form for commit/preview
    return kept, dropped


# ── write path (after a digest is sent) ──────────────────────────────────────
def commit(raw_watchlist: list, confidence: str | None, now: datetime) -> None:
    """Persist the picks we just showed: dedup by (code,direction), keep first_seen
    for carried names, fetch an entry price for genuinely new ones."""
    try:
        state = _load()
        picks = state.get("picks", [])
        by_id = {p["id"]: p for p in picks if not p.get("archived")}
        preexisting = set(by_id)  # ids active BEFORE this commit (for the flip guard)
        today = now.date().isoformat()

        for item in raw_watchlist or []:
            norm = _normalize_pick(item)
            if not norm:
                continue
            code, direction = norm["code"], norm["direction"]
            pid = _pick_id(code, direction)
            existing = by_id.get(pid)

            if existing:  # carried forward — keep entry & first_seen, refresh metadata
                existing["last_seen"] = today
                existing["times_recommended"] = existing.get("times_recommended", 1) + 1
                if norm["thesis_zh"]:
                    existing["thesis_zh"] = norm["thesis_zh"]
                if confidence:
                    existing["confidence"] = confidence
                continue

            # New pick — archive any PRE-EXISTING opposite-direction call on the same
            # code (a genuine flip). Guard on `preexisting` so a self-contradictory
            # list (same code long+short in one digest) doesn't archive the entry we
            # just created in this very commit.
            opp = _pick_id(code, "short" if direction == "long" else "long")
            if opp in by_id and opp in preexisting:
                by_id[opp]["archived"] = True

            yahoo = mom_quotes.to_yahoo(code)
            entry_price = entry_date = currency = None
            status = "untracked"
            if yahoo:
                hist = mom_quotes.fetch_history(yahoo)
                if hist and mom_quotes.is_trackable(hist, yahoo) and hist.get("closes"):
                    closes = hist["closes"]
                    as_of = hist.get("as_of_date")
                    # Enter on the last SETTLED close (date < exchange-today), so the
                    # entry price and date refer to the SAME finalized bar — never a
                    # still-forming intraday bar that would bias every later return.
                    settled = [(d, c) for (d, c) in closes if not as_of or d < as_of]
                    entry_date, entry_price = settled[-1] if settled else closes[-1]
                    currency = hist.get("currency")
                    status = "pending"

            pick = {
                "id": pid,
                "name_zh": norm["name_zh"],
                "code": code,
                "yahoo": yahoo,
                "direction": direction,
                "thesis_zh": norm["thesis_zh"],
                "confidence": confidence,
                "first_seen": today,
                "last_seen": today,
                "times_recommended": 1,
                "entry_price": entry_price,
                "entry_date": entry_date,
                "currency": currency,
                "evaluations": {},
                "status": status,
                "archived": False,
            }
            picks.append(pick)
            by_id[pid] = pick

        state["picks"] = picks
        _save(state)
    except Exception as e:
        log.warning("mom_watchlist.commit failed: %s", e)


# ── evaluation + compile (every scan) ────────────────────────────────────────
def _age_days(entry_date: str, now: datetime) -> int:
    try:
        d0 = datetime.fromisoformat(entry_date).date()
        return (now.date() - d0).days
    except Exception:
        return 0


def evaluate(now: datetime) -> None:
    """Mark active picks to market at any elapsed 3/5/10-trading-day horizon."""
    try:
        state = _load()
        changed = False
        hist_cache: dict = {}  # fetch each symbol at most once per evaluate() call
        for p in _active_picks(state):
            entry = p.get("entry_price")
            entry_date = p.get("entry_date")
            if not entry or not entry_date:
                continue
            ev = p.setdefault("evaluations", {})
            age = _age_days(entry_date, now)
            # horizons that could plausibly have elapsed (h trading days >= h calendar days)
            pending_h = [h for h in HORIZONS if f"{h}d" not in ev and age >= h]
            if pending_h:
                ysym = p.get("yahoo")
                if ysym not in hist_cache:
                    hist_cache[ysym] = mom_quotes.fetch_history(ysym)
                closes = (hist_cache[ysym] or {}).get("closes") or []
                for h in pending_h:
                    res = mom_quotes.close_after(closes, entry_date, h)
                    if not res:
                        continue
                    d, price = res
                    ret = (price / entry - 1.0) * 100.0
                    ev[f"{h}d"] = {
                        "date": d,
                        "price": round(price, 4),
                        "return_pct": round(ret, 2),
                        "signed_return_pct": round(_signed(ret, p["direction"]), 2),
                    }
                    changed = True
            # status from the primary horizon once it's in
            primary = ev.get(f"{PRIMARY_HORIZON}d")
            if primary and p.get("status") not in ("hit", "miss"):
                p["status"] = "hit" if primary["signed_return_pct"] > 0 else "miss"
                changed = True
            # archive when fully evaluated or aged out
            if f"{HORIZONS[-1]}d" in ev or age > ACTIVE_MAX_AGE_DAYS:
                p["archived"] = True
                changed = True
        if changed:
            _save(state)
    except Exception as e:
        log.warning("mom_watchlist.evaluate failed: %s", e)


def compile_stats(now: datetime) -> None:
    """Roll the trailing window into mom_watchlist_performance.json."""
    try:
        state = _load()
        recent = []
        for p in state.get("picks", []):
            if _age_days(p.get("first_seen", ""), now) <= WINDOW_DAYS:
                recent.append(p)

        def _bucket(picks: list[dict]) -> dict:
            out = {}
            for h in HORIZONS:
                vals = [p["evaluations"][f"{h}d"]["signed_return_pct"]
                        for p in picks
                        if p.get("evaluations", {}).get(f"{h}d")]
                if vals:
                    hits = sum(1 for v in vals if v > 0)
                    graded = [v for v in vals if v != 0]  # exactly-flat = neutral, not a miss
                    out[f"{h}d"] = {
                        "evaluated": len(vals),
                        "hit_rate": round(hits / len(graded), 3) if graded else None,
                        "avg_return_pct": round(sum(vals) / len(vals), 2),
                    }
                else:
                    out[f"{h}d"] = {"evaluated": 0, "hit_rate": None, "avg_return_pct": None}
            return out

        tracked = [p for p in recent if p.get("entry_price")]
        perf = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "window_days": WINDOW_DAYS,
            "primary_horizon": PRIMARY_HORIZON,
            "total_tracked": len(tracked),
            "untracked_count": sum(1 for p in recent if not p.get("entry_price")),
            "by_horizon": _bucket(tracked),
            "by_direction": {
                "long": _bucket([p for p in tracked if p.get("direction") == "long"]),
                "short": _bucket([p for p in tracked if p.get("direction") == "short"]),
            },
        }
        PERF_FILE.write_text(json.dumps(perf, indent=2, ensure_ascii=False))
    except Exception as e:
        log.warning("mom_watchlist.compile_stats failed: %s", e)


def evaluate_and_compile(now: datetime) -> None:
    """Convenience entry point for the scan orchestrator (main.py)."""
    evaluate(now)
    compile_stats(now)
