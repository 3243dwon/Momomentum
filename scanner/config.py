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


def _env_float(name: str, default: float) -> float:
    """Read a float env var, falling back to `default` on absence or garbage.
    Wrapped so a malformed override never raises at import time (config is
    imported everywhere)."""
    try:
        return float(os.environ[name])
    except (KeyError, ValueError, TypeError):
        return default


def _env_int(name: str, default: int) -> int:
    """Int counterpart of _env_float (same fail-soft contract)."""
    try:
        return int(os.environ[name])
    except (KeyError, ValueError, TypeError):
        return default


# Gating (Contract G) — dollar-volume liquidity floor. price * avg_volume_20d
# must clear this for a name to stay in the scan. The predicate lives in
# scanner.universe.passes_liquidity_floor and is APPLIED in
# scanner.technicals._compute_row (where price*volume is known). ~$5M/day keeps
# liquid mid-caps (RKLB-class) and drops the untradeable tail. Set to 0 to
# disable the floor entirely.
MIN_DOLLAR_VOLUME = _env_float("GATING_MIN_DOLLAR_VOLUME", 5_000_000.0)

TOP_N_MOVERS = 20

PCT_MOVE_THRESHOLD_RTH = 3.0
PCT_MOVE_THRESHOLD_AH = 5.0
REL_VOLUME_THRESHOLD = 2.0
MIN_AH_VOLUME = 100_000

RANK_JUMP_THRESHOLD = 15  # raised from 10 — only significant rank shifts

ALERT_COOLDOWN_SECONDS = 2 * 60 * 60
# High-conviction alerts (catalyst, macro, serenity_match, ripple) always fire
# — no cap. Standard alerts (big_move, delta_*) get capped to avoid noise flood.
MAX_STANDARD_ALERTS_PER_SCAN = 5

# Gating (Contract G) — reversible flags that prune/throttle the noisier alert
# streams. Defaults ship the pruned/throttled state; flip the env flag to
# restore the prior behavior. Read in scanner.alerts.rules.build_alerts. The
# bool flags follow the CATALYST_ENABLED/OPENING_ENABLED idiom; numeric flags
# parse fail-soft via _env_float/_env_int above.
#
# Master switch for the delta_* family (delta_new_top20 / delta_rank_jump /
# delta_accel). Those emit loops are already commented out in rules.py; this
# flag is the belt-and-braces guarantee they stay dead — re-enabling requires
# BOTH un-commenting the loops AND flipping this to True.
DELTA_ALERTS_ENABLED = (os.environ.get("GATING_DELTA_ALERTS", "false").strip().lower()
                        not in ("0", "false", "no", "off"))
# serenity_match is a high-conviction "always-fire" type (it bypasses
# MAX_STANDARD_ALERTS_PER_SCAN), so throttling it means raising the move bar AND
# adding a per-type cap, both applied in rules.py.
#
# Whole serenity_match stream kill-switch (default on).
SERENITY_MATCH_ENABLED = (os.environ.get("GATING_SERENITY_MATCH", "true").strip().lower()
                          not in ("0", "false", "no", "off"))
# Re-checked move floor at the serenity emit site (up from the 3.0 hot-move
# floor in scanner.serenity.compute_matches).
SERENITY_MATCH_MIN_MOVE_PCT = _env_float("GATING_SERENITY_MIN_MOVE", 5.0)
# Per-type cap for the always-fire serenity_match bucket.
SERENITY_MATCH_MAX_PER_SCAN = _env_int("GATING_SERENITY_MAX", 2)

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
# Optional: signing secret for the primary bot. Set this when the Feishu bot
# has "Signature verification" enabled. Leave unset for keyword/IP-only bots.
FEISHU_SIGNING_SECRET = os.environ.get("FEISHU_SIGNING_SECRET")
# Optional: separate Feishu group for Chinese-language macro digests (e.g. mom's).
# If not set, the mom-digest module is a no-op.
FEISHU_MOM_WEBHOOK_URL = os.environ.get("FEISHU_MOM_WEBHOOK_URL")
FEISHU_MOM_SIGNING_SECRET = os.environ.get("FEISHU_MOM_SIGNING_SECRET")

USER_AGENT = "MomentumScanner/0.1 (github.com/yourhandle/momentum)"

# Financial Modeling Prep — free tier (250 req/day, 500MB/30d) covers the
# political-trades feed comfortably. Sign up at financialmodelingprep.com.
# Without the key, scanner.political falls back to no-op (the dashboard still
# renders the page but with an "API key required" note).
FMP_API_KEY = os.environ.get("FMP_API_KEY")
# Refresh interval — FMP's senate/house feeds update a few times a day at
# most, so once every 6 hours is plenty and leaves headroom on the daily cap.
POLITICAL_REFRESH_SECONDS = 6 * 60 * 60

# Catalyst calendar (scanner.catalysts) — the portfolio-driven, forward-looking
# event calendar. Reads data/portfolio.json (your holdings) and pulls each
# name's next earnings + ex-dividend dates, plus a US macro calendar
# (FOMC / CPI / jobs / PCE) from FMP, and computes the quarterly triple-witching
# locally. An Opus pass then writes a per-holding "trim/add read". Surfaced at
# /catalysts and pushed to Feishu when a catalyst is near. Shares FMP_API_KEY
# with the political feed; both stay far under the 250/day cap. Set
# CATALYST_ENABLED=0 to disable the tier entirely.
CATALYST_ENABLED = (os.environ.get("CATALYST_ENABLED", "true").strip().lower()
                    not in ("0", "false", "no", "off"))
# How far forward to surface scheduled events.
CATALYST_HORIZON_DAYS = 120
# Refresh interval — earnings/ex-div dates don't move intraday, so twice a day
# is plenty and keeps FMP calls (~2 per holding + 1 macro) tiny.
CATALYST_REFRESH_SECONDS = 12 * 60 * 60
# Push a Feishu heads-up when a catalyst is this many calendar days out or less
# (and hasn't been pinged yet).
CATALYST_NOTIFY_DAYS = 3
# Model for the per-holding trim/add read. Opus by default (the same macro-
# reasoning tier); override to a cheaper model if the twice-daily note regen
# ever adds up.
CATALYST_NOTES_MODEL = os.environ.get("CATALYST_NOTES_MODEL", OPUS_MODEL)

# Serenity (@aleabitoreddit) — momentum polls the X API directly, 24/7, in its
# own workflow (serenity-poll.yml). Pay-per-use: ~$0.005 per tweet returned, and
# empty polls (since_id) are free. Needs an X API OAuth2 app-only bearer token.
# Set empty to disable the Serenity poller entirely.
X_BEARER_TOKEN = (os.environ.get("X_BEARER_TOKEN") or "").strip() or None
# A Serenity-named ticker counts as a "hot match" (serenity_match alert) when
# it's moving at least this much in the live scan.
SERENITY_HOT_MOVE_PCT = 3.0

# Ripple (forward second-order catalyst) — Opus reasons about which OTHER names
# a popular stock's high-impact news helps or hurts, ideally BEFORE those names
# move. Cost-bounded by design: only popular triggers (S&P 500 / NDX),
# only high-impact company news, deduped per story, hard-capped per scan, Opus.
# Set to 0 to disable the ripple tier entirely.
MAX_RIPPLE_EVENTS_PER_SCAN = 4
# A predicted name is "not yet priced in" (the high-value, push-worthy case)
# when it has moved less than this, in the predicted direction, in the live scan.
RIPPLE_PRICED_IN_PCT = 2.0
# News types whose stories plausibly ripple to OTHER tickers. Analyst notes and
# litigation rarely move a different company, so they're excluded as triggers.
RIPPLE_TRIGGER_TYPES = ("ma", "product", "guidance", "earnings")

# Scan briefing — one Sonnet call per scan that condenses everything the scan
# already computed into data/briefing.json (headline / actions / watch /
# changed / caveats) for the web front page. Set BRIEFING_ENABLED=0 to disable.
BRIEFING_ENABLED = (os.environ.get("BRIEFING_ENABLED", "true").strip().lower()
                    not in ("0", "false", "no", "off"))

# Opening catch-list (scanner.opening) — the early-entry tier. Once per trading
# day, on the first RTH scan after the 09:30 open (~10:00 ET), flag liquid names
# that gapped and are HOLDING above/below VWAP on the opening range — a
# confirmed-continuation list price-stamped at the live snapshot price, scored
# by-close/+1d/+3d so it proves itself. Honest about the data: IEX feed + the
# ~20-min historical-bar lag mean this reads ~09:40 structure at ~10:00, on
# liquid large-caps only. Set OPENING_ENABLED=0 to disable the tier entirely.
OPENING_ENABLED = (os.environ.get("OPENING_ENABLED", "true").strip().lower()
                   not in ("0", "false", "no", "off"))
# Minimum overnight gap (live price vs prev close) to be an eligible candidate.
OPENING_MIN_GAP_PCT = 3.0
# Liquidity floor — IEX only prints densely enough on liquid names for the
# gap/VWAP/live-price reads to be trustworthy. S&P 500 / NDX membership also
# qualifies regardless of this threshold.
OPENING_MIN_AVG_VOL = 2_000_000
# A candidate "fires" (enters the actionable catch list) only if it's HOLDING
# near VWAP — above (long) / below (short) by no more than this, so we catch the
# hold, not a blown-off chase.
OPENING_MAX_VWAP_DIST_PCT = 3.0
# ...and hasn't given back more than this from the opening high (long) / low
# (short) — a name fading off its extreme at 10:00 is not catching.
OPENING_MAX_GIVEBACK_PCT = 6.0
# Cap the actionable list per side; the rest stay logged as the control cohort.
OPENING_MAX_PER_SIDE = 5
# Soft preference: time-of-day relative volume at/above this is rewarded in the
# rank (never a hard gate — IEX fractional volume biases the absolute low).
OPENING_RVOL_TOD_MIN = 1.0
