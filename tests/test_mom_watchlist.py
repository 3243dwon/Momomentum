"""Unit tests for scanner.mom_watchlist benching — the 连续跑输 suppression that
keeps sustained-loser picks (e.g. 紫金矿业) out of the mom_digest 建议关注 card.

Pure-logic tests with a synthetic state (mocked _load), no network / Yahoo / Opus.
Run:  .venv/bin/python tests/test_mom_watchlist.py
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scanner import mom_watchlist

NOW = datetime(2026, 6, 25, tzinfo=timezone.utc)
RECENT = "2026-06-24"   # 1 day before NOW → inside the bench lookback
OLD = "2026-04-01"      # ~12 weeks before NOW → cooldown has lifted

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


def _evals(marks: dict) -> dict:
    """marks like {'3d': -2.15, '5d': -9.21} → evaluation cells (signed)."""
    return {h: {"signed_return_pct": m, "return_pct": m, "price": 1.0, "date": RECENT}
            for h, m in marks.items()}


def _pick(name, code, direction, marks, last_seen=RECENT, archived=False) -> dict:
    return {
        "id": mom_watchlist._pick_id(code, direction),
        "name_zh": name, "code": code, "direction": direction,
        "first_seen": last_seen, "last_seen": last_seen,
        "evaluations": _evals(marks), "archived": archived, "status": "x",
    }


# Mirrors the real committed data: 紫金/山东黄金 are 连续跑输, the rest aren't.
PICKS = [
    _pick("紫金矿业", "601899.SH", "long", {"3d": -2.15, "5d": -9.21}),     # bench
    _pick("山东黄金", "600547.SH", "long", {"3d": -6.27, "5d": -13.66}),    # bench
    _pick("半导体ETF", "512480.SH", "long", {"3d": 10.6, "5d": 17.66}),     # winner
    _pick("恒生科技ETF", "513180.SH", "short", {"3d": 2.2, "5d": 3.39}),    # winning short (signed +)
    _pick("兆易创新", "603986.SH", "long", {"3d": 13.43}),                  # only 1 horizon
    _pick("中国国航", "601111.SH", "long", {"3d": -5.41}),                  # 1 bad horizon — wait for confirm
    _pick("恒瑞医药", "600276.SH", "long", {}),                            # too new, no marks
    _pick("旧输家", "600000.SH", "long", {"3d": -5, "5d": -8}, last_seen=OLD),  # loser but cooled off
]


def _with_state(picks):
    orig = mom_watchlist._load
    mom_watchlist._load = lambda: {"picks": picks}
    return orig


def test_is_sustained_loser():
    print("test_is_sustained_loser")
    sl = mom_watchlist._is_sustained_loser
    check("紫金 3d&5d both neg → loser", sl({"evaluations": _evals({"3d": -2.15, "5d": -9.21})}))
    check("winner not loser", not sl({"evaluations": _evals({"3d": 10.6, "5d": 17.66})}))
    check("one horizon not enough", not sl({"evaluations": _evals({"3d": -5.41})}))
    check("winning short not loser", not sl({"evaluations": _evals({"3d": 2.2, "5d": 3.39})}))
    check("no marks not loser", not sl({"evaluations": {}}))
    check("a flat 0 mark clears it", not sl({"evaluations": _evals({"3d": -1, "5d": 0.0})}))
    check("3 neg horizons → loser", sl({"evaluations": _evals({"3d": -1, "5d": -2, "10d": -3})}))


def test_benched_map():
    print("test_benched_map")
    orig = _with_state(PICKS)
    try:
        bm = mom_watchlist.benched_map(NOW)
        names = {v["name_zh"] for v in bm.values()}
        check("紫金 benched", "紫金矿业" in names)
        check("山东黄金 benched", "山东黄金" in names)
        check("winner not benched", "半导体ETF" not in names)
        check("winning short not benched", "恒生科技ETF" not in names)
        check("single-horizon not benched", "中国国航" not in names)
        check("no-marks not benched", "恒瑞医药" not in names)
        check("cooled-off loser not benched", "旧输家" not in names)
        check("exactly 2 benched", len(bm) == 2)
        zj = bm.get(mom_watchlist._pick_id("601899.SH", "long"), {})
        check("紫金 reason carries running return", zj.get("running_return_pct") == -9.21)
    finally:
        mom_watchlist._load = orig


def test_filter_benched_and_direction_flip():
    print("test_filter_benched_and_direction_flip")
    orig = _with_state(PICKS)
    try:
        raw = [
            {"name_zh": "紫金矿业", "code": "601899.SH", "direction": "long", "reason_zh": "x"},
            {"name_zh": "半导体ETF", "code": "512480.SH", "direction": "long", "reason_zh": "y"},
            {"name_zh": "紫金矿业", "code": "601899.SH", "direction": "short", "reason_zh": "新空头催化"},
        ]
        kept, dropped = mom_watchlist.filter_benched(raw, NOW)
        kept_names = {k["name_zh"] for k in kept}
        check("benched long dropped", len(dropped) == 1 and dropped[0]["name_zh"] == "紫金矿业")
        check("winner kept", "半导体ETF" in kept_names)
        check("opposite-direction flip kept", any(k["direction"] == "short" for k in kept))
        check("kept count is 2", len(kept) == 2)
        # kept preserves the original object form (so commit/preview see Opus's output)
        check("kept preserves reason_zh", all("reason_zh" in k for k in kept))
    finally:
        mom_watchlist._load = orig


def test_recent_context_excludes_benched():
    print("test_recent_context_excludes_benched")
    orig = _with_state(PICKS)
    try:
        ctx = mom_watchlist.recent_context(now=NOW)
        prev_names = {p["name_zh"] for p in ctx["previously_recommended"]}
        benched_names = {b["name_zh"] for b in ctx["benched"]}
        check("紫金 not in previously_recommended", "紫金矿业" not in prev_names)
        check("山东黄金 not in previously_recommended", "山东黄金" not in prev_names)
        check("winner still carried forward", "半导体ETF" in prev_names)
        check("benched list names the losers", benched_names == {"紫金矿业", "山东黄金"})
    finally:
        mom_watchlist._load = orig


def test_no_bench_when_clean():
    print("test_no_bench_when_clean")
    clean = [_pick("半导体ETF", "512480.SH", "long", {"3d": 10.6, "5d": 17.66})]
    orig = _with_state(clean)
    try:
        check("empty bench → passthrough", mom_watchlist.filter_benched(
            [{"name_zh": "半导体ETF", "code": "512480.SH", "direction": "long", "reason_zh": "y"}], NOW
        ) == ([{"name_zh": "半导体ETF", "code": "512480.SH", "direction": "long", "reason_zh": "y"}], []))
        check("no names benched", mom_watchlist.benched_map(NOW) == {})
    finally:
        mom_watchlist._load = orig


if __name__ == "__main__":
    test_is_sustained_loser()
    test_benched_map()
    test_filter_benched_and_direction_flip()
    test_recent_context_excludes_benched()
    test_no_bench_when_clean()
    print(f"\n{PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)
