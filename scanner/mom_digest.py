"""Chinese-language macro digest for a separate Feishu audience.

Purely additive: if FEISHU_MOM_WEBHOOK_URL is not set, this is a no-op.
Runs on every scan. Filters macro events classified by Haiku, selects
only HIGH-impact items with China-Shanghai relevance (direct China
keywords OR Fed/geopol/commodity events with cross-asset pull on A-shares).
Throttled to one digest per 4 hours to keep the channel calm.

Opus writes the digest in Simplified Chinese targeting a non-technical
audience: plain language, named industries affected, named A-share /
HK / SSE tickers to watch.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

from scanner import config
from scanner.llm.client import LLMClient

log = logging.getLogger(__name__)

THROTTLE_FILE = config.CACHE_DIR / "mom_digest_throttle.json"
AUDIT_DIR = config.AUDIT_DIR
THROTTLE_SECONDS = 4 * 60 * 60  # 4 hours between mom digests

CHINA_KEYWORDS = re.compile(
    r"\b(china|chinese|beijing|shanghai|shenzhen|hong kong|hk|taiwan|"
    r"yuan|renminbi|rmb|pboc|csrc|sse|hkex|a[- ]?shares?|csi ?300|hang seng|hstech|"
    r"xi jinping|xi '?s|li qiang|"
    r"huawei|alibaba|tencent|baidu|byd|nio|xpeng|li auto|xiaomi|pinduoduo|jd\.com|"
    r"tsmc|semiconductor.+(china|export|ban)|chip.+(china|ban|export)|"
    r"tariff.+china|china.+tariff|trade war|belt and road|"
    r"evergrande|country garden|property.+(china|crisis)|"
    r"yuan devaluation|yuan fix|pboc cut|reserve ratio|rrr cut)\b",
    re.IGNORECASE,
)


def _load_throttle() -> dict:
    if not THROTTLE_FILE.exists():
        return {}
    try:
        return json.loads(THROTTLE_FILE.read_text())
    except Exception:
        return {}


def _save_throttle(state: dict) -> None:
    THROTTLE_FILE.write_text(json.dumps(state, indent=2))


def _is_china_relevant(event: dict) -> tuple[bool, str]:
    """Return (matches, reason) for an already-Haiku-classified macro event."""
    title = event.get("event_summary", "") or ""
    headlines = " ".join(event.get("headlines", []) or [])
    blob = f"{title} {headlines}"
    if CHINA_KEYWORDS.search(blob):
        return True, "direct_china_keyword"
    return False, ""


MOM_DIGEST_TOOL = {
    "name": "mom_china_digest",
    "description": "Summarize today's China-relevant macro event(s) for a Chinese-reading non-professional audience.",
    "input_schema": {
        "type": "object",
        "properties": {
            "title_zh": {
                "type": "string",
                "description": "Headline in Simplified Chinese, under 25 chars. No jargon.",
            },
            "summary_zh": {
                "type": "string",
                "description": "2-4 sentences in Simplified Chinese. Plain language a retiree could follow. Explain any financial term used.",
            },
            "affected_industries_zh": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Industries affected, in Chinese (e.g. 半导体, 房地产, 新能源车, 银行, 消费). Max 4.",
            },
            "shanghai_impact": {
                "type": "string",
                "enum": ["bullish", "bearish", "mixed", "neutral"],
                "description": "Directional bias for Shanghai A-shares / CSI 300 overall.",
            },
            "shanghai_impact_reason_zh": {
                "type": "string",
                "description": "One sentence in Chinese explaining why Shanghai market reacts this way.",
            },
            "watchlist_zh": {
                "type": "array",
                "items": {"type": "string"},
                "description": "2-4 specific A-share / HK / ETF names to watch, formatted as '中文名 (代码)'. e.g. '比亚迪 (002594.SZ)', '台积电 (2330.TW)', '沪深300ETF (510300.SH)'. Only names plausibly tied to the event.",
            },
            "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
            "horizon_days": {
                "type": "integer",
                "description": "How long this effect persists, in days.",
            },
        },
        "required": ["title_zh", "summary_zh", "affected_industries_zh", "shanghai_impact", "shanghai_impact_reason_zh", "confidence"],
    },
}

MOM_SYSTEM = """你是一位财经分析师，为一位非专业的中国投资者（比如一位退休人士）撰写每日市场速报。

你收到1条或多条今天发生的、对中国/上海股市有直接或间接影响的全球宏观事件。你的任务：
1. 用简体中文写一份清晰、简短的摘要，让普通人能读懂。
2. 明确指出受影响的行业（用中文表达，不要用英文缩写）。
3. 给出对上海A股市场的方向性判断（看涨/看跌/混合/中性）。
4. 推荐2-4只相关的A股/港股/ETF。使用公司中文名称加股票代码，例如"比亚迪 (002594.SZ)"。

## 风格要求
- 语言通俗易懂。不用"点位"、"流动性"、"久期"这类术语，除非紧接着用日常语言解释。
- 句子短、有力。不用"或许"、"可能"、"似乎"这类模糊措辞。
- 不捏造。如果事件跟中国关联较弱，标记为"混合"或"中性"，置信度选"low"。
- 推荐的标的必须与事件有明确因果逻辑。不要胡乱推荐。

## 请勿
- 不要用繁体字。
- 不要出现"投资建议"字样——这不是投资建议，是事件速报。
- 不要重复事件原文；你在做的是解读，不是转述。
"""


def _format_user(qualifying_events: list[dict]) -> str:
    payload = {
        "events": [
            {
                "event_summary": e.get("event_summary", ""),
                "headlines": e.get("headlines", []),
                "primary_drivers": e.get("primary_drivers", []),
                "beneficiaries": e.get("beneficiaries", []),
                "losers": e.get("losers", []),
            }
            for e in qualifying_events
        ]
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)


def _audit(payload: dict, response: dict | None, error: str | None) -> None:
    now = datetime.now(timezone.utc)
    day_dir = AUDIT_DIR / now.strftime("%Y-%m-%d")
    day_dir.mkdir(parents=True, exist_ok=True)
    path = day_dir / f"mom_digest_{now.strftime('%H%M%S')}.json"
    path.write_text(
        json.dumps(
            {"ts": now.isoformat(), "payload": payload, "response": response, "error": error},
            indent=2, ensure_ascii=False,
        )
    )


def _build_card(digest: dict) -> dict:
    industries = "、".join(digest.get("affected_industries_zh", []))
    watchlist = "\n".join(f"  • {w}" for w in digest.get("watchlist_zh", []))
    impact_map = {"bullish": "偏多", "bearish": "偏空", "mixed": "混合", "neutral": "中性"}
    impact_label = impact_map.get(digest.get("shanghai_impact", ""), "未知")

    body = (
        f"**{digest.get('summary_zh', '')}**\n\n"
        f"**受影响行业：** {industries}\n\n"
        f"**上海A股方向：** {impact_label} · {digest.get('shanghai_impact_reason_zh', '')}"
    )
    if watchlist:
        body += f"\n\n**建议关注：**\n{watchlist}"
    body += f"\n\n_置信度：{digest.get('confidence', '—')} · 预计持续：{digest.get('horizon_days', '—')} 天_"

    template_map = {"bullish": "green", "bearish": "red", "mixed": "orange", "neutral": "blue"}
    template = template_map.get(digest.get("shanghai_impact", ""), "blue")

    return {
        "msg_type": "interactive",
        "card": {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": f"📰 {digest.get('title_zh', '宏观速报')}"},
                "template": template,
            },
            "elements": [{"tag": "div", "text": {"tag": "lark_md", "content": body}}],
        },
    }


def _send(webhook_url: str, card: dict) -> tuple[bool, dict | None, str | None]:
    try:
        resp = requests.post(webhook_url, json=card, timeout=10)
        body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {"text": resp.text}
        if resp.status_code == 200 and body.get("StatusCode") in (0, None):
            return True, body, None
        return False, body, f"HTTP {resp.status_code}"
    except requests.RequestException as e:
        return False, None, str(e)


def run(macro_analyses: list[dict], client: LLMClient | None) -> None:
    webhook = getattr(config, "FEISHU_MOM_WEBHOOK_URL", None)
    if not webhook:
        return  # disabled — no config
    if not client:
        log.info("Mom digest: no LLM client, skipping")
        return
    if not macro_analyses:
        return

    qualifying = []
    for m in macro_analyses:
        relevant, reason = _is_china_relevant(m)
        if relevant:
            qualifying.append(m)

    if not qualifying:
        log.info("Mom digest: no China-relevant macro events this scan")
        return

    # Throttle: don't re-send within THROTTLE_SECONDS, unless new dedup_group appears
    state = _load_throttle()
    last_sent_iso = state.get("last_sent_at")
    last_groups = set(state.get("last_groups", []))
    current_groups = {m.get("dedup_group") for m in qualifying}

    if last_sent_iso:
        try:
            last_sent = datetime.fromisoformat(last_sent_iso)
            age = (datetime.now(timezone.utc) - last_sent).total_seconds()
            if age < THROTTLE_SECONDS and current_groups.issubset(last_groups):
                log.info(
                    "Mom digest: throttled (sent %.0fm ago, same groups)",
                    age / 60,
                )
                return
        except Exception:
            pass

    # Call Opus for Chinese digest
    result = client.call_structured(
        model=config.OPUS_MODEL,
        system=MOM_SYSTEM,
        user=_format_user(qualifying),
        output_tool=MOM_DIGEST_TOOL,
        audit_tier="opus_mom",
        audit_key=hashlib.sha1(str(sorted(current_groups)).encode()).hexdigest()[:12],
        max_tokens=2048,
    )
    if not result:
        log.warning("Mom digest: Opus returned no result")
        return

    card = _build_card(result)
    ok, response, err = _send(webhook, card)
    _audit({"digest": result, "events": qualifying}, response, err)

    if ok:
        state["last_sent_at"] = datetime.now(timezone.utc).isoformat()
        state["last_groups"] = sorted(current_groups)
        _save_throttle(state)
        log.info("Mom digest sent: %s", result.get("title_zh"))
    else:
        log.warning("Mom digest send failed: %s", err)
