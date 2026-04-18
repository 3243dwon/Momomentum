# Momentum

Personal momentum scanner with news synthesis. Python scanner + 3-tier LLM + Feishu alerts + SvelteKit PWA on Vercel.

```
2,500 ticker scan → tier-0 routing → news ingest → Haiku classify → Sonnet "why" → Opus macro beneficiaries
                                                                                                          ↓
                                                                                          Feishu alerts + JSON for the web app
```

## ⚠️ First thing — rotate your API key

If you shared an Anthropic key in any chat, document, or log, **revoke it now** at [console.anthropic.com/settings/keys](https://console.anthropic.com/settings/keys) and generate a fresh one. Same principle for the Feishu webhook.

Set them in three places, never in code:

1. **Local `.env`** — copy `.env.example` to `.env`, fill in values. Gitignored.
2. **GitHub Actions** — repo → Settings → Secrets and variables → Actions → `ANTHROPIC_API_KEY` and `FEISHU_WEBHOOK_URL`.
3. **Vercel** — project → Settings → Environment Variables (only needed if you ever read these from the web app; right now the web app reads no secrets).

## Architecture

```
momentum/
├── scanner/                 # Python — runs in GitHub Actions
│   ├── config.py                # all knobs in one place
│   ├── universe.py              # S&P 500 + NASDAQ 100 + NYSE common (~2,500 after filter)
│   ├── technicals.py            # batched yfinance + RSI/MACD/rel-vol
│   ├── state.py                 # prior-scan persistence + delta detection
│   ├── windows.py               # market-clock window detection
│   ├── router.py                # Tier 0: which tickers earn LLM cost
│   ├── news.py                  # Finviz per-ticker + RSS macro feeds
│   ├── llm/
│   │   ├── client.py            # shared Anthropic client + caching + audit log
│   │   ├── classify.py          # Tier 1: Haiku — dedup + classify + entity extract
│   │   ├── synthesize.py        # Tier 2: Sonnet — per-ticker "why"
│   │   └── macro.py             # Tier 3: Opus — macro → beneficiary reasoning
│   ├── alerts/
│   │   ├── throttle.py          # per-(ticker, alert_type) cooldown
│   │   ├── rules.py             # threshold + delta + macro alert decisions
│   │   └── feishu.py            # webhook sender with audit log
│   ├── render.py                # writes data/scan.json + data/news.json
│   └── main.py                  # entry point
├── data/                    # committed JSON — consumed by the web app
│   ├── scan.json                # ticker rows + synthesis per row
│   ├── news.json                # ticker_news + macro_events with beneficiaries
│   ├── deltas.json              # what changed since last scan
│   ├── universe.json            # ticker candidate list
│   └── watchlist.json           # hand-edit your pinned tickers
├── web/                     # SvelteKit PWA, deploys to Vercel
│   ├── src/routes/
│   │   ├── +page.svelte         # main dashboard: top 20 → fresh news → watchlist → all-scan table
│   │   ├── t/[ticker]/          # per-ticker detail with synthesis + news + macro context
│   │   └── macro/               # macro events panel (beneficiaries / losers)
│   ├── scripts/sync-data.mjs    # copies ../data/*.json → static/data/ at build
│   └── ...
└── .github/workflows/
    └── scan.yml                 # 24/7 cron with window-aware logic
```

## Three-tier LLM economics

The reason this fits a personal budget at Sonnet/Opus quality: **cascade, don't blanket**.

- **Tier 0 (rules, free):** filter ~2,500 tickers down to ~50–200 movers/news-bearers
- **Tier 1 (Haiku 4.5):** classify + dedup all news (~$0.05/scan)
- **Tier 2 (Sonnet 4.6):** per-ticker "why" only for routed tickers with high-impact news (~$0.30/scan)
- **Tier 3 (Opus 4.7):** macro → beneficiary reasoning, only on high-impact macro events (~$0.50/event)

Realistic cost: $20–60/month at 30-min cadence during market hours + 2-hour cadence overnight/weekend. Audit log in `data/audit/` so you can see exactly what every tier saw and produced.

## Alerts (Feishu)

Three classes, all 24/7, calibrated by window:

- **Threshold** — watchlist move, big move + volume spike, fresh high-impact news
- **Delta** — *new* top-20 entrant, ≥10 rank jump, momentum acceleration across scans
- **Macro** — high-impact macro event with Opus's beneficiary/loser breakdown

Per-(ticker, alert_type) cooldown of 2hr prevents spam. `MATERIAL_CHANGE_PCT` re-opens the gate when a signal materially strengthens (default 1.5%). Audit log in `data/audit/`.

## Web app

Single-page SvelteKit on Vercel with PWA manifest. Reads JSON from `/data/*.json` shipped with the build. Routes:

- `/` — dashboard (top 20 → fresh news → watchlist → full sortable scan table)
- `/t/[ticker]` — per-ticker page with synthesis, news, macro mentions
- `/macro` — macro events with beneficiaries/losers cards

Mobile-first responsive. PWA install works ("Add to Home Screen" on iOS/Android). For full PWA installability you'll want to add `web/static/icon-192.png` and `web/static/icon-512.png` — placeholder icons until then.

## Local setup

```bash
# Scanner side
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # then fill in your keys

python -m scanner.main --rebuild-universe --limit 50 --force --verbose

# Web side
cd web
npm install
npm run dev   # http://localhost:5173
```

CLI flags:
- `--limit N` — scan only first N tickers (dev)
- `--force` — ignore market-window check, always scan
- `--rebuild-universe` — refresh `data/universe.json`
- `--no-llm` — skip the 3-tier LLM (still ingests news)
- `--no-news` — skip news + LLM entirely (technicals only)
- `--no-alerts` — build but don't send Feishu alerts

## Deploy

**GitHub Actions** runs the scanner on cron: `*/30 8-23 * * 1-5` (extended hours, every 30min) + every 2hr overnight + weekend. Commits `data/*.json` back to the repo on each run.

**Vercel** — connect the repo, set **Root Directory** to `web/`. Auto-deploys on every push from the scanner. Cache headers on `/data/*` are `max-age=60` so the page reflects fresh scans within a minute.

PWA install: open the deployed URL on phone → Share → Add to Home Screen.

## Tunable knobs

All in [scanner/config.py](scanner/config.py):

- Universe: `MIN_PRICE`, `MIN_AVG_VOLUME_20D`, `UNIVERSE_REBUILD_AFTER_DAYS`
- Alerts: `PCT_MOVE_THRESHOLD_RTH`, `PCT_MOVE_THRESHOLD_AH`, `REL_VOLUME_THRESHOLD`, `MIN_AH_VOLUME`
- Deltas: `TOP_N_MOVERS`, `RANK_JUMP_THRESHOLD`
- Throttling: `ALERT_COOLDOWN_SECONDS`
- Models: `HAIKU_MODEL`, `SONNET_MODEL`, `OPUS_MODEL`

## Roadmap

- [x] Phase 1 — scanner core (universe, technicals, deltas, GH Actions)
- [x] Phase 2 — news ingestion + 3-tier LLM (Haiku/Sonnet/Opus)
- [x] Phase 3 — Feishu alerts (threshold + delta + macro, throttling, audit)
- [x] Phase 4 — SvelteKit PWA on Vercel (mobile-first responsive)
- [ ] PWA icons (`web/static/icon-192.png`, `icon-512.png`)
- [ ] Optional: ticker chart sparklines
- [ ] Optional: backtest of the routing rules vs realized moves
