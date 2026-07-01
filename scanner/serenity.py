"""Serenity (@aleabitoreddit) — momentum's own 24/7 X poller.

momentum's repo is public, so GitHub Actions are free and we poll the X API
*directly* every 15 min, around the clock — independent of the (private,
windowed) lengjing pipeline. Each new tweet is:
  1. extracted with Claude (Haiku) → tickers / stance / one-line English gloss
     (regex ticker fallback when the LLM is unavailable),
  2. pushed as a card to momentum's Feishu webhook,
  3. merged into data/serenity.json (the feed the /serenity web page reads).

X bills per tweet *returned* (~$0.005), so polls that find nothing new — using
`since_id` — cost $0. You only pay per actual new tweet.

The live-scan cross-reference (serenity_match alerts) stays in the main scan,
which reads data/serenity.json via load_feed() and compares tickers against the
live universe in compute_matches().
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from urllib.parse import urlencode

import requests

from scanner import config
from scanner.llm.client import LLMClient, get_client

log = logging.getLogger(__name__)

HANDLE = "aleabitoreddit"
API_BASE = "https://api.x.com/2"
EXCLUDE = "retweets"  # keep originals + replies + quotes ("every tweet")

FEED_FILE = config.DATA_DIR / "serenity.json"
STATE_FILE = config.DATA_DIR / "serenity_state.json"  # committed; {userId, sinceId}
FEED_CAP = 200
SEED_COUNT = 10
MAX_BATCH = 10

_TICKER_RE = re.compile(r"\$([A-Za-z]{1,6})\b")


# ── state + feed I/O ────────────────────────────────────────────────
def _load_state() -> dict:
    try:
        if STATE_FILE.exists():
            return json.loads(STATE_FILE.read_text())
    except (OSError, ValueError):
        pass
    return {}


def _save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2))


def _write_feed(tweets: list[dict], now: datetime) -> None:
    """Write data/serenity.json (read by the /serenity web page + the scan).
    Written here rather than via render.py so the lightweight poll job doesn't
    pull in the scanner's heavy data deps (pandas/universe)."""
    FEED_FILE.write_text(json.dumps({"generated_at": now.isoformat(), "tweets": tweets}, indent=2))


def load_feed() -> list[dict]:
    """Read the committed tweet feed (for the scan's cross-reference). [] if absent."""
    try:
        if FEED_FILE.exists():
            data = json.loads(FEED_FILE.read_text())
            tweets = data.get("tweets", [])
            return tweets if isinstance(tweets, list) else []
    except (OSError, ValueError):
        pass
    return []


# ── X API ───────────────────────────────────────────────────────────
def _x_get(url: str, token: str) -> requests.Response:
    return requests.get(
        url,
        headers={"Authorization": f"Bearer {token}", "User-Agent": config.USER_AGENT},
        timeout=15,
    )


def _resolve_user_id(token: str) -> str:
    r = _x_get(f"{API_BASE}/users/by/username/{HANDLE}", token)
    r.raise_for_status()
    uid = r.json().get("data", {}).get("id")
    if not uid:
        raise RuntimeError(f"X user lookup returned no id for @{HANDLE}")
    return uid


def _fetch_timeline(token: str, user_id: str, since_id: str | None) -> list[dict]:
    params = {
        "max_results": "20",
        "exclude": EXCLUDE,
        "tweet.fields": "created_at,public_metrics,referenced_tweets",
    }
    if since_id:
        params["since_id"] = since_id
    else:
        params["max_results"] = str(max(5, SEED_COUNT))
    r = _x_get(f"{API_BASE}/users/{user_id}/tweets?{urlencode(params)}", token)
    if r.status_code == 429:
        log.warning("Serenity: X rate limited (429); skipping this poll.")
        return []
    r.raise_for_status()
    data = r.json().get("data", [])
    return data if isinstance(data, list) else []


# ── Claude extraction (Haiku) with regex fallback ───────────────────
EXTRACT_TOOL = {
    "name": "extract_serenity",
    "description": "Extract structured signal from each Serenity tweet.",
    "input_schema": {
        "type": "object",
        "properties": {
            "tweets": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "tickers": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "US stock tickers mentioned, uppercase, no $ prefix. [] if none.",
                        },
                        "stance": {"type": "string", "enum": ["bull", "bear", "neutral"]},
                        "summary": {"type": "string", "description": "one-line English gloss, < 140 chars"},
                    },
                    "required": ["id", "tickers", "stance", "summary"],
                },
            }
        },
        "required": ["tweets"],
    },
}

_EXTRACT_SYSTEM = (
    "You extract trading signal from tweets by Serenity (@aleabitoreddit), an "
    "AI-infrastructure & semiconductor research account whose posts move stocks. "
    "For each tweet return: the US stock tickers mentioned (uppercase, no $), the "
    "author's overall stance toward the core name (bull/bear/neutral), and a "
    "one-line English gloss of the point. Return tickers=[] if none; never invent "
    "tickers."
)


def _regex_tickers(text: str) -> list[str]:
    out: list[str] = []
    for m in _TICKER_RE.findall(text or ""):
        u = m.upper()
        if u not in out:
            out.append(u)
    return out


def _extract(client: LLMClient | None, tweets: list[dict]) -> dict[str, dict]:
    """{id: {tickers, stance, summary}}. Falls back to regex tickers / neutral
    stance / empty summary when the LLM is unavailable or errors per item."""
    out: dict[str, dict] = {}
    if client:
        for i in range(0, len(tweets), MAX_BATCH):
            batch = tweets[i : i + MAX_BATCH]
            user = json.dumps([{"id": t["id"], "text": t.get("text", "")} for t in batch])
            try:
                result = client.call_structured(
                    model=config.HAIKU_MODEL, system=_EXTRACT_SYSTEM, user=user,
                    output_tool=EXTRACT_TOOL, audit_tier="serenity_extract",
                    audit_key=f"batch_{i}", max_tokens=2048,
                )
            except Exception as e:  # never let extraction failure drop a tweet
                log.warning("Serenity extract batch failed: %s", e)
                result = None
            for e in (result or {}).get("tweets", []):
                stance = e.get("stance")
                out[str(e.get("id"))] = {
                    "tickers": [str(x).upper().lstrip("$") for x in e.get("tickers", [])],
                    "stance": stance if stance in ("bull", "bear", "neutral") else "neutral",
                    "summary": e.get("summary", ""),
                }
    for t in tweets:
        out.setdefault(
            str(t["id"]),
            {"tickers": _regex_tickers(t.get("text", "")), "stance": "neutral", "summary": ""},
        )
    return out


def _to_record(raw: dict, d: dict) -> dict:
    refs = raw.get("referenced_tweets") or []
    m = raw.get("public_metrics") or {}
    return {
        "id": raw["id"],
        "url": f"https://x.com/{HANDLE}/status/{raw['id']}",
        "createdAt": raw.get("created_at", ""),
        "text": raw.get("text", ""),
        "isReply": any(r.get("type") == "replied_to" for r in refs),
        "isQuote": any(r.get("type") == "quoted" for r in refs),
        "metrics": {
            "likes": m.get("like_count", 0),
            "reposts": m.get("retweet_count", 0) + m.get("quote_count", 0),
            "replies": m.get("reply_count", 0),
            "views": m.get("impression_count"),
        } if m else None,
        "tickers": d.get("tickers", []),
        "stance": d.get("stance", "neutral"),
        "summaryEn": d.get("summary", ""),
    }


# ── Feishu (momentum's own webhook, English) ────────────────────────
def _notify(records: list[dict]) -> int:
    """Push only the SINGLE latest tweet to Feishu per run, to keep the channel
    quiet. Older tweets from the same poll still land in the feed / on the web —
    they're just not pushed. records are oldest→newest, so [-1] is the latest.

    Title carries the signal (stance emoji + tickers, or the summary) because
    it's all the phone notification preview shows; body is one clipped line."""
    if not config.FEISHU_WEBHOOK_URL or not records:
        return 0
    from scanner.alerts import feishu
    from scanner.alerts.rules import _clip

    t = records[-1]
    skipped = len(records) - 1
    emoji = {"bull": "🟢", "bear": "🔴"}.get(t.get("stance", ""), "⚪")  # green = bullish (US)
    summary = t.get("summaryEn") or t.get("text", "")
    tickers = " ".join(f"${x}" for x in (t.get("tickers") or [])[:4])
    title = _clip(f"{emoji} Serenity · {tickers or _clip(summary, 40)}", 60)
    body = _clip(summary, 140)
    if t.get("url"):
        body += f"\n[View on X]({t['url']})"
    if skipped:
        body += f"\n_+{skipped} earlier — see /serenity_"
    ok = feishu.send({"type": "serenity_match", "ticker": None, "title": title, "body_md": body, "link": None})
    log.info("Serenity: sent %d Feishu card (latest); %d older skipped.", 1 if ok else 0, skipped)
    return 1 if ok else 0


# ── 24/7 poll entry point ───────────────────────────────────────────
def poll_and_process() -> int:
    """Poll X, process NEW tweets, push Feishu, update data/serenity.json + state.
    Returns the count of new tweets ingested. Driven by serenity-poll.yml every
    15 min. Empty polls cost $0 (since_id) and write nothing."""
    token = config.X_BEARER_TOKEN
    if not token:
        log.info("X_BEARER_TOKEN not set; Serenity poll skipped.")
        return 0

    state = _load_state()
    seeding = not state.get("sinceId")
    if not state.get("userId"):
        state["userId"] = _resolve_user_id(token)
        log.info("Serenity: resolved @%s → %s", HANDLE, state["userId"])

    raw = _fetch_timeline(token, state["userId"], state.get("sinceId"))
    if not raw:
        _save_state(state)  # persist a freshly-resolved userId
        log.info("Serenity: no new tweets.")
        return 0

    raw.sort(key=lambda t: int(t["id"]))  # oldest → newest
    derived = _extract(get_client(), raw)
    new_records = [_to_record(t, derived.get(str(t["id"]), {})) for t in raw]

    # Merge into the rolling feed (newest-first, deduped, capped).
    by_id = {t["id"]: t for t in load_feed()}
    for rec in new_records:
        by_id[rec["id"]] = rec
    merged = sorted(by_id.values(), key=lambda t: int(t["id"]), reverse=True)[:FEED_CAP]
    _write_feed(merged, datetime.now(config.MARKET_TZ))

    # Push Feishu per new tweet — but not the first-run backfill.
    if seeding:
        log.info("Serenity: seeded %d tweet(s), no Feishu (first run).", len(new_records))
    else:
        _notify(new_records)

    state["sinceId"] = str(max(int(t["id"]) for t in raw))
    _save_state(state)
    log.info("Serenity: ingested %d new tweet(s); feed holds %d.", len(new_records), len(merged))
    return len(new_records)


# ── live-scan cross-reference (used by the scan for serenity_match) ──
def compute_matches(tweets: list[dict], rows: list[dict]) -> list[dict]:
    """Hot matches: tickers Serenity named that are ALSO moving (≥
    config.SERENITY_HOT_MOVE_PCT) this scan. Tweets are newest-first so the
    most-recent context wins per ticker."""
    by_ticker = {r["ticker"]: r for r in rows}
    hot: dict[str, dict] = {}
    for tw in tweets:
        for t in tw.get("tickers", []) or []:
            row = by_ticker.get(t)
            if row is None:
                continue
            pct = row.get("pct_1d")
            moving = pct is not None and abs(pct) >= config.SERENITY_HOT_MOVE_PCT
            if moving:
                hot.setdefault(t, {
                    "ticker": t,
                    "pct_1d": pct,
                    "rel_volume": row.get("rel_volume"),
                    "stance": tw.get("stance", "neutral"),
                    "summary": tw.get("summaryEn") or (tw.get("text", "")[:160]),
                    "url": tw.get("url", ""),
                })
    return list(hot.values())
