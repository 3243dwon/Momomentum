# Agent desk — design charter

A proposed **tier-4** addition to the scanner: a small "desk" of perspective
agents that turns the single hand-weighted `recommend.py` score into a panel
of independent disciplines that get reconciled by a portfolio manager.

> Status: **design only.** Nothing here is built yet. The recommended path is
> to build it as a *shadow* alongside `recommend.py`, log its picks, and
> promote it only if it beats the baseline on real hit-rate (see §5).

## 0. Why

`recommend.py` is already trying to be four agents at once — technician,
analyst, risk manager, sizer — in one formula. The `/performance` data says
it's miscalibrated: `long_hi` (score ≥7) returned **+2.54%** over 5 days vs
`long_lo` **+11.70%**, and `short_hi` was **−3.57%** in a bull tape. One voice
doing everything, badly.

The fix is not "give the agents personalities." Personality is theater. What
creates useful disagreement is three concrete things:

- **a different data diet** (what each agent is allowed to see)
- **a different objective function** (what it optimizes for)
- **a different power** (advise vs veto vs decide)

## 1. The desk

Each agent maps onto data the scanner *already* produces.

| Agent | 中文 | Data diet | Optimizes for | Power |
|-------|------|-----------|---------------|-------|
| **Signal** | 技术 | technicals, intraday (VWAP/HOD/LOD), deltas, spark | entry quality — "fresh, or already run?" | advise |
| **Research** | 催化 | news synthesis, macro analyses, political trades, Trump pulse | catalyst durability — "is there a real *why* that sustains?" | advise |
| **Risk** | 风控 | regime (SPY vs 50/200d, VXX), caution_level, RSI extremes, crowding, historical hit-rate by setup | not losing — "what kills this trade?" | **veto** |
| **Portfolio Mgr** | 组合 | all three verdicts + the book (watchlist/holdings) + regime | risk-adjusted forward return | **decides + sizes** |

The **Risk veto** is the piece the current system lacks — and exactly what the
perf data says is missing (it kept surfacing shorts that lost money in a bull
regime, and over-scored extended/news-priced-in longs).

### Mandates (the system prompts, in one line each)

- **Signal:** "Score only the price action. Is this a clean continuation entry
  or an exhausted chase? Ignore the news — that's not your job."
- **Research:** "Is the move explained by a durable catalyst, or is it noise /
  already priced in? A news-driven move that the market has fully absorbed is
  *not* a fresh edge."
- **Risk:** "Find the reason *not* to take this. Wrong regime? Crowded late
  entry? Setup type with a losing track record? You may VETO. Default skeptical."
- **Portfolio Mgr:** "Reconcile the three. Decide long / short / pass and a
  size. If you override the Risk veto, say why. Explain the disagreement."

## 2. Disagreement is the product

A pick all four love is a *different animal* from one the PM pushed through
over the Risk veto. Log the per-agent verdicts and the disagreement, not just
the final call. That signal is new information the single scorer can't express.

Schema sketch for each desk pick (logged + optionally shown):

```jsonc
{
  "ticker": "NVDA",
  "decision": "long",          // PM's call
  "size_hint": "half",         // PM
  "signal":   { "vote": "long",  "entry_quality": 7, "note": "..." },
  "research": { "vote": "long",  "durability": "high", "note": "..." },
  "risk":     { "veto": false,   "concern": "RSI 71, watch", "note": "..." },
  "pm":       { "rationale": "...", "overrode_veto": false },
  "agreement": "unanimous"     // unanimous | majority | pm_override
}
```

## 3. Cost control (non-negotiable)

The scanner runs on cron with hard token caps; tier-0 routing is the whole
cost lever. The desk must not blow it up:

- runs **only on the ~15–20 candidates** `recommend.py` already shortlisted —
  never all 753 rows
- **one batched call per agent** (all candidates at once), not per-ticker
- four agent calls per scan, added to the existing Haiku/Sonnet/Opus tiers
- a visitor loading the site triggers **zero** of this — it's all pre-computed
  on the cron, same as everything else

## 4. Where it lives

```
scanner/desk/
  signal.py      # tier-4 agent: price-action verdict
  research.py    # tier-4 agent: catalyst-durability verdict
  risk.py        # tier-4 agent: veto + concerns
  pm.py          # reconciles, decides, sizes
  __init__.py    # run_desk(candidates, regime, book) -> [DeskPick]
```

- orchestrated from `scanner/main.py` right after `recommend.compute()`
- uses the existing `scanner/llm/client.py` (same Anthropic client as the
  other tiers), with structured tool-use output per agent
- logs to `data/cache/desk_log.jsonl`, evaluated by the existing
  `scanner/performance.py` machinery (1/3/5-day forward returns), so it's
  measured the same way as the recommendations and alerts

## 5. Rollout — shadow first, promote on evidence

1. Build the desk to run on the cron and **log its picks to a separate file**.
   Do **not** touch `recommend.py` or the dashboard yet.
2. Let it accumulate **4–8 weeks** of outcomes (same window the regression in
   `perf-roadmap.md` §5 needs).
3. Compare the desk's hit-rate + avg-return against the `recommend.py`
   baseline, regime-stratified.
4. **Promote only if it wins.** If it doesn't, we learned something cheap and
   the working scorer is untouched.

This is the same discipline applied to the perf-roadmap fixes: measure before
trusting.

## 6. Open questions

- Do the three advisor agents need to be three separate calls, or can a single
  call return three role-played verdicts? (Separate calls = genuine
  independence + diverse sampling; one call = cheaper but correlated. Start
  separate; collapse if cost bites.)
- Should the Risk agent's veto be hard (kills the pick) or soft (down-weights
  size)? Start soft-logged, harden once we trust it.
- Does the PM need the *other* picks for cross-sectional sizing (don't put the
  whole book in one sector), or is per-ticker fine for v1? Per-ticker first.
