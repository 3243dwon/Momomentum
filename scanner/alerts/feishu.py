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
    "watchlist": "blue",
    "big_move": "orange",
    "unusual_volume": "yellow",
    "delta_new_top20": "purple",
    "delta_rank_jump": "purple",
    "delta_accel": "purple",
    "macro": "red",
    "synthesis": "green",
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
