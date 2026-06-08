# Momentum

A personal momentum scanner with AI-powered news synthesis. Built for one trader.

When a Fed pause hits the wire, a generic scanner shows you the headline.
This shows you *who benefits* — with the mechanism, the confidence, and the
horizon — alongside the price action that triggered the alert.

```
ticker scan → routing → news ingest → classify → synthesize → macro + ripple
                                                                      ↓
                                                           alerts + dashboard
```

Three signal classes drive alerts: threshold (watchlist + big moves),
delta (rank changes between scans), and macro (events with second-order
beneficiary breakdowns). All throttled, all auditable, all opinionated.

Mobile-first PWA with light/dark, sortable tables, per-ticker drill-down,
and a separate macro-events view. Runs on its own — no babysitting.

---

## What it does

Every scan, the pipeline:

1. Pulls daily bars + intraday snapshots for ~2,500 tickers (S&P 500 + NASDAQ-100 + NYSE/NASDAQ commons) from Alpaca
2. Computes technicals (RSI-14, MACD crossover, 1d/5d change, relative volume, sparkline)
3. Routes ~50–200 tickers to news ingest based on price/volume signals
4. Classifies news (Claude Haiku) → synthesizes per-ticker explanations (Claude Sonnet) → reasons about macro events + forward "ripple" predictions (Claude Opus)
5. Builds tiered alerts (catalyst > ripple > macro > watchlist > delta) with per-ticker throttling
6. Delivers to Feishu webhook + commits scan/news/deltas JSON for the web dashboard

## Architecture

**Three-tier Claude pipeline with cost control:**

| Tier | Model | Job | Per-scan cap |
|---|---|---|---|
| 0 | Rules | Route ~2,500 → ~100 tickers (price/volume/delta filters) | — |
| 1 | Haiku 4.5 | Classify news (type, impact, dedup, route flag) — batches of 15 | 100 items |
| 2 | Sonnet 4.6 | Per-ticker synthesis (verdict, confidence, supporting news) — 8 concurrent | 20 syntheses |
| 3 | Opus 4.7 | Macro reasoning (beneficiaries, losers, mechanisms) — 4 concurrent | 5 events |
| 3b | Opus 4.7 | Ripple: forward second-order predictions from a popular stock's news — who *else* moves, before they do — 4 concurrent | 4 events |

Tier-0 routing is the cost lever: rules filter 2,500 tickers down to ~100 before any LLM cost. Each tier uses tool-use for structured output, prompt caching to drop input cost ~90% on repeat system prompts, and full audit logs to `data/audit/YYYY-MM-DD/`.

**Macro reasoning** is the differentiator. Opus is constrained to the universe (drops unknown tickers) and required to give explicit causal links — *"tariff on Chinese solar → First Solar margin expansion"* — not vibes. Confidence levels (high/medium/low) and horizons (intraday/days/weeks/months) are part of the schema.

**Ripple prediction** runs that reasoning *forward*. The synthesis tier only reads a ticker's own news, so a deal about NVDA/GOOGL that names INTC as backup foundry never reaches INTC — you find out late. The ripple tier closes that: when a popular stock's high-impact news (deal, earnings, guidance) breaks, Opus maps which *other* names it helps or hurts, then cross-references the live tape to flag the ones that **haven't priced it in yet** — a bullish/bearish call surfaced *before* the move, not an explanation after. Predictions are accountable: each is logged and scored against its 1/3/5-day outcome (`/predictions`, `prediction_performance.json`). Cost-bounded by design — only popular triggers (S&P 500 / NDX / watchlist), deduped per story, hard-capped at 4 events/scan.

**Delta tracking** persists prior top-20 movers, detects rank jumps (≥15 positions), new entrants, and momentum acceleration — surfacing early movers before they become headlines.

**Alert tiers:**
- **A0 catalyst**: synthesis verdict says news explains the move + ticker also has a big move/unusual volume — always fires
- **A1 ripple**: a popular stock's news predicts a second-order move on *another* name that hasn't happened yet (the not-yet-priced-in calls only) — always fires
- **A threshold**: watchlist (±1.5%+), big move (±3%+ RTH / ±5%+ AH with 2× volume) — capped at 5/scan
- **B delta**: new top-20, rank jumps, momentum acceleration — capped at 5/scan
- **C macro**: high/medium-impact macro events with beneficiary lists — always fires

Per-ticker/type throttling (2-hour cooldown) prevents alert spam.

## Stack

**Backend** — Python 3.11+ · Alpaca paper API (bars + Benzinga news) · RSS (Fed, CNBC, MarketWatch, Yahoo) · Anthropic SDK · pandas/numpy · feedparser · httpx

**Frontend** — SvelteKit · Tailwind CSS · Vercel deployment · TypeScript

**Ops** — GitHub Actions cron-triggered scans · commits scan/news/deltas JSON to repo · Vercel auto-deploys frontend · Feishu webhooks for alerts (optional separate webhook for Chinese-language macro digest)

## Web dashboard

- `/` — recommended picks (LLM-scored, with conviction), scan filters, top-20 movers, fresh-news tickers, watchlist, full sortable table — see *Dashboard design* below
- `/t/[ticker]` — per-ticker drill-down (full technicals, all news, synthesis). The **指标解读 / What the signals say** block turns each live number into a plain-language bull/bear read (VWAP, day-range position, RVOL, RSI, MACD, gap, ATR volatility) so the page interprets, not just reports. Reads degrade gracefully: VWAP/range/gap only appear in a live session; RSI/MACD/RVOL/ATR always do. Logic in `web/src/lib/reads.ts`.
- `/predictions` — 🔮 **Ahead of the move**: the ripple tier's forward second-order calls (a popular stock's news → who *else* moves), grouped not-yet-priced-in / already-moving / tape-disagrees, with the not-yet-priced-in 5-day hit rate up top. A condensed version surfaces on `/` between Recommended and Top 20.
- `/macro` — macro events with beneficiaries/losers
- `/weekly` — Saturday roll-up (top movers, catalysts, rank jumps by day)
- `/political` — disclosed Congress trades (Senate + House STOCK-Act PTRs from FMP; requires `FMP_API_KEY`). Cross-references the day's scan: tickers also in the watchlist or moving ≥ 3% get highlighted.
- `/performance` — past alert outcomes (1d/3d/5d returns)
- `/learn` — bilingual indicator guide (VWAP, EMA, key levels, RVOL, float, ATR, RSI, MACD, gap) with an honest "is this live on the site" tag per indicator. The companion to the ticker-page reads above.

## Dashboard design

The scan page uses the **Conviction** visual direction — warm off-white canvas (`#fafaf7`) in light mode, dark slate in dark mode, with directional card tints (green wash for longs, red for shorts). Playfair Display is loaded for the hero `%` number and conviction score; everything else stays in the system sans / JetBrains Mono stack.

**Sections, top to bottom:**

- **Recommended** — hero `PickCard` grid (3 columns). Each card: rank · ticker (large bold) · long/short badge · price · Playfair display `%` · inset SVG sparkline · conviction score (1–10) · flag chips · synthesis "why" · top supporting headlines. Bucketed by long-term (catalyst-backed) vs short-term (pure technical), both sorted by score.
- **Top 20 movers** — dense `TickerRow` grid (rank · ticker · block-char sparkline · price · `%` · chips). Sorted by `|%chg|` of the filtered universe. Each row optionally carries a one-line "why" pulled from synthesis summary or top headline.
- **Fresh news** — tickers with new headlines that aren't already in Top 20.
- **Watchlist** — same thin-row treatment, `★` next to the ticker.
- **All scan** — collapsible `<details>` with the full sortable/searchable table.

**Flag chips** (replaces the old pill-badge stack — single normalized vocabulary in `lib/flags.ts`, rendered by `IconCluster` with up to 3 visible and a `+N` overflow chip):

| Chip   | Tone  | Means |
|--------|-------|-------|
| `LATE` | red   | Late entry risk — price stretched well above its trend |
| `NEWS` | warn  | High-impact news headline today |
| `VOL`  | warn  | Volume ≥ 2× 20-day average |
| `NEW`  | info  | New entrant to Top 20 since the last scan |
| `JUMP` | info  | Big rank jump or accelerating momentum |
| `MACD↑`| up    | MACD bullish cross |
| `MACD↓`| down  | MACD bearish cross |
| `OB`   | warn  | Overbought (RSI > 70) |
| `EXT`  | warn  | Extended above moving averages |
| `★`    | mute  | On watchlist |

Hover any chip for the full plain-English tooltip.

**Sparkline strategy is hybrid** — hero PickCards get a readable SVG polyline at full opacity (top-right inset of the `%` number); thin TickerRows get unicode block chars (`▁▂▃▄▅▆▇`) in JetBrains Mono. One `Sparkline` component handles both via a `treatment: 'line' | 'block'` prop.

**Components** (`web/src/routes/`): `PickCard.svelte`, `TickerRow.svelte`, `IconCluster.svelte`, `Sparkline.svelte`, `FilterBar.svelte`, `ScanTable.svelte`. Tokens live on `:root` / `[data-theme='dark']` in `app.css` so the same components render correctly in both themes without per-component branching.

## Running it

Required env vars in `.env`:

```
ANTHROPIC_API_KEY=...
ALPACA_API_KEY=...
ALPACA_API_SECRET=...
FEISHU_WEBHOOK_URL=...        # optional; alerts log only without it
FEISHU_MOM_WEBHOOK_URL=...    # optional; Chinese macro digest
FMP_API_KEY=...               # optional; powers /political dashboard
                              # (250 req/day free at financialmodelingprep.com)
SITE_URL=...                  # optional; base URL used in Feishu card links
                              # (defaults to the Vercel deployment)
```

```bash
# Backend scan
python -m scanner.main

# Web dev
cd web && npm run dev

# Web build (Vercel)
cd web && npm run build
```

Each layer fails independently: missing Anthropic key → LLM tiers skipped, scanner still returns technicals; missing Alpaca → no news/bars; missing Feishu → alerts log only.

---

Personal scanner. Not investment advice. Source by request.
