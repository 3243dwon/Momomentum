"""Feishu (Lark) custom-bot incoming-webhook sender.

We render alerts as interactive cards with a colored header by alert type.
Each send writes an audit record to data/audit/ so we can trace what fired.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import requests

from scanner import config

log = logging.getLogger(__name__)

ALERT_AUDIT_DIR = config.AUDIT_DIR


HEADER_TEMPLATES = {
    "catalyst": "carmine",
    "watchlist": "blue",
    "big_move": "orange",
    "unusual_volume": "yellow",
    "delta_new_top20": "purple",
    "delta_rank_jump": "purple",
    "delta_accel": "purple",
    "macro": "red",
    "synthesis": "green",
    "weekly": "turquoise",
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

    payload = _build_card(alert)
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
    ("catalyst",        "🎯 Catalysts"),
    ("watchlist",       "⭐ Watchlist"),
    ("big_move",        "🚀 Big moves"),
    ("delta_new_top20", "📈 New top-20"),
    ("delta_rank_jump", "⚡ Rank jumps"),
    ("delta_accel",     "🌡️ Accelerating"),
]


def _pick_ticker_template(alerts: list[dict]) -> str:
    """Header color for the consolidated ticker card — dominated by the
    highest-priority alert type present."""
    types = {a.get("type", "") for a in alerts}
    if "catalyst" in types:
        return "carmine"
    if "watchlist" in types:
        return "blue"
    if "big_move" in types:
        return "orange"
    return "purple"  # delta_*


def _build_ticker_card(alerts: list[dict]) -> dict:
    sections: list[str] = []
    for type_key, label in _TICKER_SECTIONS:
        group = [a for a in alerts if a.get("type") == type_key]
        if not group:
            continue
        lines = [f"**{label}** ({len(group)})"]
        for a in group:
            lines.append(a.get("body_md", "").strip())
        sections.append("\n\n".join(lines))

    body = "\n\n---\n\n".join(sections) if sections else "_(no alerts)_"
    title = f"🚨 Scanner: {len(alerts)} alert{'s' if len(alerts) != 1 else ''}"
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
    parts: list[str] = []
    for a in alerts:
        # Each macro alert already has full event + beneficiaries/losers in body_md.
        parts.append(a.get("body_md", "").strip())
    body = "\n\n---\n\n".join(parts) if parts else "_(no macro events)_"
    title = f"🌍 Macro: {len(alerts)} event{'s' if len(alerts) != 1 else ''}"
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
        resp = requests.post(config.FEISHU_WEBHOOK_URL, json=card, timeout=10)
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


def send_consolidated(alerts: list[dict]) -> int:
    """Send at most 2 cards per scan: one for ticker alerts (grouped by type)
    and one for macro events. Returns count of cards sent."""
    if not alerts:
        return 0

    ticker_alerts = [a for a in alerts if not (a.get("type") or "").startswith("macro")]
    macro_alerts = [a for a in alerts if (a.get("type") or "").startswith("macro")]

    sent = 0
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
    return sent
