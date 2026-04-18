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
MIN_AVG_VOLUME_20D = 100_000  # includes mid + small caps; below this %chg gets noisy

TOP_N_MOVERS = 20

PCT_MOVE_THRESHOLD_RTH = 3.0
PCT_MOVE_THRESHOLD_AH = 5.0
REL_VOLUME_THRESHOLD = 2.0
MIN_AH_VOLUME = 100_000

RANK_JUMP_THRESHOLD = 15  # raised from 10 — only significant rank shifts

ALERT_COOLDOWN_SECONDS = 2 * 60 * 60
# High-conviction alerts (catalyst, macro, watchlist) always fire — no cap.
# Standard alerts (big_move, delta_*) get capped to avoid noise flood.
MAX_STANDARD_ALERTS_PER_SCAN = 5

# Hard caps per scan to bound monthly LLM spend. When over, we score and
# send the most-informative candidates first.
MAX_HAIKU_NEWS_ITEMS_PER_SCAN = 100
MAX_SONNET_SYNTHESES_PER_SCAN = 20
MAX_OPUS_MACRO_PER_SCAN = 5

UNIVERSE_REBUILD_AFTER_DAYS = 7

HAIKU_MODEL = os.environ.get("HAIKU_MODEL", "claude-haiku-4-5-20251001")
SONNET_MODEL = os.environ.get("SONNET_MODEL", "claude-sonnet-4-6")
OPUS_MODEL = os.environ.get("OPUS_MODEL", "claude-opus-4-7")

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
FEISHU_WEBHOOK_URL = os.environ.get("FEISHU_WEBHOOK_URL")
# Optional: separate Feishu group for Chinese-language macro digests (e.g. mom's).
# If not set, the mom-digest module is a no-op.
FEISHU_MOM_WEBHOOK_URL = os.environ.get("FEISHU_MOM_WEBHOOK_URL")

USER_AGENT = "MomentumScanner/0.1 (github.com/yourhandle/momentum)"
