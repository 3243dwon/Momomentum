"""Alert decision engine.

Composes alerts from scan rows, deltas, ticker syntheses, and macro analyses.
Each candidate alert is checked against the throttle before being emitted.

Alert types fired (matched to design):
  A. Threshold      \u2014 watchlist move, big move + volume spike, fresh news
  B. Delta          \u2014 new top-20 entrant, rank jump, momentum acceleration
  C. Macro          \u2014 macro event with beneficiary analysis
  S. Synthesis      \u2014 high-confidence Sonnet "why" worth surfacing
"""
from __future__ import annotations

import logging

from scanner import config, router
from scanner.alerts.throttle import Throttle
from scanner.windows import Window

log = logging.getLogger(__name__)


def _fmt_pct(x: float | None) -> str:
    if x is None:
        return "?"
    sign = "+" if x >= 0 else ""
    return f"{sign}{x:.2f}%"


def _ah_suffix(window: Window) -> str:
    return " (AH)" if window in (Window.AH_PRE, Window.AH_POST) else ""


def _emit(
    out: list[dict],
    throttle: Throttle,
    *,
    ticker: str | None,
    alert_type: str,
    title: str,
    body_md: str,
    signal: float | None = None,
    link: str | None = None,
) -> None:
    key_id = ticker or alert_type
    if not throttle.allowed(key_id, alert_type, signal_pct=signal):
        return
    out.append(
        {
            "ticker": ticker,
            "type": alert_type,
            "title": title,
            "body_md": body_md,
            "link": link,
        }
    )
    throttle.record(key_id, alert_type, signal_pct=signal)


def build_alerts(
    rows: list[dict],
    deltas: dict,
    syntheses: dict[str, dict],
    macro_analyses: list[dict],
    window: Window,
) -> tuple[list[dict], Throttle]:
    throttle = Throttle()
    alerts: list[dict] = []

    watchlist = router.load_watchlist()
    by_ticker = {r["ticker"]: r for r in rows}

    pct_threshold = (
        config.PCT_MOVE_THRESHOLD_RTH
        if window == Window.RTH
        else config.PCT_MOVE_THRESHOLD_AH
    )
    ah_min_volume = config.MIN_AH_VOLUME if window in (Window.AH_PRE, Window.AH_POST) else 0
    suffix = _ah_suffix(window)

    # === A. Threshold alerts ===
    for r in rows:
        t = r["ticker"]
        pct = r.get("pct_1d") or 0
        rel_vol = r.get("rel_volume") or 0
        vol = r.get("volume") or 0

        if t in watchlist and abs(pct) >= 1.5:
            synth = syntheses.get(t, {}).get("summary")
            body = f"**{t}** {_fmt_pct(pct)}{suffix} on {rel_vol:.1f}x avg volume"
            if synth:
                body += f"\n\n*{synth}*"
            _emit(
                alerts, throttle,
                ticker=t, alert_type="watchlist",
                title=f"⭐ Watchlist: {t} {_fmt_pct(pct)}",
                body_md=body, signal=pct,
            )
            continue

        if abs(pct) >= pct_threshold and rel_vol >= config.REL_VOLUME_THRESHOLD and vol >= ah_min_volume:
            synth = syntheses.get(t, {}).get("summary")
            body = f"**{t}** {_fmt_pct(pct)}{suffix} on {rel_vol:.1f}x avg volume (RSI {r.get('rsi_14', '?')})"
            if synth:
                body += f"\n\n*{synth}*"
            _emit(
                alerts, throttle,
                ticker=t, alert_type="big_move",
                title=f"🚀 {t} {_fmt_pct(pct)} on heavy volume",
                body_md=body, signal=pct,
            )

    # === B. Delta alerts ===
    for t in deltas.get("new_top20_entrants", []):
        r = by_ticker.get(t, {})
        synth = syntheses.get(t, {}).get("summary")
        body = f"**{t}** entered top-20 movers at {_fmt_pct(r.get('pct_1d'))}{suffix}"
        if synth:
            body += f"\n\n*{synth}*"
        _emit(
            alerts, throttle,
            ticker=t, alert_type="delta_new_top20",
            title=f"📈 {t} broke into top-20 movers",
            body_md=body, signal=r.get("pct_1d"),
        )

    for jump in deltas.get("rank_jumps", []):
        t = jump["ticker"]
        r = by_ticker.get(t, {})
        body = (
            f"**{t}** jumped from #{jump['from']} to #{jump['to']} in top-20 "
            f"({_fmt_pct(r.get('pct_1d'))}{suffix})"
        )
        synth = syntheses.get(t, {}).get("summary")
        if synth:
            body += f"\n\n*{synth}*"
        _emit(
            alerts, throttle,
            ticker=t, alert_type="delta_rank_jump",
            title=f"⚡ {t} rank jump #{jump['from']} → #{jump['to']}",
            body_md=body, signal=r.get("pct_1d"),
        )

    for t in deltas.get("momentum_accel", []):
        r = by_ticker.get(t, {})
        body = f"**{t}** momentum accelerating across last 3 scans, now {_fmt_pct(r.get('pct_1d'))}{suffix}"
        _emit(
            alerts, throttle,
            ticker=t, alert_type="delta_accel",
            title=f"🌡️ {t} accelerating",
            body_md=body, signal=r.get("pct_1d"),
        )

    # === C. Macro alerts ===
    for analysis in macro_analyses:
        beneficiaries = analysis.get("beneficiaries", [])[:5]
        losers = analysis.get("losers", [])[:5]
        if not beneficiaries and not losers:
            continue
        b_lines = "\n".join(
            f"  • **{b['ticker']}** ({b['confidence']}): {b['rationale']}" for b in beneficiaries
        )
        l_lines = "\n".join(
            f"  • **{l['ticker']}** ({l['confidence']}): {l['rationale']}" for l in losers
        )
        body = f"**Event:** {analysis.get('event_summary', '')}\n\n"
        if beneficiaries:
            body += f"**Beneficiaries:**\n{b_lines}\n\n"
        if losers:
            body += f"**Losers:**\n{l_lines}"

        group_id = analysis.get("dedup_group", "macro")
        _emit(
            alerts, throttle,
            ticker=None, alert_type=f"macro:{group_id}"[:60],
            title=f"🌍 Macro: {analysis.get('event_summary', '')[:60]}",
            body_md=body,
        )

    log.info("Built %d alerts after throttling", len(alerts))
    return alerts, throttle
