"""Scanner entry point. Runs on a schedule from GitHub Actions.

Flow per scan:
  1. detect window
  2. load universe (rebuild if stale)
  3. if equity window: pull technicals, compute deltas
  4. route tickers (rules-based Tier 0)
  5. fetch news: Finviz for routed tickers + macro RSS
  6. Tier 1 (Haiku): classify + dedup
  7. Tier 2 (Sonnet): per-ticker "why" synthesis
  8. Tier 3 (Opus): macro \u2192 beneficiary analysis
  9. write data/scan.json + data/news.json + data/deltas.json

LLM tiers degrade gracefully if ANTHROPIC_API_KEY is missing.

    python -m scanner.main                # normal run
    python -m scanner.main --rebuild-universe
    python -m scanner.main --limit 50     # dev: scan a small subset
    python -m scanner.main --force        # ignore window (always scan)
    python -m scanner.main --no-llm       # skip all LLM tiers
    python -m scanner.main --no-news      # skip news ingestion + LLM entirely
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime

from scanner import briefing, catalysts, config, deals, desk, levels as levels_mod, mom_digest, mom_watchlist, news, opening, performance, political, recommend, regime as regime_mod, render, risk, router, serenity, state, technicals, trump_pulse, universe, weekly_events, windows
from scanner.alerts import feishu
from scanner.alerts import rules as alert_rules
from scanner.llm import classify, macro, ripple, synthesize
from scanner.llm.client import get_client

log = logging.getLogger("scanner")

# Reference account equity for position sizing (scanner.risk). The risk module's
# outputs are fractions of this base (pct_of_equity etc.), so this only sets the
# absolute scale of the suggested share count / notional shown alongside a pick —
# it is NOT a live brokerage balance. Anchored to David's ~£12k ISA (memory).
SIZING_REFERENCE_EQUITY = 12_000.0


def _rank_news_for_haiku(
    ticker_news: dict[str, list[dict]],
    macro_news: list[dict],
    rows: list[dict],
) -> list[dict]:
    """Score each news item so that if we hit the Haiku cap, we classify the
    most informative items first (bigger movers, macro)."""
    by_ticker = {r["ticker"]: r for r in rows}

    def score(item: dict) -> float:
        if item.get("scope") == "macro":
            return 40.0  # all macro gets classified before low-signal ticker news
        t = item.get("ticker")
        s = 0.0
        row = by_ticker.get(t or "")
        if row:
            pct = abs(row.get("pct_1d") or 0)
            s += pct * 2
            rv = row.get("rel_volume") or 0
            s += min(rv, 10)
        return s

    all_items = [n for items in ticker_news.values() for n in items] + macro_news
    all_items.sort(key=score, reverse=True)
    return all_items


def _rank_synthesis_targets(
    candidates: set[str],
    ticker_news_enriched: dict[str, list[dict]],
    rows: list[dict],
) -> list[str]:
    """Order synthesis candidates by priority. Big movers with news first, then
    big movers, then rest."""
    by_ticker = {r["ticker"]: r for r in rows}

    def score(t: str) -> float:
        s = 0.0
        row = by_ticker.get(t)
        if row:
            s += abs(row.get("pct_1d") or 0) * 10
            s += min(row.get("rel_volume") or 0, 10) * 5
            flags = row.get("flags", []) or []
            if "big_move" in flags:
                s += 20
            if "unusual_volume" in flags:
                s += 15
        news_items = ticker_news_enriched.get(t, [])
        if any(n.get("impact") == "high" for n in news_items):
            s += 40
        return s

    return sorted(candidates, key=score, reverse=True)


def run(
    limit: int | None = None,
    rebuild_universe: bool = False,
    force: bool = False,
    use_llm: bool = True,
    use_news: bool = True,
    use_alerts: bool = True,
) -> int:
    now = datetime.now(config.MARKET_TZ)
    window = windows.detect(now)
    log.info("Market window: %s at %s", window.value, now.isoformat())

    # Always run the technicals scan so the UI shows prices even off-hours.
    # yfinance returns the last available close on weekends, and Tier 0 routing
    # filters out non-movers before any LLM cost is incurred.
    tickers = universe.load(force_rebuild=rebuild_universe)
    # Prioritize S&P 500 + NDX before any partial-scan limit kicks in, so a small
    # --limit run still surfaces the most informative names.
    tickers = universe.prioritize(tickers)
    if limit:
        tickers = tickers[:limit]
    uni_size = len(tickers)
    log.info("Loaded universe: %d tickers", uni_size)
    rows = technicals.scan(tickers)

    deltas = state.compute_and_persist(rows, now)

    routed = router.route(rows, deltas, window) if rows else []

    # Opening catch-list (scanner.opening): once per trading day, on the first
    # RTH scan after the open. When it's due, widen the snapshot pass to the
    # whole popular universe so FRESH gappers — which the router (keyed off
    # yesterday's tape) would otherwise never enrich — get a gap read and
    # intraday bars. Normal scans keep the cheap routed-only behavior.
    run_catch = opening.should_run_today(now, window)

    # Pre-market gap + intraday VWAP/HOD/LOD for routed tickers only
    # (cheap because Tier 0 already cut us down to ~50-200 names).
    routed_for_intraday = sorted(set(routed))
    snapshot_targets = set(routed_for_intraday)
    if run_catch:
        snapshot_targets |= universe.popular()
    snapshots: dict[str, dict] = {}
    intraday: dict[str, dict] = {}
    if snapshot_targets:
        snapshots = technicals.fetch_snapshots(sorted(snapshot_targets))
        if run_catch:
            gappers = opening.gapper_candidates(snapshots)
            if gappers:
                routed_for_intraday = sorted(set(routed_for_intraday) | set(gappers))
                log.info("Catch list: %d fresh gappers admitted for intraday", len(gappers))
        if window in (windows.Window.RTH, windows.Window.AH_PRE, windows.Window.AH_POST):
            intraday = technicals.fetch_intraday(routed_for_intraday)

    ticker_news: dict[str, list[dict]] = {}
    macro_news: list[dict] = []
    if use_news:
        ticker_news, macro_news = news.ingest(routed)
    else:
        log.info("--no-news: skipping news ingestion + all LLM tiers")

    ticker_news_enriched: dict[str, list[dict]] = {}
    macro_news_enriched: list[dict] = []
    syntheses: dict[str, dict] = {}
    macro_analyses: list[dict] = []
    ripple_events: list[dict] = []
    ripple_predictions: list[dict] = []

    client = get_client() if (use_llm and use_news) else None
    if client and (ticker_news or macro_news):
        # --- Haiku budget: cap to MAX_HAIKU_NEWS_ITEMS_PER_SCAN ---
        all_items = _rank_news_for_haiku(ticker_news, macro_news, rows)
        if len(all_items) > config.MAX_HAIKU_NEWS_ITEMS_PER_SCAN:
            log.info(
                "Haiku budget: %d items → capping to %d",
                len(all_items), config.MAX_HAIKU_NEWS_ITEMS_PER_SCAN,
            )
            all_items = all_items[: config.MAX_HAIKU_NEWS_ITEMS_PER_SCAN]
        classifications = classify.classify(all_items, client)

        for ticker, items in ticker_news.items():
            ticker_news_enriched[ticker] = classify.attach(items, classifications)

        macro_news_enriched = classify.attach(macro_news, classifications)
        macro_news_dedup = classify.dedup(macro_news_enriched)

        # --- Sonnet budget: score tickers, cap at MAX_SONNET_SYNTHESES ---
        must_synth = set(deltas.get("new_top20_entrants", []))
        must_synth.update(j["ticker"] for j in deltas.get("rank_jumps", []))
        ranked_synth_targets = _rank_synthesis_targets(
            must_synth, ticker_news_enriched, rows,
        )[: config.MAX_SONNET_SYNTHESES_PER_SCAN]
        log.info(
            "Sonnet budget: %d candidates → synthesizing top %d",
            len(must_synth), len(ranked_synth_targets),
        )
        syntheses = synthesize.synthesize(
            ticker_news_enriched,
            {r["ticker"]: r for r in rows},
            client,
            must_synthesize=set(ranked_synth_targets),
        )

        # --- Opus budget: high-impact macro only, capped ---
        # Opus is the priciest tier; medium-impact macro rarely justifies a
        # full beneficiary breakdown, so it no longer reaches this tier.
        macro_for_opus = [
            m for m in macro_news_dedup
            if m.get("impact") == "high" and (m.get("type") or "").startswith("macro_")
        ][: config.MAX_OPUS_MACRO_PER_SCAN]
        log.info(
            "Opus budget: analyzing top %d macro events (cap %d)",
            len(macro_for_opus), config.MAX_OPUS_MACRO_PER_SCAN,
        )
        macro_analyses = macro.analyze(macro_for_opus, client)

        # --- Ripple (Opus): forward second-order predictions from popular-stock
        # news. Who ELSE does this story help/hurt — before they move? Triggers
        # are gated to popular names (S&P 500 / NDX) and high-impact company
        # news, deduped per story and hard-capped, so the spend is small.
        popular = universe.popular()
        trigger_groups = ripple.select_trigger_events(
            ticker_news_enriched, popular, rows, config.MAX_RIPPLE_EVENTS_PER_SCAN,
        )
        ripple_events, ripple_predictions = ripple.analyze(trigger_groups, rows, client)
    else:
        ticker_news_enriched = ticker_news
        macro_news_enriched = macro_news

    news_count_by_ticker = {t: len(v) for t, v in ticker_news_enriched.items()}
    enriched_rows = render.enrich_rows(
        rows,
        syntheses_by_ticker=syntheses,
        news_count_by_ticker=news_count_by_ticker,
        snapshots_by_ticker=snapshots,
        intraday_by_ticker=intraday,
    )
    # Market regime snapshot — gates short picks in bull tape and tags every
    # logged outcome so future analysis can stratify by regime. Empty on any
    # Alpaca failure; downstream callers handle that gracefully.
    regime = regime_mod.compute()
    if regime:
        regime["window"] = window.value  # passthrough so the log carries it

    recommendations = recommend.compute(enriched_rows, regime=regime)

    # Trade levels (entry/support/stop/target/R:R) — deterministic, attached to
    # every pick so the PM agent can reference real numbers and the UI has one
    # source of truth. Runs regardless of LLM availability.
    levels_mod.attach_levels(recommendations, enriched_rows)

    # Position sizing (scanner.risk) — attach rec["risk"] to every surfaced pick.
    # Entry comes from the levels just attached (falling back to the row's live
    # price); the hard stop is risk.hard_stop (fixed 7-8% rule, no ATR on rows
    # yet). size_position is direction-agnostic, so longs and shorts size off the
    # absolute entry-stop distance. Fail-soft per pick — a degenerate price never
    # blocks the scan.
    _rows_by_ticker = {r["ticker"]: r for r in enriched_rows}
    for _side in ("longs", "shorts"):
        for _rec in recommendations.get(_side, []):
            _direction = _rec.get("direction", "long")
            _levels = _rec.get("levels") or {}
            _entry = _levels.get("entry")
            if _entry is None:
                _row = _rows_by_ticker.get(_rec.get("ticker")) or {}
                _entry = _row.get("price") or _row.get("last_close")
            if _entry is None:
                continue
            _stop = risk.hard_stop(_entry, _direction)
            _rec["risk"] = risk.size_position(SIZING_REFERENCE_EQUITY, _entry, _stop)
            _rec["hard_stop"] = _stop

    # Opening catch-list — the early-entry tier. Built off the enriched rows
    # (live snapshot price + opening-range VWAP), once per trading day. Skip the
    # write when no intraday bars landed yet so the next scan retries rather than
    # burning the once-a-day slot on empty data. Fail-soft — never blocks a scan.
    if run_catch:
        try:
            catch = opening.build_catch_list(enriched_rows, regime, now, window)
            if catch.get("_has_intraday"):
                opening.write_catch_list(catch, now)
                opening.log_catch_list(catch, now, regime=regime)
            else:
                log.info("Catch list: no intraday bars yet; will retry next scan")
        except Exception as e:
            log.warning("Catch list build raised: %s", e)

    # Tier-4 agent desk: review each pick through Signal/Research/Risk/PM and
    # attach rec["desk"]. Runs only when the LLM client is available; fails soft
    # so a desk error never blocks the scan. See docs/agent-desk.md.
    try:
        desk.review(recommendations, enriched_rows, regime, client)
    except Exception as e:
        log.warning("Desk review raised: %s", e)

    render.write_scan(enriched_rows, window, now, uni_size, recommendations=recommendations, regime=regime)
    performance.log_recommendations(recommendations, rows, now, regime=regime)
    performance.log_predictions(ripple_predictions, rows, now, regime=regime)

    # Log notable momentum events for the Saturday weekly summary.
    weekly_events.record(
        rows=rows,
        ticker_news=ticker_news_enriched,
        syntheses=syntheses,
        window=window.value,
        now=now,
    )
    render.write_news(ticker_news_enriched, macro_analyses, now)
    render.write_predictions(ripple_events, ripple_predictions, now)

    # Serenity (@aleabitoreddit) — the 24/7 poller (serenity-poll.yml) owns X
    # polling, Claude extraction, the Feishu push and writing data/serenity.json.
    # The scan only reads that feed and cross-references it against the live
    # universe to add serenity_match alerts (price coincidence). Fail-soft.
    # Skip the cross-reference entirely when the serenity_match stream is gated
    # off (Contract G). rules.build_alerts also drops these alerts defensively,
    # but short-circuiting here avoids the feed-load + match work when disabled.
    serenity_matches: list[dict] = []
    if config.SERENITY_MATCH_ENABLED:
        try:
            serenity_tweets = serenity.load_feed()
            if serenity_tweets:
                serenity_matches = serenity.compute_matches(
                    serenity_tweets, rows,
                )
        except Exception as e:
            log.warning("Serenity match raised: %s", e)

    alerts: list[dict] = []
    if use_alerts:
        alerts, throttle = alert_rules.build_alerts(
            rows, deltas, syntheses, macro_analyses, window,
            serenity_matches=serenity_matches,
            ripple_predictions=ripple_predictions,
        )
        # Dispatch honesty: only alerts that made it into a successfully-sent
        # card enter the 2h throttle cooldown and the performance log —
        # capped-out or failed-send alerts no longer count as "dispatched".
        sent_cards, dispatched = feishu.send_consolidated(alerts)
        alert_rules.record_dispatched(dispatched, throttle)
        log.info(
            "Alerts: built %d, dispatched %d in %d card(s)",
            len(alerts), len(dispatched), sent_cards,
        )
        performance.log_alerts(dispatched, rows, now, regime=regime)

    # Scan briefing: one Sonnet call condensing this scan into data/briefing.json
    # for the web front page. Fail-soft — never blocks the scan; on any error
    # the previous briefing.json stays in place.
    try:
        briefing.run(
            client=client,
            regime=regime,
            rows=enriched_rows,
            recommendations=recommendations,
            alerts=alerts,
            ripple_predictions=ripple_predictions,
            macro_analyses=macro_analyses,
            window=window,
            now=now,
        )
    except Exception as e:
        log.warning("Briefing raised: %s", e)

    # Mom digest: purely additive Chinese-language macro+industry digest to a
    # second Feishu webhook. No-op if FEISHU_MOM_WEBHOOK_URL isn't set.
    mom_digest.run(macro_analyses, client, rows=rows)

    # Political-trade feed: cheap external fetch, throttled to once every few
    # hours via the file's generated_at so we stay under FMP's 250/day cap.
    # Failure is silent — never blocks the scan.
    try:
        political.fetch_and_save()
    except Exception as e:
        log.warning("Political fetch raised: %s", e)

    # Trump pulse: Truth Social posts + Federal Register presidential documents.
    # Both sources are free. Same throttle as political so the dashboard's two
    # external feeds stay aligned. When alerts are on, ping Feishu for any FRESH
    # stock mention (deduped, never re-sent).
    try:
        from datetime import timezone as _tz2
        pulse_payload = trump_pulse.fetch_and_save()
        if use_alerts:
            trump_pulse.notify_fresh_mentions(
                pulse_payload, rows,
                datetime.now(_tz2.utc),
            )
    except Exception as e:
        log.warning("Trump pulse fetch/notify raised: %s", e)

    # Catalyst calendar (scanner.catalysts): the portfolio-driven forward event
    # calendar — next earnings / ex-dividend per holding + a US macro calendar +
    # the quarterly triple-witching (FMP + computed), with an Opus per-holding
    # trim/add read. Throttled (~12h) so FMP calls stay tiny and Opus regen is
    # rare; fail-soft. When alerts are on, ping Feishu for a near catalyst.
    try:
        cat_payload = catalysts.fetch_and_save(
            client=client, rows=enriched_rows, syntheses=syntheses, now=now,
        )
        if use_alerts and cat_payload:
            catalysts.notify_due_catalysts(cat_payload, now)
    except Exception as e:
        log.warning("Catalyst calendar raised: %s", e)

    # Evaluate past alerts + recommendations whose 1d/3d/5d horizons elapsed.
    from datetime import timezone as _tz
    _alpaca = getattr(technicals, "_CLIENT", None)
    _utc_now = datetime.now(_tz.utc)
    performance.evaluate_pending(_alpaca, _utc_now)
    performance.evaluate_pending_recommendations(_alpaca, _utc_now)
    performance.evaluate_pending_predictions(_alpaca, _utc_now)
    # Early-entry grading + stats are brand-new live-Alpaca paths; keep them
    # fail-soft so a first-run surprise can never break the scan or the ledger
    # write below.
    try:
        opening.evaluate_pending_early_entries(_alpaca, _utc_now)
    except Exception as e:
        log.warning("Early-entry eval raised: %s", e)
    performance.compile_stats(datetime.now(config.MARKET_TZ))
    performance.compile_recommendation_stats(datetime.now(config.MARKET_TZ))
    performance.compile_desk_stats(datetime.now(config.MARKET_TZ))
    performance.compile_prediction_stats(datetime.now(config.MARKET_TZ))
    try:
        opening.compile_early_entry_stats(datetime.now(config.MARKET_TZ))
    except Exception as e:
        log.warning("Early-entry stats raised: %s", e)
    # Mom 建议关注 (CN/HK) tracker — mark prior picks to market at 3/5/10 trading
    # days via Yahoo and roll up a hit-rate. Separate from the US Alpaca pipeline
    # above; fail-soft so it never blocks the scan.
    try:
        mom_watchlist.evaluate_and_compile(_utc_now)
    except Exception as e:
        log.warning("Mom watchlist eval raised: %s", e)
    # Public accountability ledger — the committed, permanent record of every
    # alert/pick/prediction (the .jsonl logs above live only in evictable
    # Actions caches). Written after evaluation so outcomes are fresh.
    ledger_payload = performance.write_ledger(datetime.now(_tz.utc))

    # Deal flow — surface this scan's ripple events as deals, paired with their
    # second-order prediction chain and the grades just written to the ledger.
    # Rolling window merged into data/deals.json; fail-soft so it never blocks
    # the scan. (ripple_events/ripple_predictions carry created_at from the
    # render.write_predictions call above.)
    try:
        deals.write_deals(
            datetime.now(_tz.utc),
            {"events": ripple_events, "predictions": ripple_predictions},
            ledger_payload,
        )
    except Exception as e:
        log.warning("Deal flow write raised: %s", e)

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Momentum scanner")
    parser.add_argument("--limit", type=int, default=None, help="Scan only first N tickers (dev)")
    parser.add_argument("--rebuild-universe", action="store_true", help="Force-rebuild universe.json")
    parser.add_argument("--force", action="store_true", help="Ignore market window and always scan")
    parser.add_argument("--no-llm", action="store_true", help="Skip LLM tiers (classify/synth/macro)")
    parser.add_argument("--no-news", action="store_true", help="Skip news ingestion + LLM entirely")
    parser.add_argument("--no-alerts", action="store_true", help="Build alerts but don't send to Feishu")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    return run(
        limit=args.limit,
        rebuild_universe=args.rebuild_universe,
        force=args.force,
        use_llm=not args.no_llm,
        use_news=not args.no_news,
        use_alerts=not args.no_alerts,
    )


if __name__ == "__main__":
    sys.exit(main())
