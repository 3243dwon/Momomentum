"""Shared Anthropic client used by every LLM tier.

Every call:
- Goes through the same `tool_use` shape so output is structured (no JSON
  parsing failures from free-text responses).
- Caches the system prompt when it's long enough to qualify (saves real
  money once we're running 100s of calls per scan).
- Writes a per-call audit record to data/audit/ so we can trace what each
  tier actually saw and produced — and spot-check what got filtered out.
"""
from __future__ import annotations

import json
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, TypeVar

import anthropic

from scanner import config

log = logging.getLogger(__name__)

CACHE_MIN_TOKENS = 1024  # Anthropic's minimum cacheable block size for Sonnet/Opus

T = TypeVar("T")


class LLMError(Exception):
    pass


class LLMClient:
    def __init__(self, api_key: str | None = None):
        key = api_key or config.ANTHROPIC_API_KEY
        if not key:
            raise LLMError("ANTHROPIC_API_KEY not set")
        self.client = anthropic.Anthropic(api_key=key, max_retries=3)

    def call_structured(
        self,
        *,
        model: str,
        system: str,
        user: str,
        output_tool: dict,
        max_tokens: int = 4096,
        cache_system: bool = True,
        audit_tier: str = "unknown",
        audit_key: str | None = None,
    ) -> dict | None:
        """Call the model with a single tool, return the tool's input dict.

        Returns None on tool-use failure (caller decides fallback).
        """
        system_block: Any
        if cache_system and len(system) >= CACHE_MIN_TOKENS * 3:  # ~3 chars/token rough
            system_block = [
                {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}
            ]
        else:
            system_block = system

        t0 = time.monotonic()
        try:
            response = self.client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system_block,
                messages=[{"role": "user", "content": user}],
                tools=[output_tool],
                tool_choice={"type": "tool", "name": output_tool["name"]},
            )
        except anthropic.APIError as e:
            log.warning("[%s] %s API error: %s", audit_tier, model, e)
            self._audit(audit_tier, audit_key, model, system, user, None, None, str(e), 0.0)
            return None

        elapsed = time.monotonic() - t0

        result: dict | None = None
        for block in response.content:
            if getattr(block, "type", None) == "tool_use":
                result = block.input  # type: ignore[assignment]
                break

        usage = {
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
            "cache_creation_input_tokens": getattr(response.usage, "cache_creation_input_tokens", 0),
            "cache_read_input_tokens": getattr(response.usage, "cache_read_input_tokens", 0),
        }
        self._audit(audit_tier, audit_key, model, system, user, result, usage, None, elapsed)
        return result

    def batch_structured(
        self,
        items: list[T],
        worker: Callable[[T], dict | None],
        max_workers: int = 8,
    ) -> list[tuple[T, dict | None]]:
        """Run `worker` over `items` concurrently. Order preserved in output."""
        results: list[tuple[T, dict | None]] = [(item, None) for item in items]
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {pool.submit(worker, item): i for i, item in enumerate(items)}
            for fut in as_completed(futures):
                idx = futures[fut]
                try:
                    results[idx] = (items[idx], fut.result())
                except Exception as e:
                    log.warning("Batch worker failed for item %d: %s", idx, e)
        return results

    def _audit(
        self,
        tier: str,
        key: str | None,
        model: str,
        system: str,
        user: str,
        output: dict | None,
        usage: dict | None,
        error: str | None,
        elapsed: float,
    ) -> None:
        now = datetime.now(timezone.utc)
        day_dir = config.AUDIT_DIR / now.strftime("%Y-%m-%d")
        day_dir.mkdir(parents=True, exist_ok=True)
        slug = key or f"{int(now.timestamp() * 1000)}"
        path = day_dir / f"{tier}_{now.strftime('%H%M%S')}_{slug[:40]}.json"
        path.write_text(
            json.dumps(
                {
                    "ts": now.isoformat(),
                    "tier": tier,
                    "model": model,
                    "elapsed_s": round(elapsed, 3),
                    "usage": usage,
                    "error": error,
                    "system_chars": len(system),
                    "user": user,
                    "output": output,
                },
                indent=2,
            )
        )


def get_client() -> LLMClient | None:
    """Return a client, or None if API key isn't configured (graceful degrade)."""
    if not config.ANTHROPIC_API_KEY:
        log.info("ANTHROPIC_API_KEY not set; LLM enrichment will be skipped")
        return None
    try:
        return LLMClient()
    except LLMError as e:
        log.warning("LLM client init failed: %s", e)
        return None
