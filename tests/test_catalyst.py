"""Unit tests for scanner.llm.synthesize — catalyst durability + priced-in.

Pure schema + helper tests for the durability/durability_weight/priced_in fields
the synthesis tier now emits. NO LLMClient, NO network, NO API — only the static
tool schema and the deterministic Python helpers/normalizer. Run:
  .venv/bin/python tests/test_catalyst.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scanner.llm import synthesize

PASS = 0
FAIL = 0


def check(name: str, cond: bool) -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok   {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name}")


def test_durability_weight():
    print("test_durability_weight (deterministic map, null/invalid → 0)")
    check("soft → 0", synthesize._durability_weight("soft") == 0)
    check("surprise → 1", synthesize._durability_weight("surprise") == 1)
    check("guidance → 2", synthesize._durability_weight("guidance") == 2)
    check("structural → 3", synthesize._durability_weight("structural") == 3)
    check("None → 0", synthesize._durability_weight(None) == 0)
    check("garbage → 0", synthesize._durability_weight("garbage") == 0)
    check("empty str → 0", synthesize._durability_weight("") == 0)


def test_normalizer():
    print("test_normalizer (every stored dict carries all three keys)")

    # valid durability → matching weight, untouched priced_in
    a = synthesize._normalize({"verdict": "news_explains_move", "durability": "structural",
                               "priced_in": "contradicted"})
    check("structural → weight 3", a["durability_weight"] == 3)
    check("structural label kept", a["durability"] == "structural")
    check("contradicted priced_in kept", a["priced_in"] == "contradicted")

    # bogus durability → None + weight 0
    b = synthesize._normalize({"durability": "bogus"})
    check("bogus durability → None", b["durability"] is None)
    check("bogus durability → weight 0", b["durability_weight"] == 0)

    # empty dict (old-shape) → full defaults
    c = synthesize._normalize({})
    check("empty: durability None", c["durability"] is None)
    check("empty: weight 0", c["durability_weight"] == 0)
    check("empty: priced_in 'no'", c["priced_in"] == "no")

    # invalid priced_in → "no"
    d = synthesize._normalize({"priced_in": "sorta"})
    check("invalid priced_in → 'no'", d["priced_in"] == "no")

    # each valid priced_in enum value survives normalization
    for v in ("no", "partial", "yes", "contradicted"):
        check(f"priced_in '{v}' survives", synthesize._normalize({"priced_in": v})["priced_in"] == v)

    # idempotence: normalizing twice is stable
    once = synthesize._normalize({"durability": "guidance", "priced_in": "yes"})
    twice = synthesize._normalize(dict(once))
    check("idempotent durability_weight", twice["durability_weight"] == 2)
    check("idempotent priced_in", twice["priced_in"] == "yes")

    # pre-existing keys are left intact
    e = synthesize._normalize({"summary": "x", "verdict": "partial_explanation",
                               "confidence": "high", "supporting_news_ids": ["n1"]})
    check("summary untouched", e["summary"] == "x")
    check("verdict untouched", e["verdict"] == "partial_explanation")
    check("confidence untouched", e["confidence"] == "high")
    check("supporting_news_ids untouched", e["supporting_news_ids"] == ["n1"])


def test_schema_integrity():
    print("test_schema_integrity (static — no API)")
    props = synthesize.SYNTH_TOOL["input_schema"]["properties"]

    check("durability in schema", "durability" in props)
    check("durability enum exact",
          props["durability"]["enum"] == ["structural", "guidance", "surprise", "soft"])
    check("priced_in in schema", "priced_in" in props)
    check("priced_in enum exact",
          props["priced_in"]["enum"] == ["no", "partial", "yes", "contradicted"])

    # durability_weight is COMPUTED in Python — must NOT be in the schema
    check("durability_weight NOT in schema", "durability_weight" not in props)

    # required list frozen — durability/priced_in deliberately non-required
    req = synthesize.SYNTH_TOOL["input_schema"]["required"]
    check("required unchanged",
          req == ["summary", "supporting_news_ids", "verdict", "confidence"])
    check("durability not required", "durability" not in req)
    check("priced_in not required", "priced_in" not in req)

    # pre-existing keys still present and intact
    for key in ("summary", "verdict", "confidence", "supporting_news_ids"):
        check(f"pre-existing prop {key}", key in props)
    check("verdict enum intact",
          props["verdict"]["enum"]
          == ["news_explains_move", "partial_explanation", "move_unexplained_by_news"])


def test_back_compat():
    print("test_back_compat (stale data/scan.json synthesis won't crash scorer)")
    # An OLD-shape synthesis dict (no durability/priced_in) — what a stale scan.json
    # holds. After normalize it yields weight 0 / priced_in 'no'. We also assert the
    # raw-dict .get() access the scorer uses degrades safely without normalization.
    old = {"summary": "moved on a beat", "verdict": "news_explains_move",
           "confidence": "high", "supporting_news_ids": []}
    check("raw old: durability_weight default 0",
          synthesize._durability_weight(old.get("durability")) == 0)
    check("raw old: priced_in .get default 'no'", old.get("priced_in", "no") == "no")

    norm = synthesize._normalize(dict(old))
    check("normalized old: weight 0", norm["durability_weight"] == 0)
    check("normalized old: priced_in 'no'", norm["priced_in"] == "no")
    check("normalized old: durability None", norm["durability"] is None)


def test_prompt_smoke():
    print("test_prompt_smoke (prompt keeps durability + priced-in sections)")
    sp = synthesize.SYSTEM_PROMPT.lower()
    for word in ("structural", "guidance", "surprise", "soft"):
        check(f"prompt mentions '{word}'", word in sp)
    check("prompt has priced-in section", "priced" in sp)
    check("prompt mentions 'contradicted'", "contradicted" in sp)
    # the deterministic weight map matches the schema enum (no silent drift)
    check("weight map keys == schema enum (as set)",
          set(synthesize._DURABILITY_WEIGHT.keys())
          == set(synthesize.SYNTH_TOOL["input_schema"]["properties"]["durability"]["enum"]))


if __name__ == "__main__":
    test_durability_weight()
    test_normalizer()
    test_schema_integrity()
    test_back_compat()
    test_prompt_smoke()
    print(f"\n{PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)
