"""Entry point for the 24/7 Serenity poll workflow.

    python -m scanner.serenity_poll

Polls the X API for new @aleabitoreddit tweets, extracts/translates them, pushes
a Feishu card per new tweet, and writes data/serenity.json. Runs every 15 min on
its own (free, public-repo) GitHub Actions schedule — separate from the scan.
"""
from __future__ import annotations

import logging
import sys

from scanner import serenity


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        serenity.poll_and_process()
    except Exception as e:
        logging.getLogger("scanner.serenity_poll").error("Serenity poll failed: %s", e)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
