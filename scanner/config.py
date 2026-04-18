"""Central configuration. All tunable knobs live here."""
from __future__ import annotations

import os
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
CACHE_DIR = DATA_DIR / "cache"
AUDIT_DIR = DATA_DIR / "audit"

for d in (DATA_DIR, CACHE_DIR, AUDIT_DIR):
    d.mkdir(parents=True, exist_ok=True)

MARKET_TZ = ZoneInfo("America/New_York")

MIN_PRICE = 3.0
MIN_AVG_VOLUME_20D = 500_000

TOP_N_MOVERS = 20

PCT_MOVE_THRESHOLD_RTH = 3.0
PCT_MOVE_THRESHOLD_AH = 5.0
REL_VOLUME_THRESHOLD = 2.0
MIN_AH_VOLUME = 100_000

RANK_JUMP_THRESHOLD = 10

ALERT_COOLDOWN_SECONDS = 2 * 60 * 60

UNIVERSE_REBUILD_AFTER_DAYS = 7

HAIKU_MODEL = os.environ.get("HAIKU_MODEL", "claude-haiku-4-5-20251001")
SONNET_MODEL = os.environ.get("SONNET_MODEL", "claude-sonnet-4-6")
OPUS_MODEL = os.environ.get("OPUS_MODEL", "claude-opus-4-7")

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
FEISHU_WEBHOOK_URL = os.environ.get("FEISHU_WEBHOOK_URL")

USER_AGENT = "MomentumScanner/0.1 (github.com/yourhandle/momentum)"
