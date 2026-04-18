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

from scanner import config, mom_digest, news, performance, render, router, state, technicals, universe, weekly_events, windows
from scanner.alerts import feishu
from scanner.alerts import rules as alert_rules
from scanner.llm import classify, macro, synthesize
from scanner.llm.client import get_client

log = logging.getLogger("scanner")


def _rank_news_for_haiku(
    ticker_news: dict[str, list[dict]],
    macro_news: list[dict],
    rows: list[dict],
    watchlist: set[str],
) -> list[dict]:
    """Score each news item so that if we hit the Haiku cap, we classify the
    most informative items first (bigger movers, watchlist, macro)."""
    by_ticker = {r["ticker"]: r for r in rows}

    def score(item: dict) -> float:
        if item.get("scope") == "macro":
            return 40.0  # all macro gets classified before low-signal ticker news
        t = item.get("ticker")
        s = 0.0
        if t in watchlist:
            s += 50
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
    watchlist: set[str],
) -> list[str]:
    """Order synthesis candidates by priority. Watchlist first, then big movers
    with news, then big movers, then rest."""
    by_ticker = {r["ticker"]: r for r in rows}

    def score(t: str) -> float:
        s = 0.0
        if t in watchlist:
            s += 200  # always synthesize watchlist first
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

    # Always run the technicals scan so the UI shows prices/watchlist even
    # off-hours. yfinance returns the last available close on weekends, and
    # Tier 0 routing filters out non-movers before any LLM cost is incurred.
    tickers = universe.load(force_rebuild=rebuild_universe)
    # Prioritize watchlist + S&P 500 + NDX before any partial-scan limit kicks in,
    # so a small --limit run still surfaces the most informative names.
    tickers = universe.prioritize(tickers, set(router.load_watchlist()))
    if limit:
        tickers = tickers[:limit]
    uni_size = len(tickers)
    log.info("Loaded universe: %d tickers", uni_size)
    rows = technicals.scan(tickers)

    deltas = state.compute_and_persist(rows, now)

    routed, watchlist = router.route(rows, deltas, window) if rows else ([], sorted(router.load_watchlist()))

    # Pre-market gap + intraday VWAP/HOD/LOD for routed tickers only
    # (cheap because Tier 0 already cut us down to ~50-200 names).
    routed_for_intraday = sorted(set(routed) | set(watchlist))
    snapshots: dict[str, dict] = {}
    intraday: dict[str, dict] = {}
    if routed_for_intraday:
        snapshots = technicals.fetch_snapshots(routed_for_intraday)
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

    client = get_client() if (use_llm and use_news) else None
    if client and (ticker_news or macro_news):
        # --- Haiku budget: cap to MAX_HAIKU_NEWS_ITEMS_PER_SCAN ---
        all_items = _rank_news_for_haiku(ticker_news, macro_news, rows, router.load_watchlist())
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
        scanned_tickers = {r["ticker"] for r in rows}
        watchlist_set = router.load_watchlist()
        must_synth = set(deltas.get("new_top20_entrants", []))
        must_synth.update(j["ticker"] for j in deltas.get("rank_jumps", []))
        must_synth.update(t for t in watchlist_set if t in scanned_tickers)
        ranked_synth_targets = _rank_synthesis_targets(
            must_synth, ticker_news_enriched, rows, watchlist_set,
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

        # --- Opus budget: cap macro events, sort by impact ---
        macro_for_opus = sorted(
            [
                m for m in macro_news_dedup
                if m.get("impact") in ("high", "medium") and (m.get("type") or "").startswith("macro_")
            ],
            key=lambda m: 0 if m.get("impact") == "high" else 1,
        )[: config.MAX_OPUS_MACRO_PER_SCAN]
        log.info(
            "Opus budget: analyzing top %d macro events (cap %d)",
            len(macro_for_opus), config.MAX_OPUS_MACRO_PER_SCAN,
        )
        macro_analyses = macro.analyze(macro_for_opus, client)
    else:
        ticker_news_enriched = ticker_news
        macro_news_enriched = macro_news

    news_count_by_ticker = {t: len(v) for t, v in ticker_news_enriched.items()}
    render.write_scan(
        rows, window, now, uni_size,
        syntheses_by_ticker=syntheses,
        news_count_by_ticker=news_count_by_ticker,
        snapshots_by_ticker=snapshots,
        intraday_by_ticker=intraday,
    )

    # Log notable momentum events for the Saturday weekly summary.
    weekly_events.record(
        rows=rows,
        ticker_news=ticker_news_enriched,
        syntheses=syntheses,
        window=window.value,
        now=now,
        watchlist=set(router.load_watchlist()),
    )
    render.write_news(ticker_news_enriched, macro_analyses, now)

    if use_alerts:
        alerts, throttle = alert_rules.build_alerts(rows, deltas, syntheses, macro_analyses, window)
        sent = feishu.send_batch(alerts)
        throttle.commit()
        log.info("Alerts: built %d, sent %d", len(alerts), sent)
        performance.log_alerts(alerts, rows, now)

    # Mom digest: purely additive Chinese-language macro digest to a second
    # Feishu webhook. No-op if FEISHU_MOM_WEBHOOK_URL isn't set.
    mom_digest.run(macro_analyses, client)

    # Evaluate past alerts whose 1d/3d/5d horizons have elapsed.
    from datetime import timezone as _tz
    performance.evaluate_pending(getattr(technicals, "_CLIENT", None), datetime.now(_tz.utc))
    performance.compile_stats(datetime.now(config.MARKET_TZ))

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
