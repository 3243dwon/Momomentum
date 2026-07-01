"""Feishu (Lark) custom-bot incoming-webhook sender.

We render alerts as interactive cards with a colored header by alert type.
Each send writes an audit record to data/audit/ so we can trace what fired.

Bots with "Signature verification" enabled require `timestamp` + `sign` fields
on the payload. We inject them when ``FEISHU_SIGNING_SECRET`` is configured;
without it the payload goes through unsigned (works for bots with only
keyword/IP-allowlist verification or no verification at all).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import time
from datetime import datetime, timezone

import requests

from scanner import config
from scanner.alerts.rules import _clip

log = logging.getLogger(__name__)


def _gen_sign(timestamp: str, secret: str) -> str:
    """Feishu signature: HMAC-SHA256 over an empty body, with key
    f'{timestamp}\\n{secret}', base64-encoded. Per Feishu docs."""
    string_to_sign = f"{timestamp}\n{secret}"
    digest = hmac.new(string_to_sign.encode("utf-8"), digestmod=hashlib.sha256).digest()
    return base64.b64encode(digest).decode("utf-8")


def sign_payload(payload: dict, secret: str | None) -> dict:
    """Return payload with timestamp+sign injected if a secret is given.
    Returns the payload unchanged when secret is empty/None."""
    if not secret:
        return payload
    ts = str(int(time.time()))
    return {**payload, "timestamp": ts, "sign": _gen_sign(ts, secret)}

ALERT_AUDIT_DIR = config.AUDIT_DIR


HEADER_TEMPLATES = {
    "catalyst": "carmine",
    "big_move": "orange",
    "unusual_volume": "yellow",
    "delta_new_top20": "purple",
    "delta_rank_jump": "purple",
    "delta_accel": "purple",
    "macro": "red",
    "synthesis": "green",
    "weekly": "turquoise",
    "trump_pulse": "violet",
    "serenity_match": "indigo",
}


def _audit(alert: dict, response: dict | None, error: str | None) -> None:
    now = datetime.now(timezone.utc)
    day_dir = ALERT_AUDIT_DIR / now.strftime("%Y-%m-%d")
    day_dir.mkdir(parents=True, exist_ok=True)
    slug = (alert.get("ticker") or alert.get("type") or "alert").replace(" ", "_")[:30]
    path = day_dir / f"alert_{now.strftime('%H%M%S')}_{slug}.json"
    path.write_text(
        json.dumps(
            {"ts": now.isoformat(), "alert": alert, "response": response, "error": error},
            indent=2,
        )
    )


def _build_card(alert: dict) -> dict:
    title = alert["title"]
    body_md = alert["body_md"]
    template = HEADER_TEMPLATES.get(alert.get("type", ""), "blue")
    elements = [{"tag": "div", "text": {"tag": "lark_md", "content": body_md}}]
    if alert.get("link"):
        elements.append(
            {
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "Open in scanner"},
                        "url": alert["link"],
                        "type": "default",
                    }
                ],
            }
        )
    return {
        "msg_type": "interactive",
        "card": {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": title},
                "template": template,
            },
            "elements": elements,
        },
    }


def send(alert: dict) -> bool:
    """Send one alert. Returns True on success. Audits in all cases."""
    if not config.FEISHU_WEBHOOK_URL:
        log.info("FEISHU_WEBHOOK_URL not set; alert dry-run only")
        _audit(alert, None, "FEISHU_WEBHOOK_URL not configured")
        return False

    payload = sign_payload(_build_card(alert), config.FEISHU_SIGNING_SECRET)
    try:
        resp = requests.post(
            config.FEISHU_WEBHOOK_URL,
            json=payload,
            timeout=10,
        )
        body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {"text": resp.text}
        if resp.status_code == 200 and body.get("StatusCode") in (0, None):
            _audit(alert, body, None)
            return True
        _audit(alert, body, f"HTTP {resp.status_code}")
        log.warning("Feishu send failed: %s %s", resp.status_code, body)
        return False
    except requests.RequestException as e:
        _audit(alert, None, str(e))
        log.warning("Feishu request error: %s", e)
        return False


def send_batch(alerts: list[dict]) -> int:
    """Send a batch sequentially. Returns count of successful sends."""
    sent = 0
    for alert in alerts:
        if send(alert):
            sent += 1
    return sent


# --- Consolidated sender -----------------------------------------------------
# One scan used to produce up to 10+ Feishu cards (one per ticker alert). That
# spams the channel. Consolidated sender collapses ticker alerts into a single
# card with per-type sections, and macro events into a single macro card. Goal:
# ≤2 cards per scan regardless of signal count.

_TICKER_SECTIONS = [
    ("catalyst",        "🎯", "Catalysts"),
    ("ripple",          "🔮", "Ripple"),
    ("serenity_match",  "🧠", "Serenity"),
    ("big_move",        "🚀", "Big moves"),
    ("delta_new_top20", "📈", "New top-20"),
    ("delta_rank_jump", "⚡", "Rank jumps"),
    ("delta_accel",     "🌡️", "Accelerating"),
]


def _best_alert(alerts: list[dict]) -> dict:
    """The single alert whose title leads the card: first catalyst, else first
    ripple, else first macro, else the first alert (list is priority-ordered)."""
    for typ in ("catalyst", "ripple"):
        for a in alerts:
            if a.get("type") == typ:
                return a
    for a in alerts:
        if (a.get("type") or "").startswith("macro"):
            return a
    return alerts[0]


def _consolidated_title(alerts: list[dict]) -> str:
    """`{best alert's title} · +{N-1} more` — the title is all the phone
    notification preview shows, so it carries the highest-value line."""
    lead = _best_alert(alerts).get("title") or "Scanner alerts"
    if len(alerts) == 1:
        return _clip(lead, 60)
    more = f" · +{len(alerts) - 1} more"
    return _clip(lead, max(20, 60 - len(more))) + more


def _pick_ticker_template(alerts: list[dict]) -> str:
    """Header color for the consolidated ticker card — dominated by the
    highest-priority alert type present."""
    types = {a.get("type", "") for a in alerts}
    if "catalyst" in types:
        return "carmine"
    if "serenity_match" in types:
        return "indigo"
    if "big_move" in types:
        return "orange"
    return "purple"  # delta_*


def _build_ticker_card(alerts: list[dict]) -> dict:
    # One-line alerts under single-line bold section headers; each alert's
    # body_md already ends in its own [→](/t/{ticker}) deep link.
    sections: list[str] = []
    for type_key, emoji, name in _TICKER_SECTIONS:
        group = [a for a in alerts if a.get("type") == type_key]
        if not group:
            continue
        lines = [f"{emoji} **{name} ({len(group)})**"]
        lines.extend(a.get("body_md", "").strip() for a in group)
        sections.append("\n".join(lines))

    known = {key for key, _, _ in _TICKER_SECTIONS}
    other = [a for a in alerts if a.get("type") not in known]
    if other:  # never silently drop an unknown alert type from the card
        lines = [f"📌 **Other ({len(other)})**"]
        lines.extend(a.get("body_md", "").strip() for a in other)
        sections.append("\n".join(lines))

    body = "\n\n".join(sections) if sections else "_(no alerts)_"
    title = _consolidated_title(alerts)
    return {
        "msg_type": "interactive",
        "card": {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": title},
                "template": _pick_ticker_template(alerts),
            },
            "elements": [{"tag": "div", "text": {"tag": "lark_md", "content": body}}],
        },
    }


def _build_macro_card(alerts: list[dict]) -> dict:
    # Each macro alert's body_md is already a compact event + Wins/Risks block.
    parts = [a.get("body_md", "").strip() for a in alerts]
    body = "\n\n".join(p for p in parts if p) or "_(no macro events)_"
    title = _consolidated_title(alerts)
    return {
        "msg_type": "interactive",
        "card": {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": title},
                "template": "red",
            },
            "elements": [{"tag": "div", "text": {"tag": "lark_md", "content": body}}],
        },
    }


def _post_card(card: dict, stub_alert: dict) -> bool:
    """Post a pre-built consolidated card. stub_alert is what gets audited."""
    if not config.FEISHU_WEBHOOK_URL:
        log.info("FEISHU_WEBHOOK_URL not set; consolidated alert dry-run only")
        _audit(stub_alert, None, "FEISHU_WEBHOOK_URL not configured")
        return False
    try:
        resp = requests.post(
            config.FEISHU_WEBHOOK_URL,
            json=sign_payload(card, config.FEISHU_SIGNING_SECRET),
            timeout=10,
        )
        body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {"text": resp.text}
        if resp.status_code == 200 and body.get("StatusCode") in (0, None):
            _audit(stub_alert, body, None)
            return True
        _audit(stub_alert, body, f"HTTP {resp.status_code}")
        log.warning("Feishu send failed: %s %s", resp.status_code, body)
        return False
    except requests.RequestException as e:
        _audit(stub_alert, None, str(e))
        log.warning("Feishu request error: %s", e)
        return False


def send_consolidated(alerts: list[dict]) -> tuple[int, list[dict]]:
    """Send at most 2 cards per scan: one for ticker alerts (grouped by type)
    and one for macro events. Returns (cards_sent, alerts_delivered) where
    alerts_delivered contains exactly the alerts included in cards that were
    successfully posted — callers use it to throttle-record / performance-log
    only what actually went out."""
    if not alerts:
        return 0, []

    ticker_alerts = [a for a in alerts if not (a.get("type") or "").startswith("macro")]
    macro_alerts = [a for a in alerts if (a.get("type") or "").startswith("macro")]

    sent = 0
    delivered: list[dict] = []
    if ticker_alerts:
        card = _build_ticker_card(ticker_alerts)
        stub = {
            "type": "consolidated_ticker",
            "title": card["card"]["header"]["title"]["content"],
            "body_md": card["card"]["elements"][0]["text"]["content"],
            "n_alerts": len(ticker_alerts),
            "types": sorted({a.get("type", "") for a in ticker_alerts}),
        }
        if _post_card(card, stub):
            sent += 1
            delivered.extend(ticker_alerts)
    if macro_alerts:
        card = _build_macro_card(macro_alerts)
        stub = {
            "type": "consolidated_macro",
            "title": card["card"]["header"]["title"]["content"],
            "body_md": card["card"]["elements"][0]["text"]["content"],
            "n_alerts": len(macro_alerts),
        }
        if _post_card(card, stub):
            sent += 1
            delivered.extend(macro_alerts)
    return sent, delivered
