"""Prior-scan persistence + delta detection.

Produces `data/deltas.json` describing what *changed* since the last scan:
new entrants to the top-20 movers, rank jumps, and momentum acceleration.
The state file is local-only (gitignored); deltas.json is committed so the
web app can show them.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from scanner import config

log = logging.getLogger(__name__)

STATE_FILE = config.DATA_DIR / ".last_scan_state.json"
DELTAS_FILE = config.DATA_DIR / "deltas.json"

RECENT_MOVES_HISTORY = 5


def _load_state() -> dict:
    if not STATE_FILE.exists():
        return {"last_scan_at": None, "top_20": [], "recent_moves": {}}
    try:
        return json.loads(STATE_FILE.read_text())
    except Exception as e:
        log.warning("State file unreadable (%s); starting fresh", e)
        return {"last_scan_at": None, "top_20": [], "recent_moves": {}}


def _top_n_by_abs_pct(rows: list[dict], n: int) -> list[dict]:
    ranked = sorted(
        (r for r in rows if r.get("pct_1d") is not None),
        key=lambda r: abs(r["pct_1d"]),
        reverse=True,
    )
    return ranked[:n]


def _detect_acceleration(ticker: str, pct: float, history: list[float]) -> bool:
    series = history + [pct]
    if len(series) < 3:
        return False
    last3 = series[-3:]
    if all(x > 0 for x in last3):
        return last3[0] < last3[1] < last3[2]
    if all(x < 0 for x in last3):
        return last3[0] > last3[1] > last3[2]
    return False


def compute_and_persist(rows: list[dict], now: datetime) -> dict:
    state = _load_state()
    prior_top = state.get("top_20", []) or []
    prior_ranks = {r["ticker"]: i for i, r in enumerate(prior_top)}

    current_top = _top_n_by_abs_pct(rows, config.TOP_N_MOVERS)
    current_ranks = {r["ticker"]: i for i, r in enumerate(current_top)}

    new_entrants = [
        r["ticker"] for r in current_top if r["ticker"] not in prior_ranks
    ]

    rank_jumps = []
    for t, cur_rank in current_ranks.items():
        if t in prior_ranks:
            prior_rank = prior_ranks[t]
            jump = prior_rank - cur_rank
            if jump >= config.RANK_JUMP_THRESHOLD:
                rank_jumps.append({"ticker": t, "from": prior_rank + 1, "to": cur_rank + 1, "delta": jump})

    history = state.get("recent_moves", {}) or {}
    accel = []
    new_history: dict[str, list[float]] = {}
    for r in rows:
        t = r["ticker"]
        pct = r.get("pct_1d")
        if pct is None:
            continue
        prior = history.get(t, [])
        if _detect_acceleration(t, pct, prior):
            accel.append(t)
        new_history[t] = (prior + [pct])[-RECENT_MOVES_HISTORY:]

    deltas = {
        "generated_at": now.isoformat(),
        "prior_scan_at": state.get("last_scan_at"),
        "new_top20_entrants": new_entrants,
        "rank_jumps": rank_jumps,
        "momentum_accel": accel,
    }
    DELTAS_FILE.write_text(json.dumps(deltas, indent=2))

    STATE_FILE.write_text(
        json.dumps(
            {
                "last_scan_at": now.isoformat(),
                "top_20": [
                    {"ticker": r["ticker"], "pct_1d": r["pct_1d"]} for r in current_top
                ],
                "recent_moves": new_history,
            },
            indent=2,
        )
    )

    log.info(
        "Deltas: %d new entrants, %d rank jumps, %d accel",
        len(new_entrants), len(rank_jumps), len(accel),
    )
    return deltas
