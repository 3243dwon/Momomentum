"""Momentum MCP server — the scanner's brain as tools for any Claude client.

Exposes the committed ``data/*.json`` (scan, news, Serenity, predictions,
ledger, briefing, performance, deals) as MCP tools so Claude Code or Claude
Desktop can pull live Momentum signals mid-conversation — no copy-paste, no
hitting the SSO-protected website.

Run directly to smoke-test:   python mcp/server.py
Wire it into a client:        see mcp/README.md

The data is read from the local repo (git-tracked), so its freshness is
whatever your last `git pull` or scanner run produced; every tool reports the
data's age so the model knows.
"""

import sys
from pathlib import Path

# Make `momentum_data` importable no matter how the server is launched.
sys.path.insert(0, str(Path(__file__).resolve().parent))

import momentum_data as md  # noqa: E402
from mcp.server.fastmcp import FastMCP  # noqa: E402

mcp = FastMCP("momentum")


@mcp.tool()
def momentum_status() -> dict:
    """Snapshot of the scanner right now: data freshness, market regime, scan
    counts, the latest briefing headline, and the age of every brain file. Call
    this first to see how fresh the data is before reasoning over it."""
    return md.status()


@mcp.tool()
def get_ticker(ticker: str) -> dict:
    """The full picture on one name, cross-referenced across every source: scan
    momentum/indicators, the desk's take + plan, recent news, Serenity
    (Chinese-X) mentions, ripple predictions, the weekly verdict, and the call
    ledger. The highest-leverage tool — use it to answer "what's the story on X?"."""
    return md.get_ticker(ticker)


@mcp.tool()
def top_movers(limit: int = 10, direction: str = "both") -> dict:
    """The biggest movers in the latest scan, ranked by absolute 1-day move.
    direction: 'up', 'down', or 'both'."""
    return md.top_movers(limit=limit, direction=direction)


@mcp.tool()
def desk_recommendations() -> dict:
    """The desk's current long/short picks — score, trade levels, the
    multi-agent take/pass decision, and the plan behind each."""
    return md.desk_recommendations()


@mcp.tool()
def query_ledger(
    ticker: str | None = None,
    status: str | None = None,
    kind: str | None = None,
    limit: int = 50,
) -> dict:
    """The accountability ledger — every dispatched call and how it graded.
    Filters: ticker; status (pending/hit/miss/untracked); kind (alert/pick/prediction)."""
    return md.query_ledger(ticker=ticker, status=status, kind=kind, limit=limit)


@mcp.tool()
def get_serenity(ticker: str | None = None, limit: int = 30) -> dict:
    """The Serenity feed — synthesized Chinese-X market chatter with English
    summaries, stance, and tagged tickers. Optionally filter to one ticker."""
    return md.get_serenity(ticker=ticker, limit=limit)


@mcp.tool()
def get_predictions() -> dict:
    """Ripple forward-predictions: popular-stock catalysts and the second-order
    names they should move, with mechanism and whether it's priced in yet."""
    return md.get_predictions()


@mcp.tool()
def get_briefing() -> dict:
    """The latest one-read briefing: headline, market state, actionable calls,
    what to watch, and what changed since the last scan."""
    return md.get_briefing()


@mcp.tool()
def signal_performance() -> dict:
    """The signal scoreboard — for each signal class, how often its directional
    call followed through, by horizon. The track record behind the conviction."""
    return md.signal_performance()


@mcp.tool()
def get_deals(limit: int = 20) -> dict:
    """Deal flow: high-impact catalysts on popular names and the second-order
    ripple calls each one sets up."""
    return md.get_deals(limit=limit)


if __name__ == "__main__":
    mcp.run()
