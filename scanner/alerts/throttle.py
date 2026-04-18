"""Per-(ticker, alert_type) cooldown to prevent spam.

State lives in data/cache/alert_throttle.json (gitignored). The 'signal'
field lets us re-fire when the situation materially strengthens (e.g.
%change moved another 1.5%+ since the last alert).
"""
from __future__ import annotations

import json
import logging
import math
from datetime import datetime, timedelta, timezone

from scanner import config

log = logging.getLogger(__name__)

THROTTLE_FILE = config.CACHE_DIR / "alert_throttle.json"

MATERIAL_CHANGE_PCT = 1.5  # additional move beyond the last fire that re-opens the gate


def _load() -> dict:
    if not THROTTLE_FILE.exists():
        return {}
    try:
        return json.loads(THROTTLE_FILE.read_text())
    except Exception:
        return {}


def _save(state: dict) -> None:
    THROTTLE_FILE.write_text(json.dumps(state, indent=2))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _key(ticker: str, alert_type: str) -> str:
    return f"{ticker}::{alert_type}"


class Throttle:
    def __init__(self):
        self._state = _load()
        self._fired_this_run: list[dict] = []

    def allowed(self, ticker: str, alert_type: str, signal_pct: float | None = None) -> bool:
        key = _key(ticker, alert_type)
        prior = self._state.get(key)
        if not prior:
            return True
        prior_at = datetime.fromisoformat(prior["at"])
        if (_now() - prior_at) >= timedelta(seconds=config.ALERT_COOLDOWN_SECONDS):
            return True
        if signal_pct is None:
            return False
        prior_signal = prior.get("signal")
        if prior_signal is None:
            return False
        if abs(signal_pct) - abs(prior_signal) >= MATERIAL_CHANGE_PCT:
            return True
        return False

    def record(self, ticker: str, alert_type: str, signal_pct: float | None = None) -> None:
        key = _key(ticker, alert_type)
        self._state[key] = {
            "at": _now().isoformat(),
            "signal": signal_pct,
        }

    def commit(self) -> None:
        _save(self._state)
