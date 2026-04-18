"""Market-clock window detection. Drives alert threshold calibration."""
from __future__ import annotations

from datetime import datetime, time
from enum import Enum

from scanner import config


class Window(str, Enum):
    RTH = "RTH"
    AH_PRE = "AH_PRE"
    AH_POST = "AH_POST"
    OVERNIGHT = "OVERNIGHT"
    WEEKEND = "WEEKEND"


RTH_OPEN = time(9, 30)
RTH_CLOSE = time(16, 0)
PRE_OPEN = time(4, 0)
POST_CLOSE = time(20, 0)


def detect(now: datetime | None = None) -> Window:
    now = now or datetime.now(config.MARKET_TZ)
    if now.tzinfo is None:
        now = now.replace(tzinfo=config.MARKET_TZ)
    local = now.astimezone(config.MARKET_TZ)
    if local.weekday() >= 5:
        return Window.WEEKEND
    t = local.time()
    if RTH_OPEN <= t < RTH_CLOSE:
        return Window.RTH
    if PRE_OPEN <= t < RTH_OPEN:
        return Window.AH_PRE
    if RTH_CLOSE <= t < POST_CLOSE:
        return Window.AH_POST
    return Window.OVERNIGHT


def skip_equity_scan(window: Window) -> bool:
    """True if we should skip the technicals pull (no fresh price data)."""
    return window in (Window.WEEKEND, Window.OVERNIGHT)
