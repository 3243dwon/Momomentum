"""Alert decision engine.

Composes alerts from scan rows, deltas, ticker syntheses, and macro analyses.
Each candidate alert is checked against the throttle before being emitted.
After building, the full list is ranked by priority and truncated to
config.MAX_ALERTS_PER_SCAN so Feishu doesn't flood on noisy days.

Alert types fired (matched to design):
  A. Catalyst       \u2014 news-explained move + volume (highest priority)
  B. Macro          \u2014 macro event with beneficiary analysis
  C. Threshold      \u2014 watchlist move, big move + volume spike
  D. Delta          \u2014 new top-20 entrant, rank jump, momentum acceleration
"""
from __future__ import annotations

import logging
import os

from scanner import config, router
from scanner.alerts.throttle import Throttle
from scanner.windows import Window

log = logging.getLogger(__name__)

# Ticker-bearing alerts deep-link to the scanner's own ticker page, which
# carries the full rationale/sources; the push body stays one line.
_SITE_URL = os.environ.get("SITE_URL", "https://momomentum.vercel.app")

ALERT_TYPE_PRIORITY = {
    "catalyst": 100,
    "ripple": 95,
    "macro": 90,
    "serenity_match": 85,
    "watchlist": 80,
    "big_move": 60,
    "delta_new_top20": 45,
    "delta_rank_jump": 40,
    "delta_accel": 35,
}


def _score_alert(alert: dict) -> float:
    base = ALERT_TYPE_PRIORITY.get(alert.get("type", "").split(":")[0], 0)
    signal = alert.get("_signal_abs")
    if signal is not None:
        base += min(signal, 20)  # magnitude tiebreaker, capped so type dominates
    return base


def _cap_by_type(alerts: list[dict], alert_type: str, cap: int) -> tuple[list[dict], int]:
    """Trim a single always-fire alert type to at most `cap`, keeping the
    strongest by _score_alert. Returns (kept_alerts, dropped_count) where
    kept_alerts is the input list with the over-cap entries of `alert_type`
    removed (all other types untouched, original order preserved). Filters by
    reference — the surviving dicts are the same objects, so record_dispatched()
    can still pop their `_signal_abs`. cap < 0 disables the cap."""
    if cap < 0:
        return alerts, 0
    matching = [a for a in alerts if a.get("type") == alert_type]
    if len(matching) <= cap:
        return alerts, 0
    keep = set(id(a) for a in sorted(matching, key=_score_alert, reverse=True)[:cap])
    kept = [a for a in alerts if a.get("type") != alert_type or id(a) in keep]
    return kept, len(matching) - cap


def _fmt_pct(x: float | None) -> str:
    if x is None:
        return "?"
    sign = "+" if x >= 0 else ""
    return f"{sign}{x:.1f}%"


def _clip(s: str, n: int) -> str:
    """Word-boundary truncate with an ellipsis. Shared by every Feishu string
    builder (alerts, serenity, trump_pulse, weekly) — pushes are headlines,
    full rationales live on the website."""
    s = (s or "").strip()
    if len(s) <= n:
        return s
    cut = s[: max(1, n - 1)]
    sp = cut.rfind(" ")
    if sp > n // 2:
        cut = cut[:sp]
    return cut.rstrip(" ,;:·-—") + "…"


def _line(
    ticker: str,
    pct: float | None,
    suffix: str,
    rel_vol: float | None,
    thesis: str | None,
    qualifier: str | None = None,
) -> str:
    """One-line alert body: `**TICK +5.5%** 2.8x · *thesis* [→](deep link)`.
    Rel volume only when notable (>=1.5x). Thesis (italic, clipped ~110) when a
    synthesis exists; else an optional 2-3 word qualifier; else just the move."""
    head = f"**{ticker} {_fmt_pct(pct)}{suffix}**"
    if rel_vol and rel_vol >= 1.5:
        head += f" {rel_vol:.1f}x"
    if thesis:
        head += f" · *{_clip(thesis, 110)}*"
    elif qualifier:
        head += f" · {qualifier}"
    return head + f" [→]({_SITE_URL}/t/{ticker})"


def _macro_side(items: list[dict]) -> str:
    """`**T1** (short reason) · **T2** (short reason) · **T3** · ...` — top 2
    get a clipped parenthetical reason, the rest bare tickers, cap 5."""
    parts: list[str] = []
    for i, x in enumerate(items[:5]):
        if i < 2 and x.get("rationale"):
            parts.append(f"**{x['ticker']}** ({_clip(x['rationale'], 25)})")
        else:
            parts.append(f"**{x['ticker']}**")
    return " · ".join(parts)


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
    extra: dict | None = None,
) -> None:
    key_id = ticker or alert_type
    if not throttle.allowed(key_id, alert_type, signal_pct=signal):
        return
    # In-run dedup: the throttle used to be recorded at build time, which also
    # blocked same-scan duplicates. Recording now happens only after a
    # successful dispatch (see record_dispatched), so guard here instead.
    if any(a.get("ticker") == ticker and a.get("type") == alert_type for a in out):
        return
    alert = {
        "ticker": ticker,
        "type": alert_type,
        "title": title,
        # Ticker alerts always deep-link to the scanner's ticker page.
        "link": f"{_SITE_URL}/t/{ticker}" if ticker else link,
        "body_md": body_md,
        "_signal_abs": abs(signal) if signal is not None else None,
    }
    if extra:
        alert.update(extra)
    out.append(alert)


def build_alerts(
    rows: list[dict],
    deltas: dict,
    syntheses: dict[str, dict],
    macro_analyses: list[dict],
    window: Window,
    serenity_matches: list[dict] | None = None,
    ripple_predictions: list[dict] | None = None,
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

    # === A0. Catalyst alerts (highest priority) ===
    # Synthesis with high/medium confidence + verdict=news_explains_move on a
    # ticker also showing big_move or unusual_volume = pro-grade catalyst signal.
    for r in rows:
        t = r["ticker"]
        synth = syntheses.get(t)
        if not synth:
            continue
        if synth.get("verdict") != "news_explains_move":
            continue
        if synth.get("confidence") not in ("high", "medium"):
            continue
        flags = r.get("flags", []) or []
        if "big_move" not in flags and "unusual_volume" not in flags:
            continue
        pct = r.get("pct_1d") or 0
        rel_vol = r.get("rel_volume") or 0
        thesis = synth.get("summary", "")
        title = (
            f"🎯 {t} {_fmt_pct(pct)} · {_clip(thesis, 40)}"
            if thesis else f"🎯 {t} {_fmt_pct(pct)} catalyst"
        )
        _emit(
            alerts, throttle,
            ticker=t, alert_type="catalyst",
            title=_clip(title, 60),
            body_md=_line(t, pct, suffix, rel_vol, thesis),
            signal=pct,
        )

    # === A. Threshold alerts ===
    for r in rows:
        t = r["ticker"]
        pct = r.get("pct_1d") or 0
        rel_vol = r.get("rel_volume") or 0
        vol = r.get("volume") or 0

        if t in watchlist and abs(pct) >= config.WATCHLIST_ALERT_MIN_MOVE_PCT:
            synth = syntheses.get(t, {}).get("summary")
            title = f"⭐ {t} {_fmt_pct(pct)}" + (f" · {_clip(synth, 40)}" if synth else " watchlist")
            _emit(
                alerts, throttle,
                ticker=t, alert_type="watchlist",
                title=_clip(title, 60),
                body_md=_line(t, pct, suffix, rel_vol, synth),
                signal=pct,
            )
            continue

        if abs(pct) >= pct_threshold and rel_vol >= config.REL_VOLUME_THRESHOLD and vol >= ah_min_volume:
            # Gate: raw big movers without supporting signal are noise (perf
            # data Apr-May 2026: 1106 fired, 47.7% 5d hit rate, +0.25% avg).
            # Require ONE of:
            #   - any synthesis (the news pipeline thought this was worth
            #     explaining — already a quality filter)
            #   - extreme volume (≥ 3× avg, not just the ≥ 2× threshold)
            # AND not "stretched" (already late). A confirmed catalyst would
            # have fired as type=catalyst above; this branch handles the
            # second-tier confirmation.
            synth_full = syntheses.get(t) or {}
            has_synthesis = bool(synth_full)
            extreme_volume = rel_vol >= 3.0
            stretched = r.get("caution_level") == "stretched"
            if stretched or not (has_synthesis or extreme_volume):
                continue

            synth = synth_full.get("summary")
            title = f"🚀 {t} {_fmt_pct(pct)}" + (
                f" · {_clip(synth, 40)}" if synth else f" on {rel_vol:.1f}x vol"
            )
            _emit(
                alerts, throttle,
                ticker=t, alert_type="big_move",
                title=_clip(title, 60),
                body_md=_line(t, pct, suffix, rel_vol, synth),
                signal=pct,
            )

    # === B. Delta alerts (DISABLED) ===
    # Pure movers-leaderboard mechanics (entered top-20 / jumped ranks /
    # 3-scan acceleration) with no catalyst attached — the lowest-signal
    # alerts in the system. Trimmed to quiet the Feishu channel; a move that
    # actually matters still surfaces as a `catalyst` or `big_move` alert.
    # Also gated by config.DELTA_ALERTS_ENABLED (default False, Contract G):
    # restoring the family requires BOTH un-commenting the three loops
    # (delta_new_top20 / delta_rank_jump / delta_accel) and flipping the flag
    # to True. Any future delta emit MUST stay behind `if config.DELTA_ALERTS_ENABLED:`.

    # === C. Macro alerts ===
    for analysis in macro_analyses:
        beneficiaries = analysis.get("beneficiaries", [])[:5]
        losers = analysis.get("losers", [])[:5]
        if not beneficiaries and not losers:
            continue
        lines = [f"🌍 **{_clip(analysis.get('event_summary', ''), 90)}**"]
        if beneficiaries:
            lines.append(f"Wins: {_macro_side(beneficiaries)}")
        if losers:
            lines.append(f"Risks: {_macro_side(losers)}")

        group_id = analysis.get("dedup_group", "macro")
        _emit(
            alerts, throttle,
            ticker=None, alert_type=f"macro:{group_id}"[:60],
            title=_clip(f"🌍 {analysis.get('event_summary', '')}", 60),
            body_md="\n".join(lines),
        )

    # === D. Serenity matches (high-signal, always fires) ===
    # Serenity (@aleabitoreddit) named a ticker that is ALSO moving or on the
    # watchlist this scan — rare and high-conviction. This is additive to
    # lengjing's per-tweet Feishu ping (which fires for every tweet regardless of
    # price); here we only ping when his call coincides with a live move.
    for m in serenity_matches or []:
        # Gating (Contract G): kill-switch for the whole stream, plus a raised
        # move floor (up from the 3.0 hot-move floor in serenity.compute_matches).
        # Drop watchlist-only names with no live move (pct_1d None) — the noisy
        # case — and anything moving less than the throttle threshold.
        if not config.SERENITY_MATCH_ENABLED:
            continue
        if m.get("pct_1d") is None or abs(m["pct_1d"]) < config.SERENITY_MATCH_MIN_MOVE_PCT:
            continue
        t = m["ticker"]
        pct = m.get("pct_1d")
        stance = m.get("stance", "neutral")
        stance_str = {"bull": "🟢bull", "bear": "🔴bear"}.get(stance, "⚪")
        body = f"🧠 **{t} {_fmt_pct(pct)}{suffix}** {stance_str}"
        summary = m.get("summary", "")
        if summary:
            body += f" · *{_clip(summary, 110)}*"
        url = m.get("url")
        if url:
            body += f" [post]({url})"
        body += f" [→]({_SITE_URL}/t/{t})"
        _emit(
            alerts, throttle,
            ticker=t, alert_type="serenity_match",
            title=_clip(f"🧠 Serenity {t} {_fmt_pct(pct)} {stance_str}", 60),
            body_md=body, signal=pct,
            extra={"stance": stance},  # thesis direction for performance logging
        )

    # === E. Ripple predictions (forward second-order, high-signal) ===
    # The ripple tier predicted these names will move on ANOTHER company's news.
    # Push only the ones that HAVEN'T moved yet (priced_in == "no") with real
    # confidence — those are the calls still actionable ("report before"). The
    # already-moved ones still render on the web, but pushing them would just be
    # late news. Always-fire (this tier is the differentiator).
    ripple_pushed = 0
    for p in ripple_predictions or []:
        if p.get("priced_in") != "no":
            continue
        if p.get("confidence") not in ("high", "medium"):
            continue
        if ripple_pushed >= 6:
            break
        t = p["ticker"]
        bullish = p.get("direction") == "bullish"
        arrow = "📈" if bullish else "📉"
        pct = p.get("pct_1d")
        trigger = p.get("trigger_ticker")
        body = f"🔮 **{t}** {arrow} via {trigger}"
        rationale = p.get("rationale", "")
        if rationale:
            body += f" · *{_clip(rationale, 100)}*"
        # Directional call + confidence/horizon stay inline (accountability),
        # full rationale + trigger event + source live on /t/{ticker}.
        body += f" · {p.get('confidence')} {p.get('horizon')} [→]({_SITE_URL}/t/{t})"
        _emit(
            alerts, throttle,
            ticker=t, alert_type="ripple",
            title=_clip(f"🔮 {t} {arrow} via {trigger}", 60),
            body_md=body, signal=pct if pct is not None else 0.0,
            extra={"direction": p.get("direction")},  # thesis direction for perf logging
        )
        ripple_pushed += 1

    # Two-tier cap:
    #   - High-conviction (catalyst, macro:*, watchlist) always fires — if Sonnet
    #     or Opus surfaced it as a real signal, you should never miss it.
    #   - Standard (big_move, delta_*) is capped by signal magnitude so heavy
    #     broad-market move days don't flood the Feishu channel.
    high_conviction_types = {"catalyst", "watchlist", "serenity_match", "ripple"}
    high, standard = [], []
    for a in alerts:
        t = a.get("type", "")
        if t in high_conviction_types or t.startswith("macro:"):
            high.append(a)
        else:
            standard.append(a)

    # Gating (Contract G): per-type caps on the always-fire bucket. watchlist
    # and serenity_match bypass MAX_STANDARD_ALERTS_PER_SCAN, so they get their
    # own caps here, ranked by _score_alert (strongest survive). catalyst /
    # macro:* / ripple are NOT capped — they are the system's differentiators.
    high, wl_dropped = _cap_by_type(high, "watchlist", config.WATCHLIST_MAX_PER_SCAN)
    high, sm_dropped = _cap_by_type(high, "serenity_match", config.SERENITY_MATCH_MAX_PER_SCAN)

    standard.sort(key=_score_alert, reverse=True)
    dropped = max(0, len(standard) - config.MAX_STANDARD_ALERTS_PER_SCAN)
    standard = standard[: config.MAX_STANDARD_ALERTS_PER_SCAN]

    # High-conviction first so they render at top of any notification stack.
    # NOTE: `_signal_abs` stays on the dicts — record_dispatched() needs it to
    # write the throttle entry after a successful Feishu send, and pops it then.
    final = high + standard

    log.info(
        "Alerts: %d total (%d high-conviction always-fire [watchlist −%d, serenity −%d by per-type cap], "
        "%d standard kept, %d standard dropped by cap %d)",
        len(final), len(high), wl_dropped, sm_dropped,
        len(standard), dropped, config.MAX_STANDARD_ALERTS_PER_SCAN,
    )
    return final, throttle


def record_dispatched(alerts: list[dict], throttle: Throttle) -> None:
    """Record cooldowns for the alerts that actually made it into a
    successfully-sent dispatch, then persist the throttle state.

    Throttle entries used to be written at BUILD time, so alerts that were
    capped out of the standard list or whose Feishu send failed still entered
    the 2h cooldown (and the performance log). Call this with only the alerts
    feishu.send_consolidated() reported as delivered."""
    for a in alerts:
        key_id = a.get("ticker") or a.get("type", "")
        throttle.record(key_id, a.get("type", ""), signal_pct=a.pop("_signal_abs", None))
    throttle.commit()
