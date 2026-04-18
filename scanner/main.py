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

from scanner import config, news, render, router, state, technicals, universe, windows
from scanner.alerts import feishu
from scanner.alerts import rules as alert_rules
from scanner.llm import classify, macro, synthesize
from scanner.llm.client import get_client

log = logging.getLogger("scanner")


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
    if limit:
        tickers = tickers[:limit]
    uni_size = len(tickers)
    log.info("Loaded universe: %d tickers", uni_size)
    rows = technicals.scan(tickers)

    deltas = state.compute_and_persist(rows, now)

    routed, watchlist = router.route(rows, deltas, window) if rows else ([], sorted(router.load_watchlist()))

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
        all_items = [n for items in ticker_news.values() for n in items] + macro_news
        classifications = classify.classify(all_items, client)

        for ticker, items in ticker_news.items():
            ticker_news_enriched[ticker] = classify.attach(items, classifications)

        macro_news_enriched = classify.attach(macro_news, classifications)
        macro_news_dedup = classify.dedup(macro_news_enriched)

        syntheses = synthesize.synthesize(ticker_news_enriched, {r["ticker"]: r for r in rows}, client)

        macro_for_opus = [
            m for m in macro_news_dedup
            if m.get("impact") in ("high", "medium") and (m.get("type") or "").startswith("macro_")
        ]
        macro_analyses = macro.analyze(macro_for_opus, client)
    else:
        ticker_news_enriched = ticker_news
        macro_news_enriched = macro_news

    news_count_by_ticker = {t: len(v) for t, v in ticker_news_enriched.items()}
    render.write_scan(
        rows, window, now, uni_size,
        syntheses_by_ticker=syntheses,
        news_count_by_ticker=news_count_by_ticker,
    )
    render.write_news(ticker_news_enriched, macro_analyses, now)

    if use_alerts:
        alerts, throttle = alert_rules.build_alerts(rows, deltas, syntheses, macro_analyses, window)
        sent = feishu.send_batch(alerts)
        throttle.commit()
        log.info("Alerts: built %d, sent %d", len(alerts), sent)

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
