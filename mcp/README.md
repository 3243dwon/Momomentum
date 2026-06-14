# Momentum MCP server

Exposes the scanner's brain — the committed `data/*.json` (scan, news, Serenity,
predictions, ledger, briefing, performance, deals) — as MCP tools, so **any
Claude client** (Claude Code, Claude Desktop) can pull live Momentum signals
mid-conversation. No copy-paste, and no hitting the SSO-protected website.

See [`docs/claude-workflow.md`](../docs/claude-workflow.md) for why this beats
pointing Claude at the live site.

## Why

> The leverage isn't "Claude reads your website." It's "Claude reads your raw
> data." This turns that from a per-session `Read data/*.json` into a permanent
> capability available in every Claude conversation.

The data is read from the **local repo** (the `data/` dir is git-tracked), so
its freshness is whatever your last `git pull` or scanner run produced. Every
tool reports the data's age (`age_minutes`) so the model knows.

## Tools

| Tool | What it returns |
| --- | --- |
| `momentum_status` | Freshness, market regime, counts, briefing headline. **Call first.** |
| `get_ticker(ticker)` | Everything on one name: scan, desk take + plan, news, Serenity, predictions, weekly verdict, ledger history. The star tool. |
| `top_movers(limit, direction)` | Biggest movers by abs 1-day %. |
| `desk_recommendations()` | The desk's long/short picks, levels, take/pass + plan. |
| `query_ledger(ticker, status, kind, limit)` | The accountability ledger, filterable. |
| `get_serenity(ticker, limit)` | Chinese-X market chatter, English summaries + stance. |
| `get_predictions()` | Ripple forward-predictions (who-else-moves). |
| `get_briefing()` | The latest one-read briefing. |
| `signal_performance()` | The signal scoreboard / track record by horizon. |
| `get_deals(limit)` | Deal flow and its ripple chains. |

## Install

```sh
# from the repo root
python3 -m pip install -r mcp/requirements.txt
# smoke-test the data layer (no MCP client needed):
python3 mcp/server.py    # starts the stdio server; Ctrl-C to stop
```

By default it reads `../data` relative to the server. Override with
`MOMENTUM_DATA_DIR=/path/to/data` if you keep the data elsewhere.

## Wire it into Claude Code

From the repo root:

```sh
claude mcp add momentum -- python3 /Users/makutanaka/momentum/mcp/server.py
```

That writes a project-scoped `.mcp.json`. Or create it by hand:

```json
{
  "mcpServers": {
    "momentum": {
      "command": "python3",
      "args": ["/Users/makutanaka/momentum/mcp/server.py"]
    }
  }
}
```

Then in a Claude Code session: *"Use the momentum tools — what's the full story
on SGHC, and how have the desk's longs graded in the ledger?"*

## Wire it into Claude Desktop

Edit `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "momentum": {
      "command": "python3",
      "args": ["/Users/makutanaka/momentum/mcp/server.py"]
    }
  }
}
```

Restart Claude Desktop. The Momentum tools appear in the tools menu.

> Tip: if `python3` isn't the interpreter that has `mcp` installed, use the
> absolute path to the right one (e.g. a venv's `python`). Keep the data fresh
> with `git pull` (or a scanner run) before a session that needs today's tape.
