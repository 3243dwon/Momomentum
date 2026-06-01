# Performance roadmap

Action list for improving signal quality, derived from `/performance` data as
of 2026-05-29 (30-day window, 552 picks, 1,903 alerts).

## Status (as of 2026-06-01)

5 of 6 items shipped in commit `b157710`. Remaining item is gated on data.

| Item | What | Status |
|------|------|--------|
| #1 | Suppress shorts when SPY > 50-day MA | ✅ shipped — `scanner/regime.py` + `recommend.py` |
| #2 | Log full feature vector per pick | ✅ shipped — `performance.py` (collecting now) |
| #3 | Regime-tag every pick + alert | ✅ shipped — `performance.py` + `main.py` |
| #4 | Demote `big_move` to catalyst-confirmed | ✅ shipped — `alerts/rules.py` |
| #6 | Backtest the Weekly classifications | ✅ shipped — `scanner/weekly_performance.py` |
| #5 | Rebuild the score from regression | ⏳ **blocked on data** — needs 4–8 weeks of #2's feature logs before a fit is meaningful. Revisit ~late July 2026. |

When #5 is ready: regress 5-day signed return against each logged feature
(univariate Spearman first, then a regularized multivariate fit), compare
against the current hand-weighted score as baseline, and only re-weight if it
beats it. The feature + regime data is accumulating in
`data/cache/recommendations_log.jsonl` now.

---

## What the data says

Verified against `data/recommendation_performance.json` and `data/performance.json`:

| Bucket            | 5d evaluated | 5d hit rate | 5d avg return |
|-------------------|--------------|-------------|---------------|
| `long_hi` (≥7)    | 23           | 56.5%       | **+2.54%**    |
| `long_lo` (<7)    | 37           | 94.6%       | **+11.70%**   |
| `short_hi` (≥7)   | 21           | 28.6%       | **−3.57%**    |
| `short_lo` (<7)   | 39           | 41.0%       | **−1.26%**    |

| Alert type         | Count | 5d hit rate | 5d avg return |
|--------------------|-------|-------------|---------------|
| `catalyst`         | 107   | 65.9%       | **+1.97%**    |
| `watchlist`        | 538   | 55.6%       | +0.51%        |
| `delta_new_top20`  | 152   | 45.5%       | +0.55%        |
| `big_move`         | 1106  | 47.7%       | +0.25%        |

Two clear signals:
1. **High-conviction longs underperform low-conviction longs by ~9pp.** Either
   the score is anti-predictive at the top end, or the sample is too thin (n=23
   at 5d) to mean anything. Probably both.
2. **Shorts lose money** in this regime — both score bands are negative on
   their respective directional bets. `short_hi` is worst at −3.57%.
3. **Catalyst alerts are the alpha.** 65.9% hit rate, positive across every
   horizon. `big_move` is essentially noise (47.7%, +0.25%).

## Diagnoses + actions, ranked by impact

### 1. Suppress shorts when SPY > 50-day MA  *(ship today)*

**Why first:** highest-leverage action with the lowest implementation cost,
and the evidence is unambiguous. `short_hi` averaging −3.57% over 5 days means
the picks we flag with high conviction to *short* go *up* — we're fighting an
uptrending tape.

**Where:** `scanner/recommend.py:compute()`. Pull SPY 1d/5d/50d from the
existing technicals path. If SPY is above its 50-day, drop the entire `shorts`
list (or only show shorts with `score >= 9`).

**Skepticism:** SPY-vs-50-day is a crude regime indicator that whipsaws —
better is `SPY > 200d AND VIX < 25`, or the breadth metrics. Start with
50-day because it's already implicit in the technicals pipeline; refine later.

**Validation after shipping:** track `short_*` buckets for a month. If
suppression is correct, the remaining shorts (in down regimes) should have
positive signed returns. If they don't, we have a deeper short-model problem.

### 2. Log full feature vectors per pick  *(infrastructure prereq)*

**Why second:** every other diagnosis below is gated on having the data to
test it. Right now `data/cache/recommendations_log.jsonl` stores
`{ticker, direction, score, price_at_pick}` — that's enough for hit-rate, not
enough for any "why does this score work" question.

**Where:** `scanner/performance.py:log_recommendations()`. Extend the logged
entry with:

```python
"features": {
    "pct_1d": row.get("pct_1d"),
    "pct_5d": row.get("pct_5d"),
    "rel_volume": row.get("rel_volume"),
    "rsi_14": row.get("rsi_14"),
    "macd_cross": row.get("macd_cross"),
    "above_vwap": (row.get("intraday") or {}).get("above_vwap"),
    "caution_level": row.get("caution_level"),
    "has_synthesis": bool(row.get("synthesis")),
    "verdict": (row.get("synthesis") or {}).get("verdict"),
    "confidence": (row.get("synthesis") or {}).get("confidence"),
    "news_count": row.get("news_count"),
    "tier": row.get("tier"),
    "sector": row.get("sector"),
}
```

Plus the regime tag (next item). Existing log rolls 45-day retention — within
two months we'll have ~30 picks/day × 60 = ~1,800 fully-labeled outcomes,
enough for a real univariate-then-multivariate analysis.

### 3. Regime-tag every pick and alert  *(same audit-infra extension)*

**Why third:** trivial to bolt onto #2; permanently fixes the "which signal
works in which environment" blindspot. Without this, every future analysis is
regime-blind.

**Where:** add a `_compute_regime()` helper to `scanner/main.py` that runs
once per scan, output goes into every logged pick/alert:

```python
"regime": {
    "spy_pct_5d": ...,
    "spy_above_50d": True/False,
    "spy_above_200d": True/False,
    "vix": ...,           # if accessible
    "advance_decline": ... # if cheap to compute
}
```

Macro tab data is already being fetched — wire it into the audit log instead
of leaving it siloed in `data/news.json`.

### 4. Demote `big_move` alerts to require a catalyst  *(easy data-driven fix)*

**Why fourth:** the data clearly says raw big-mover chasing has no edge
(+0.25% over 5d). Catalyst-confirmed moves are the alpha (+1.97%, 65.9%).

**Where:** `scanner/alerts/rules.py`. Add a precondition that `big_move`
alerts also require either:
- a synthesis with `verdict == "news_explains_move"`, OR
- a non-stretched caution level AND `rel_volume >= 2`

Anything else gets logged for tracking but not dispatched (or dispatched at a
lower priority that doesn't ping Feishu). Expected effect: `big_move` count
drops from 1106 → ~150-200, hit rate jumps toward the catalyst rate.

### 5. Rebuild the score from regression, not intuition  *(after 2 months of #2 data)*

**Why fifth:** the chat advice is right *in principle* — the only honest way
to weight features is from forward-return regression on labeled outcomes. But
we need #2 to have logged the features first, and we need enough samples.
Don't fit on 552 picks.

**Method:** start with univariate Spearman rank correlation between each
feature and 5d signed return (fast, robust to outliers, no scaling). Then
multivariate with a regularized linear model (ridge) or a shallow gradient
boost (limit depth=3) to catch the obvious feature interactions. Compare
against the current hand-weighted score as baseline.

**Hypothesis I'd test first:** I suspect the *news catalyst* bonus (+3 for
high-confidence `news_explains_move`) is the actual problem, not extension as
the chat suggested. The current scoring code (`recommend.py:90-108`) already
penalizes RSI > 75 and disqualifies `stretched`, so extension is not getting
overweighted. But the news bonus pushes news-driven movers to the top, and
news-driven moves are often already priced in by the time we surface them —
that would explain the high-score-underperforms-low-score inversion.

### 6. Validate Weekly classifications  *(uses existing infra pattern)*

**Why sixth:** the chat is right that this is potentially the most useful
medium-term signal we have, but completely unmeasured. Same hit-rate analysis
the alert/recommendation pipeline already uses, with a longer evaluation
horizon (2 / 4 / 8 weeks instead of 1 / 3 / 5 days).

**Where:** new `scanner/weekly_performance.py` mirroring `performance.py`
shape — log weekly classifications on Saturday, evaluate forward returns on
subsequent weekly runs, roll up by classification (`real_momentum` /
`fakeout` / `unclear`) and confidence.

## What I'd push back on from the chat advice

### "Check for look-ahead bias" is misdiagnosed

The current implementation (`performance.py:55-82`) records
`price_at_alert = row["price"]` — the scan-time snapshot price, which is
*after* any intraday spike. Measuring returns from that price is realistic /
conservative, not look-ahead. Switching to "next bar's open" as the chat
suggested would generally make returns look *better*, not worse, because
post-spike fades often happen overnight and next-open is cheaper.

**The real concern in this area is slippage.** Current measurement assumes
zero spread cost; for the mid/small-cap names the scanner surfaces, 0.3-0.8%
round-trip slippage is realistic. A flat 0.5% drag on every return would be
the cheap honest fix.

### "Univariate regression" is a starting screen, not the answer

The chat suggested regressing each feature individually. Fine as a first
screen — Spearman rank, look for sign + magnitude per feature. But features
*interact* (high volume + high RSI behaves differently from high volume + low
RSI), and the recommendation score is fundamentally a multi-feature decision.
Plan for univariate-then-multivariate, not univariate alone.

### "Extension is the bug" hypothesis is likely wrong

The chat reasoned that high scores reward extension. Reading `recommend.py`:

- Day move caps reward at 1.5-5% (line 41-46) — bigger moves get *less* boost
- 5d trend caps at 1-18% (line 49-55)
- RSI > 80 is -2, > 75 is -1 (line 93-98)
- `caution_level == "stretched"` is disqualifying (line 32-33)
- `caution_level == "caution"` (= "extended") is -2 (line 132-134)

Extension is *already* penalized. The likely culprit for `long_hi` underperformance
is the news-catalyst bonus (+3) pushing news-driven movers — which may be
already priced in by the time we score them — to the top of the list. Test
this hypothesis specifically once #2 lands.

## Recommended execution order

1. Ship #1 (suppress shorts) — one afternoon, immediately stops a known bad
   signal from being acted on.
2. Ship #2 + #3 together (feature logging + regime tagging) — one session,
   they share the same `log_recommendations()` extension. Both are no-op for
   user-facing surfaces but unblock all future analysis.
3. Ship #4 (gate big_move on catalyst) — one session, immediate effect on
   alert dispatch volume and quality.
4. Wait 4-8 weeks for #2 to accumulate samples.
5. Then #5 (rebuild score) — needs the data.
6. Then #6 (validate weekly) — parallel to #5, independent.

The chat's ranking was 1 → 2 → 6. Mine is 2 (shorts) → 5+3 (logging) → 4 →
wait → 1+6 (with caveat: #1 here means "rebuild score" not "log features"
— the chat compressed those into the same bullet).

## Open questions to revisit later

- How does the `verdict` field interact with score in practice? Group
  `long_hi` by verdict and see if `news_explains_move` is dragging the bucket
  down.
- Is the 30-day rolling window the right comparison? Markets shifted regime
  multiple times in 30 days — a regime-stratified hit rate is more honest.
- Should `MAX_PER_SIDE = 6` be regime-aware? In choppy markets, fewer picks
  with higher conviction may beat more picks with mediocre conviction.
