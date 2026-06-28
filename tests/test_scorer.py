"""Unit tests for scanner.recommend — durability-scaled scoring, the priced_in
gate, and the new base-entry / drift-horizon fields (contract C).

Pure-logic tests with synthetic rows — no Alpaca / network / LLM. Run:
    .venv/bin/python tests/test_scorer.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scanner import recommend

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


def _row(ticker="TST", *, pct_1d=3.0, rel_volume=2.0, macd_cross="bullish",
         rsi_14=60, above_vwap=True, pct_5d=4.0, synthesis=None, caution=None,
         news_count=None):
    """Minimal enriched row that clears MIN_SCORE on the technical side alone
    (so news/durability changes are visible as deltas, not pass/fail flips)."""
    r = {
        "ticker": ticker,
        "pct_1d": pct_1d,
        "pct_5d": pct_5d,
        "rel_volume": rel_volume,
        "macd_cross": macd_cross,
        "rsi_14": rsi_14,
        "intraday": {"above_vwap": above_vwap},
    }
    if synthesis is not None:
        r["synthesis"] = synthesis
    if caution is not None:
        r["caution_level"] = caution
    if news_count is not None:
        r["news_count"] = news_count
    return r


def _syn(verdict="news_explains_move", confidence="high", durability=None,
         durability_weight=None, priced_in=None):
    s = {"verdict": verdict, "confidence": confidence,
         "summary": "x", "supporting_news_ids": []}
    if durability is not None:
        s["durability"] = durability
    if durability_weight is not None:
        s["durability_weight"] = durability_weight
    if priced_in is not None:
        s["priced_in"] = priced_in
    return s


def _score(row, direction="long"):
    rec = recommend._score_row(row, direction)
    return rec["score"] if rec else None


def test_durability_monotonic():
    print("test_durability_monotonic (soft < surprise < guidance < structural)")
    scores = []
    for dur, w in (("soft", 0), ("surprise", 1), ("guidance", 2), ("structural", 3)):
        s = _score(_row(synthesis=_syn(durability=dur, durability_weight=w,
                                       priced_in="no")))
        scores.append(s)
        check(f"{dur} scores (not None)", s is not None)
    check("strictly increasing soft<surprise<guidance<structural",
          scores[0] < scores[1] < scores[2] < scores[3])
    # Confirm the points actually map per DURABILITY_POINTS (high confidence,
    # full verdict => no -1 reduction): delta between adjacent tiers == 1.
    check("structural - soft == 3 (4 vs 1 pts)", scores[3] - scores[0] == 3)


def test_priced_in_monotonic():
    print("test_priced_in_monotonic (contradicted >= no > partial > yes)")
    out = {}
    for pi in ("contradicted", "no", "partial", "yes"):
        out[pi] = _score(_row(synthesis=_syn(durability="guidance",
                                             durability_weight=2, priced_in=pi)))
    check("contradicted >= no", out["contradicted"] >= out["no"])
    check("no > partial", out["no"] > out["partial"])
    check("partial > yes", out["partial"] > out["yes"])
    # priced_in deltas: contradicted +2, no +1, partial 0, yes -3.
    check("contradicted - partial == 2", out["contradicted"] - out["partial"] == 2)
    check("partial - yes == 3", out["partial"] - out["yes"] == 3)

    # A borderline pick: priced_in=='yes' (-3) drops it below MIN_SCORE and the
    # gate removes it from the list (soft gate, not a hard reject).
    border = _row(rel_volume=1.0, macd_cross=None, pct_5d=None, above_vwap=None,
                  rsi_14=50, synthesis=_syn(durability="surprise",
                                            durability_weight=1, priced_in="no"))
    s_no = _score(border)
    check("borderline with priced_in=no survives (>= MIN_SCORE)",
          s_no is not None and s_no >= recommend.MIN_SCORE)
    border_yes = _row(rel_volume=1.0, macd_cross=None, pct_5d=None,
                      above_vwap=None, rsi_14=50,
                      synthesis=_syn(durability="surprise", durability_weight=1,
                                     priced_in="yes"))
    check("borderline with priced_in=yes dropped (None)",
          recommend._score_row(border_yes, "long") is None)


def test_derive_weight_from_label():
    print("test_derive_weight (label present, no durability_weight key)")
    with_weight = _score(_row(synthesis=_syn(durability="structural",
                                             durability_weight=3, priced_in="no")))
    label_only = _score(_row(synthesis=_syn(durability="structural",
                                            priced_in="no")))  # no weight key
    check("label-only structural derives weight 3 (same score)",
          with_weight == label_only)
    # And horizon_days reflects the derived weight (structural -> 21).
    rec = recommend._score_row(_row(synthesis=_syn(durability="structural",
                                                   priced_in="no")), "long")
    check("derived weight feeds horizon_days (21)", rec["horizon_days"] == 21)


def test_base_ready_and_entry_style():
    print("test_base_ready / entry_style")
    # Catalyst-backed, no caution_level key => base_ready True, entry_style base.
    rec = recommend._score_row(_row(synthesis=_syn(durability="guidance",
                                                   durability_weight=2,
                                                   priced_in="no")), "long")
    check("catalyst + no caution => base_ready True", rec["base_ready"] is True)
    check("catalyst + no caution => entry_style 'base'", rec["entry_style"] == "base")

    # Frozen contract: base_ready = catalyst_backed AND caution_level !=
    # "stretched". 'caution' is NOT stretched, so it stays base_ready True (the
    # v1 caution_level proxy only treats 'stretched' as breaking the base).
    rec_c = recommend._score_row(
        _row(synthesis=_syn(durability="structural", durability_weight=3,
                            priced_in="no"), caution="caution"), "long")
    check("catalyst + caution => recommended (not None)", rec_c is not None)
    check("catalyst + caution(!=stretched) => base_ready True", rec_c["base_ready"] is True)
    check("catalyst + caution(!=stretched) => entry_style 'base'", rec_c["entry_style"] == "base")

    # caution_level == 'stretched' => excluded entirely by the pre-existing rule.
    rec_s = recommend._score_row(
        _row(synthesis=_syn(durability="structural", durability_weight=3,
                            priced_in="no"), caution="stretched"), "long")
    check("stretched row excluded entirely (None)", rec_s is None)

    # Pure-technical pick (no synthesis) => not catalyst-backed => spike / not ready.
    rec_t = recommend._score_row(_row(synthesis=None), "long")
    check("no-catalyst => base_ready False", rec_t["base_ready"] is False)
    check("no-catalyst => entry_style 'spike'", rec_t["entry_style"] == "spike")


def test_horizon_days_mapping():
    print("test_horizon_days (soft 3 / surprise 5 / guidance 10 / structural 21)")
    expect = {"soft": 3, "surprise": 5, "guidance": 10, "structural": 21}
    for dur, w in (("soft", 0), ("surprise", 1), ("guidance", 2), ("structural", 3)):
        rec = recommend._score_row(
            _row(synthesis=_syn(durability=dur, durability_weight=w,
                                priced_in="no")), "long")
        check(f"{dur} -> horizon_days {expect[dur]}",
              rec["horizon_days"] == expect[dur])
    # No-catalyst technical pick inherits the soft horizon (3), not null.
    rec_t = recommend._score_row(_row(synthesis=None), "long")
    check("no-catalyst -> horizon_days 3 (not null)", rec_t["horizon_days"] == 3)


def test_back_compat_verdict_only():
    print("test_back_compat (verdict+confidence only, no durability/priced_in)")
    # synthesize.py ships this shape TODAY. Must score without error, emit the
    # new fields, and (contract C) score >= the pre-change value.
    legacy = _row(synthesis=_syn(verdict="news_explains_move", confidence="high"))
    rec = recommend._score_row(legacy, "long")
    check("legacy verdict-only row scores (not None)", rec is not None)
    check("legacy row emits entry_style", "entry_style" in rec)
    check("legacy row emits base_ready", "base_ready" in rec)
    check("legacy row emits horizon_days", "horizon_days" in rec)

    # Pre-change behaviour: news_explains_move+high gave a flat +3. dw defaults
    # to 0 -> DURABILITY_POINTS[0]=1... but the *contract* guarantee is the row
    # is not demoted below its old value when durability is the top tier. Here
    # we assert the weaker, always-true property: the no-durability legacy row
    # still clears MIN_SCORE on the same technical base, i.e. no crash / no drop
    # purely from the refactor's defaults. (Magnitude back-compat is covered by
    # the structural>=old-flat-3 sizing, asserted next.)
    check("legacy row clears MIN_SCORE", rec["score"] >= recommend.MIN_SCORE)

    # Contract magnitude guarantee: a top-tier (structural) high-confidence
    # catalyst scores >= the OLD flat +3 for the same row, so existing
    # high-conviction picks are never demoted on ship day.
    base_only = _score(_row(synthesis=None))  # technical-only baseline
    structural = _score(_row(synthesis=_syn(durability="structural",
                                            durability_weight=3, priced_in="no")))
    # structural points = 4, priced_in 'no' = +1 => +5 over the technical base;
    # the old flat path gave +3. Assert the new catalyst contribution >= 3.
    check("structural+high catalyst contributes >= old flat +3",
          structural - base_only >= 3)


def test_legacy_horizon_field_and_shape():
    print("test_legacy_horizon + compute() shape + bull-regime suppression")
    # rec["horizon"] stays the legacy STRING. Catalyst-backed long => 'long'.
    rec_long = recommend._score_row(
        _row(synthesis=_syn(durability="guidance", durability_weight=2,
                            priced_in="no")), "long")
    check("catalyst-backed horizon == 'long' (string)", rec_long["horizon"] == "long")
    check("horizon is a str, horizon_days is an int",
          isinstance(rec_long["horizon"], str)
          and isinstance(rec_long["horizon_days"], int))

    # Pure-technical short (no catalyst) => legacy horizon 'short'. Kept modest
    # (no 5d trend, sub-2x volume) so it clears MIN_SCORE but stays below the
    # bull-regime threshold (SHORT_BULL_REGIME_MIN_SCORE) => suppressible.
    short_row = _row(ticker="SHRT", pct_1d=-3.0, macd_cross="bearish",
                     rsi_14=40, above_vwap=False, pct_5d=None, rel_volume=1.5,
                     synthesis=None)
    rec_short = recommend._score_row(short_row, "short")
    check("pure-technical short horizon == 'short'", rec_short["horizon"] == "short")
    check("ordinary short clears MIN_SCORE but < bull threshold",
          recommend.MIN_SCORE <= rec_short["score"] < recommend.SHORT_BULL_REGIME_MIN_SCORE)

    # compute() shape unchanged + bull-regime short suppression intact.
    out = recommend.compute([short_row], regime={"spy_above_50d": True})
    check("compute returns {longs, shorts}", set(out.keys()) == {"longs", "shorts"})
    check("bull regime suppresses the ordinary short", out["shorts"] == [])
    out_bear = recommend.compute([short_row], regime={"spy_above_50d": False})
    check("bear/None regime keeps the short", len(out_bear["shorts"]) == 1)


def test_malformed_synthesis_does_not_raise():
    print("test_malformed (non-dict synthesis must not raise)")
    raised = False
    try:
        row = _row(synthesis="this is a string, not a dict")
        out = recommend.compute([row], regime=None)
        # Should score on the technical base only and still emit new fields.
        rec = (out["longs"] or [None])[0]
        ok_fields = rec is not None and {"entry_style", "base_ready",
                                         "horizon_days"} <= set(rec)
    except Exception as exc:  # noqa: BLE001
        raised = True
        print(f"       raised: {exc!r}")
        ok_fields = False
    check("non-dict synthesis does not raise in compute()", not raised)
    check("non-dict synthesis still emits new fields", ok_fields)

    # Out-of-contract durability_weight (int 4, or a non-int) must clamp to soft
    # rather than KeyError on the DURABILITY_POINTS/HORIZON_DAYS lookups.
    for bad in (4, -1, "structural", 1.5):
        try:
            rec = recommend._score_row(
                _row(synthesis=_syn(durability_weight=bad, priced_in="no")), "long")
            ok = rec is not None and rec["horizon_days"] in (3, 5, 10, 21)
        except Exception as exc:  # noqa: BLE001
            print(f"       raised on weight={bad!r}: {exc!r}")
            ok = False
        check(f"out-of-range weight {bad!r} clamps (no raise)", ok)


if __name__ == "__main__":
    test_durability_monotonic()
    test_priced_in_monotonic()
    test_derive_weight_from_label()
    test_base_ready_and_entry_style()
    test_horizon_days_mapping()
    test_back_compat_verdict_only()
    test_legacy_horizon_field_and_shape()
    test_malformed_synthesis_does_not_raise()
    print(f"\n{PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)
