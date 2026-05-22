"""Standard-alert digest buffer.

Breaking alerts (catalyst, watchlist, macro:*) push live every scan. Standard
alerts (big_move, delta_*) are buffered to disk and flushed into a single
consolidated card at the ET clock times in ``config.DIGEST_FLUSH_TIMES_ET`` —
typically market open and market close — so the channel doesn't drum every
30 minutes.

Each ``(flush_time, ET-date)`` pair fires at most once per day. The buffer
survives process restarts via JSON state in ``data/cache/``.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, time
from pathlib import Path

from scanner import config

log = logging.getLogger(__name__)

BUFFER_FILE: Path = config.CACHE_DIR / "alert_digest_buffer.json"


def _load() -> dict:
    if not BUFFER_FILE.exists():
        return {"alerts": [], "last_flush_by_time": {}}
    try:
        state = json.loads(BUFFER_FILE.read_text())
    except Exception:
        return {"alerts": [], "last_flush_by_time": {}}
    state.setdefault("alerts", [])
    state.setdefault("last_flush_by_time", {})
    return state


def _save(state: dict) -> None:
    BUFFER_FILE.write_text(json.dumps(state, indent=2))


def _parse_hm(s: str) -> time:
    h, m = s.split(":")
    return time(int(h), int(m))


def should_flush(
    now_utc: datetime,
    last_flush_by_time: dict[str, str] | None = None,
) -> str | None:
    """Return the first flush-time key (e.g. ``"09:30"``) whose scheduled
    moment has passed today AND hasn't already fired today. ``None`` if no
    flush is due this scan, or if the digest is disabled (empty flush list).
    """
    if not config.DIGEST_FLUSH_TIMES_ET:
        return None
    last = last_flush_by_time or {}
    now_et = now_utc.astimezone(config.MARKET_TZ)
    today_et = now_et.date().isoformat()
    for ft_str in config.DIGEST_FLUSH_TIMES_ET:
        ft = _parse_hm(ft_str)
        flush_dt = now_et.replace(hour=ft.hour, minute=ft.minute, second=0, microsecond=0)
        if now_et < flush_dt:
            continue
        if last.get(ft_str) == today_et:
            continue
        return ft_str
    return None


def append(alerts: list[dict]) -> int:
    """Append alerts to the buffer; FIFO-drop oldest beyond
    ``config.DIGEST_MAX_PER_CARD``. Returns the buffer size after append.
    Each alert is stamped with the ET clock time it was buffered so the
    eventual digest card shows when each event fired.
    """
    state = _load()
    if not alerts:
        return len(state.get("alerts", []))
    now_et = datetime.now(config.MARKET_TZ)
    stamp = now_et.strftime("%H:%M ET")
    stamped = []
    for a in alerts:
        a = dict(a)  # shallow copy so we don't mutate caller's dict
        a["_buffered_at"] = stamp
        stamped.append(a)
    state["alerts"].extend(stamped)
    cap = config.DIGEST_MAX_PER_CARD
    if len(state["alerts"]) > cap:
        dropped = len(state["alerts"]) - cap
        state["alerts"] = state["alerts"][-cap:]
        log.info("Digest buffer: FIFO-dropped %d oldest alerts (cap %d)", dropped, cap)
    _save(state)
    return len(state["alerts"])


def peek() -> list[dict]:
    """Return the current buffer contents without draining (debug/inspection)."""
    return list(_load().get("alerts", []))


def drain_and_record(flush_time_key: str, now_utc: datetime) -> list[dict]:
    """Pull all buffered alerts and mark ``(flush_time_key, today)`` as fired.

    Idempotent within the same ET-date: re-calling for the same key on the
    same day after draining returns an empty list and the timestamp stays.
    """
    state = _load()
    drained = state.get("alerts", [])
    state["alerts"] = []
    today_et = now_utc.astimezone(config.MARKET_TZ).date().isoformat()
    state.setdefault("last_flush_by_time", {})[flush_time_key] = today_et
    _save(state)
    return drained


def annotate_for_card(alerts: list[dict]) -> list[dict]:
    """Prepend the buffer timestamp to each alert's body so the consolidated
    card shows when each fired. Returns a new list; does not mutate input."""
    out = []
    for a in alerts:
        stamp = a.get("_buffered_at")
        if stamp and a.get("body_md"):
            new = dict(a)
            new["body_md"] = f"`{stamp}` {a['body_md']}"
            new.pop("_buffered_at", None)
            out.append(new)
        else:
            out.append({k: v for k, v in a.items() if k != "_buffered_at"})
    return out
