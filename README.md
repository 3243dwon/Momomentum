# Momentum

Personal momentum scanner with news synthesis. Python scanner pipeline + 3-tier LLM cascade + Feishu alerts + SvelteKit PWA on Vercel.

```
~5,000 ticker scan → tier-0 routing → news ingest → Haiku classify → Sonnet "why" → Opus macro beneficiaries
                                                                                                          ↓
                                                                              Feishu alerts + JSON for the web app
```

The differentiator vs a generic momentum scanner: **macro events get LLM-reasoned beneficiary/loser breakdowns, not just headlines.** When a Fed pause hits the wire, you see "TLT, ARKK upside (mechanism: lower discount rate); JPM downside (NIM compression)" — not just the article link.

## How it thinks

**3-tier LLM cascade** — quality without spraying Opus on everything:

| Tier | Model | Job | Cost |
|------|-------|-----|------|
| 0 | rules | filter ~5,000 → ~50–200 movers / news-bearers | free |
| 1 | Haiku 4.5 | classify, dedup, extract entities | ~$0.05/scan |
| 2 | Sonnet 4.6 | per-ticker "why this moved" synthesis | ~$0.30/scan |
| 3 | Opus 4.7 | macro → beneficiary/loser reasoning | ~$0.50/event |

Realistic cost: **$20–60/month** at 30-min cadence during extended hours + 2-hour cadence overnight/weekend. Audit trail at `data/audit/` shows what every tier saw and produced.

**Window-aware alerts** (Feishu webhook) in three classes:

- **Threshold** — watchlist move, big move + volume spike, fresh high-impact news
- **Delta** — *new* top-20 entrant, ≥10 rank jump, momentum acceleration across scans
- **Macro** — high-impact macro event with Opus's beneficiary/loser breakdown

Per-(ticker, alert_type) 2hr cooldown prevents spam. The gate re-opens when a signal materially strengthens (default: another 1.5% move).

## Architecture

```
scanner/             # Python — runs in GitHub Actions
  config.py            # all tunable knobs
  universe.py          # S&P 500 + NDX-100 + NYSE common + NASDAQ-listed (~5,000)
  technicals.py        # batched yfinance + RSI/MACD/rel-vol
  state.py             # delta detection (top-20 entrants, rank jumps, accel)
  router.py            # Tier 0 routing
  news.py              # Finviz per-ticker + RSS macro feeds
  llm/                 # 3-tier pipeline (client + classify + synthesize + macro)
  alerts/              # Feishu webhook + per-(ticker, type) throttling
data/                # committed JSON consumed by the web app
web/                 # SvelteKit PWA, deploys to Vercel
.github/workflows/   # 24/7 cron, window-aware schedule
```

The web app is a single-page dashboard:

- `/` — top 20 movers → fresh news → watchlist → full sortable scan table
- `/t/[ticker]` — synthesis + news + macro mentions per ticker
- `/macro` — beneficiaries/losers cards per macro event

Mobile-first responsive, light + dark theme, PWA-installable.

## Local setup

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # fill in ANTHROPIC_API_KEY + FEISHU_WEBHOOK_URL

python -m scanner.main --rebuild-universe --limit 50 --force --verbose

# Web side
cd web
npm install && npm run dev   # http://localhost:5173
```

CLI flags: `--limit N` · `--force` · `--rebuild-universe` · `--no-llm` · `--no-news` · `--no-alerts`.

Secrets live in three places, never in code: `.env` locally (gitignored), GitHub Actions secrets for CI, Vercel env vars if needed.

## Deploy

**GitHub Actions** runs the scanner on cron — every 30min during extended market hours (Mon–Fri) and every 2hr overnight + weekend. Each run commits `data/*.json` back to the repo.

**Vercel** picks up every push. Set Root Directory to `web/`, override Build Command to `npm run build` so the data-sync step runs. Auto-deploys take ~30 sec.

PWA install: open the deployed URL on phone → Share → Add to Home Screen.

## Tunable knobs

All in [scanner/config.py](scanner/config.py):

- **Universe** — `MIN_PRICE`, `MIN_AVG_VOLUME_20D`, `UNIVERSE_REBUILD_AFTER_DAYS`
- **Alerts** — `PCT_MOVE_THRESHOLD_RTH`, `PCT_MOVE_THRESHOLD_AH`, `REL_VOLUME_THRESHOLD`, `MIN_AH_VOLUME`
- **Deltas** — `TOP_N_MOVERS`, `RANK_JUMP_THRESHOLD`
- **Throttling** — `ALERT_COOLDOWN_SECONDS`, `MATERIAL_CHANGE_PCT`
- **Models** — `HAIKU_MODEL`, `SONNET_MODEL`, `OPUS_MODEL`

---

Personal scanner. Not investment advice.
