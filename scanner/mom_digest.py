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
    "description": "For a Chinese-reading non-professional audience, evaluate today's macro events (which may or may not mention China directly) and produce a Chinese digest covering only those with China/HK market implications.",
    "input_schema": {
        "type": "object",
        "properties": {
            "worth_sending": {
                "type": "boolean",
                "description": "True if at least one event has material (direct OR indirect) China/HK market implications worth alerting a retiree investor. False if ALL events are purely US-domestic with no plausible cross-border transmission.",
            },
            "events_considered_zh": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "headline_en": {"type": "string", "description": "Original event summary, English."},
                        "headline_zh": {"type": "string", "description": "Chinese translation/paraphrase of the event."},
                        "china_hk_relevance": {
                            "type": "string",
                            "enum": ["direct", "indirect", "minimal", "none"],
                            "description": "direct = names China/HK/yuan/Chinese company; indirect = Fed/tariff/commodity with cross-asset pull; minimal = weak theoretical link; none = US-only domestic issue.",
                        },
                        "relevance_reason_zh": {"type": "string", "description": "One sentence: how this affects China/HK markets, in Chinese."},
                    },
                    "required": ["headline_en", "headline_zh", "china_hk_relevance", "relevance_reason_zh"],
                },
                "description": "One entry per input event. Include ALL events, even 'none' — lets the user see you considered everything.",
            },
            "title_zh": {
                "type": "string",
                "description": "Headline covering the most important relevant event. Simplified Chinese, under 30 chars.",
            },
            "summary_zh": {
                "type": "string",
                "description": "3-5 sentences in Simplified Chinese. Cover the events with direct or indirect relevance. Plain language. Can reference multiple events if several are relevant.",
            },
            "affected_industries_zh": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Industries affected across all relevant events, Chinese (e.g. 半导体, 房地产, 新能源车, 银行, 消费, 能源, 航运). Max 5.",
            },
            "a_share_impact": {
                "type": "string",
                "enum": ["bullish", "bearish", "mixed", "neutral"],
                "description": "Net directional bias for A-shares across all relevant events.",
            },
            "hk_impact": {
                "type": "string",
                "enum": ["bullish", "bearish", "mixed", "neutral"],
                "description": "Net directional bias for HK market. A-shares and HK frequently diverge — judge independently.",
            },
            "markets_reason_zh": {
                "type": "string",
                "description": "Paragraph in Chinese explaining reasoning for BOTH A-shares and HK. Flag divergences.",
            },
            "watchlist_zh": {
                "type": "array",
                "items": {"type": "string"},
                "description": "3-5 specific A-share/HK/ETF names to watch, formatted '中文名 (代码)'. Mix .SH/.SZ and .HK. Examples: '比亚迪 (002594.SZ)', '腾讯控股 (0700.HK)', '恒生科技ETF (513180.SH)'.",
            },
            "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
            "horizon_days": {"type": "integer", "description": "How long these effects persist, in days."},
        },
        "required": ["worth_sending", "events_considered_zh", "title_zh", "summary_zh", "affected_industries_zh", "a_share_impact", "hk_impact", "markets_reason_zh", "confidence"],
    },
}

MOM_SYSTEM = """你是一位财经分析师，为一位非专业的中国投资者（比如一位退休人士）撰写市场速报。

你收到今天发生的1到5条全球宏观事件。这些事件**可能直接提到中国，也可能不提**——但许多全球宏观事件（美联储利率决议、关税政策、大宗商品波动、地缘政治等）都会通过跨市场传导影响A股和港股。

## 第一步：评估每一条事件

对每一条输入事件，在 events_considered_zh 中填入：
- headline_en: 原始英文标题
- headline_zh: 翻译成简体中文（不是逐字翻译，用自然中文改写）
- china_hk_relevance:
  * "direct" — 事件直接涉及中国/香港/人民币/中国公司（华为、腾讯、台积电等）
  * "indirect" — 事件间接影响中国/港股（例：美联储降息→港股估值提升；油价暴涨→中石油受益；美国对华关税→半导体供应链）
  * "minimal" — 理论上有微弱联系但实际影响不大
  * "none" — 纯美国本土事件，对中国/港股无传导效应（例：某个美国州的监管变化、与中国无关的美股个股财报）
- relevance_reason_zh: 一句中文解释该事件如何（或为何不）影响中国/港股

## 第二步：决定是否发送

如果**所有**事件都是 "none"（纯美国本土），设置 worth_sending=false，其他字段可以简略或留空。不发送给妈妈。

如果**至少一条**事件是 direct/indirect/minimal（有任何传导可能），设置 worth_sending=true，然后根据这些相关事件撰写：
- title_zh: 最重要一条事件的中文标题
- summary_zh: 综合所有相关事件写3-5句中文摘要，普通人能读懂
- affected_industries_zh: 跨所有相关事件受影响的行业
- a_share_impact / hk_impact: 分别判断两个市场方向
  * A股（上证、沪深300）以内资为主，主要受国内政策驱动
  * 港股（恒生、恒生科技）有大量外资，对美联储、汇率、全球流动性更敏感
  * 两个市场经常分化——分别独立判断
- markets_reason_zh: 综合解释两个市场的反应，分化时说明原因
- watchlist_zh: 3-5只具体标的，混合A股和港股，例如"腾讯控股 (0700.HK)"、"比亚迪 (002594.SZ)"

## 风格要求

- 简体字，不用繁体。
- 通俗易懂。不用"点位"、"流动性"、"久期"等术语，除非紧接着用日常语言解释。
- 不捏造。关联弱就选 minimal，整体偏弱就设 confidence=low。
- 不要出现"投资建议"字样——这是事件速报，不是推荐。
- 不重复事件原文；你在做的是解读和翻译。
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
    impact_map = {"bullish": "偏多 📈", "bearish": "偏空 📉", "mixed": "混合 ⚖️", "neutral": "中性 ➖"}
    a_label = impact_map.get(digest.get("a_share_impact", ""), "未知")
    hk_label = impact_map.get(digest.get("hk_impact", ""), "未知")

    # Show each event's translated headline with its relevance tag so mom
    # sees both the original news AND why it matters (or doesn't) for China/HK.
    relevance_labels = {
        "direct": "🎯 直接相关",
        "indirect": "🔗 间接影响",
        "minimal": "〰️ 弱关联",
        "none": "➖ 无关",
    }
    events_block = ""
    for e in digest.get("events_considered_zh", []):
        rel = e.get("china_hk_relevance", "none")
        if rel == "none":
            continue  # mom doesn't need to see irrelevant ones
        tag = relevance_labels.get(rel, rel)
        events_block += (
            f"\n{tag} **{e.get('headline_zh', '')}**\n"
            f"  _{e.get('relevance_reason_zh', '')}_\n"
        )

    body = f"{digest.get('summary_zh', '')}\n"
    if events_block:
        body += f"\n**今日事件：**{events_block}"
    body += (
        f"\n**受影响行业：** {industries}\n\n"
        f"**A股方向：** {a_label}\n"
        f"**港股方向：** {hk_label}\n\n"
        f"**市场逻辑：** {digest.get('markets_reason_zh', '')}"
    )
    if watchlist:
        body += f"\n\n**建议关注：**\n{watchlist}"
    body += f"\n\n_置信度：{digest.get('confidence', '—')} · 预计持续：{digest.get('horizon_days', '—')} 天_"

    # Card header color: worst-case directional signal across both markets.
    a, h = digest.get("a_share_impact", ""), digest.get("hk_impact", "")
    if a == "bullish" and h == "bullish":
        template = "green"
    elif a == "bearish" and h == "bearish":
        template = "red"
    elif "bullish" in (a, h) and "bearish" in (a, h):
        template = "orange"  # divergence
    elif "bearish" in (a, h):
        template = "red"
    elif "bullish" in (a, h):
        template = "green"
    else:
        template = "blue"

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

    # Send ALL macro events to Opus — it gatekeeps per-event relevance itself.
    # Direct keyword short-circuit just for logging visibility.
    for m in macro_analyses:
        relevant, _ = _is_china_relevant(m)
        summary_preview = (m.get("event_summary", "") or "")[:70]
        log.info(
            "Mom digest pre-check: %s '%s...'",
            "[direct China keyword]" if relevant else "[no direct China kw — Opus will judge indirect]",
            summary_preview,
        )
    qualifying = list(macro_analyses)
    log.info("Mom digest: sending %d events to Opus for Chinese relevance judgment", len(qualifying))

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
        max_tokens=3072,
    )
    if not result:
        log.warning("Mom digest: Opus returned no result")
        return

    if not result.get("worth_sending", False):
        # Log each event's relevance call for observability.
        for e in result.get("events_considered_zh", []):
            log.info(
                "Mom digest: Opus judged '%s' → %s (%s)",
                (e.get("headline_en", "") or "")[:50],
                e.get("china_hk_relevance", "?"),
                (e.get("relevance_reason_zh", "") or "")[:60],
            )
        log.info("Mom digest: Opus judged no events worth sending — skipping")
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
