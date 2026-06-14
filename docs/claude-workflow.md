# Working with Claude on Momentum

How to put Momentum's brain (the scanner's signals, news synthesis, Serenity,
predictions, ledger) and Claude's reasoning in the same room. Short version:
the leverage is **not** "tell Claude to read the website" — it's giving Claude
the raw data *and* the code that produced it.

> Status: **reference / mental model.** Distilled from a working session, not a
> spec for anything to build (except the MCP server in §4, which is a real
> suggestion).

## 0. The trap: don't point claude.ai chat at the live site

Two reasons "go read momomentum.vercel.app and tell me X" quietly fails:

1. **Vercel SSO.** The deployment sits behind Vercel's protection — an
   unauthenticated request gets a 403 "Security Checkpoint." Claude's web
   browsing isn't logged into the Vercel account, so it can't reach the page or
   the `/data/*.json` behind it.
2. **`ssr = false`.** Every route is client-rendered. Even past the auth wall,
   fetching the page HTML returns an empty shell — the real signal arrives in
   the JSON the browser loads afterward. A generic "read this URL" gets nothing.

So the website is the wrong *interface* for feeding the brain to Claude. **The
data is the interface.**

## 1. `/ask` — the fusion that already exists

`web/src/routes/api/ask/+server.ts` loads scan, news, weekly, Serenity,
predictions, performance, ledger, and briefing, detects tickers in the question,
builds context, and calls Claude. That *is* "Momentum + Claude at once,"
packaged for **fast, in-product, single questions** ("Is $NVDA chaseable here?",
"What did Serenity say about COHR?"). Use it for quick reads; it's available to
any user, not just a dev session.

Its limit: it has to trim context to fit a prompt, and it can't show its own
methodology or run anything.

## 2. Claude Code — for the deep, open-ended work

This is the right tool when you want real reasoning over the signals, because it
has what claude.ai chat and `/ask` can't:

- **Direct local access to `data/*.json`** — no SSO wall, no empty shell. It
  just reads the raw scan / news / serenity / ledger / predictions files.
- **The scanner source (`scanner/*.py`)** — so it can reason about *how* a
  signal was computed, not just the output.
- **It can run things** — re-run the scanner for fresh data, diff the ledger
  against git history, backtest an idea, write a one-off analysis script.
- **No prompt-budget squeeze** — it reads whole files.

Workflow:

```
cd momentum && git pull        # the bot commits fresh scan/serenity/ledger data
# then, in Claude Code:
"Read data/scan.json, data/serenity.json and data/ledger.json.
 Which names is the scanner flagging that Serenity also mentioned,
 and how have similar setups graded in the ledger?"
```

Claude reads the live signals + the track record + the methodology and reasons
across all three. That's the fusion at full strength.

## 3. Decision guide

| You want…                                                        | Use                      |
| ---------------------------------------------------------------- | ------------------------ |
| A fast answer grounded in today's signals                        | **`/ask`** (already built) |
| Deep multi-source analysis, run/backtest, see the methodology    | **Claude Code** in the repo |
| Momentum data live in *every* Claude conversation                | **MCP server** (§4)      |
| claude.ai chat to read the live site                             | **Don't** — SSO + `ssr=false` |

## 4. The permanent integration: an MCP server — **built**

This is built: [`mcp/`](../mcp/) is a small MCP server that exposes the data as
tools (`momentum_status`, `get_ticker`, `top_movers`, `desk_recommendations`,
`query_ledger`, `get_serenity`, `get_predictions`, `get_briefing`,
`signal_performance`, `get_deals`). Any Claude client (Code, Desktop) can pull
live Momentum data mid-conversation — no copy-paste, no SSO problem (it reads
the local git-tracked `data/`). That turns "Momentum brain" from a per-session
`Read` into a permanent capability.

Setup is in [`mcp/README.md`](../mcp/README.md). Short version:

```sh
python3 -m pip install -r mcp/requirements.txt
claude mcp add momentum -- python3 "$(pwd)/mcp/server.py"
```

Keep the data fresh with `git pull` before a session that needs today's tape —
every tool reports the data's `age_minutes` so the model knows.

## 5. The one rule

The payoff isn't "Claude reads your website." It's "Claude reads your raw data
*and* your code *and* can run the pipeline." Only the local / Claude Code path
(or an MCP server over the same data) gives you all three.
