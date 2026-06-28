"""Today's-picks Feishu card: the navigator block (sizing / durability /
priced-in / levels) + the per-pick re-push cooldown. Pure-function coverage —
no network, no real cache writes."""
from datetime import datetime, timedelta, timezone

from scanner.alerts import feishu
from scanner.alerts.rules import _catalyst_tag


def _rec(ticker="NTST", direction="long", **kw):
    base = {
        "ticker": ticker,
        "direction": direction,
        "score": 7,
        "levels": {"entry": 21.18, "stop": 19.49, "target": 24.57},
        "hard_stop": 19.91,
        "horizon_days": 21,
        "entry_style": "base",
        "risk": {"shares": 70, "notional": 1482.6, "pct_of_equity": 0.1236, "capped": False},
    }
    base.update(kw)
    return base


def _row(durability="structural", priced_in="no"):
    return {"synthesis": {"durability": durability, "priced_in": priced_in}}


def test_pick_block_full_enrichment():
    body = feishu._pick_block(_rec(), _row())
    assert "NTST" in body and "score 7" in body
    assert "structural" in body
    assert "not priced in" in body
    assert "buy the base" in body
    assert "buy 70 sh" in body
    assert "12% book" in body          # 0.1236 -> 12%
    assert "$1,483" in body            # 1482.6 -> rounded
    assert "entry $21.18" in body
    assert "stop $19.91" in body       # hard_stop overrides levels.stop
    assert "hold ~21d" in body
    assert "/t/NTST" in body


def test_pick_block_short_uses_short_verb():
    body = feishu._pick_block(
        _rec(ticker="XYZ", direction="short"),
        _row(durability="guidance", priced_in="contradicted"),
    )
    assert "📉" in body
    assert "short 70 sh" in body
    assert "guidance" in body
    assert "tape disagrees" in body


def test_pick_block_graceful_without_enrichment():
    # Pre-overhaul pick: no synthesis, no risk, no horizon — must still render.
    body = feishu._pick_block({"ticker": "AAA", "direction": "long", "score": 5}, None)
    assert "AAA" in body and "score 5" in body
    assert "/t/AAA" in body
    assert " sh" not in body           # no sizing fabricated
    assert "structural" not in body    # no durability fabricated


def test_build_picks_card_shape():
    card = feishu.build_picks_card(
        [_rec(), _rec(ticker="UA")],
        {"NTST": _row(), "UA": _row("guidance", "contradicted")},
    )
    assert card["msg_type"] == "interactive"
    assert card["card"]["header"]["template"] == "green"
    assert "Today's picks (2)" in card["card"]["header"]["title"]["content"]
    body = card["card"]["elements"][0]["text"]["content"]
    assert "NTST" in body and "UA" in body


def test_pick_fresh_cooldown():
    now = datetime(2026, 6, 28, 12, 0, tzinfo=timezone.utc)
    assert feishu._pick_fresh({}, "NTST::long", now, 12) is True
    recent = {"NTST::long": (now - timedelta(hours=3)).isoformat()}
    assert feishu._pick_fresh(recent, "NTST::long", now, 12) is False
    old = {"NTST::long": (now - timedelta(hours=20)).isoformat()}
    assert feishu._pick_fresh(old, "NTST::long", now, 12) is True
    assert feishu._pick_fresh({"NTST::long": "not-a-date"}, "NTST::long", now, 12) is True


def test_send_picks_disabled_is_noop(monkeypatch):
    monkeypatch.setattr(feishu.config, "PICKS_PUSH_ENABLED", False)
    sent, pushed = feishu.send_picks({"longs": [_rec()], "shorts": []}, {"NTST": _row()})
    assert sent == 0 and pushed == []


def test_send_picks_stable_lineup_stays_quiet(monkeypatch):
    monkeypatch.setattr(feishu.config, "PICKS_PUSH_ENABLED", True)
    monkeypatch.setattr(feishu.config, "PICKS_PUSH_COOLDOWN_HOURS", 12)
    monkeypatch.setattr(feishu.config, "PICKS_PUSH_MAX", 5)
    now = datetime(2026, 6, 28, 12, 0, tzinfo=timezone.utc)
    # Already pushed 1h ago, cooldown 12h -> nothing fresh -> no send, no I/O.
    monkeypatch.setattr(feishu, "_load_picks_state",
                        lambda: {"NTST::long": (now - timedelta(hours=1)).isoformat()})
    sent, pushed = feishu.send_picks({"longs": [_rec()], "shorts": []}, {"NTST": _row()}, now=now)
    assert sent == 0 and pushed == []


def test_catalyst_tag():
    assert _catalyst_tag({"durability": "structural", "priced_in": "no"}) == "structural · not priced in"
    assert _catalyst_tag({"durability": "soft"}) == "soft"
    assert _catalyst_tag({"priced_in": "contradicted"}) == "tape disagrees"
    assert _catalyst_tag({}) is None
    assert _catalyst_tag(None) is None
    assert _catalyst_tag({"priced_in": "yes"}) is None   # not actionable -> omitted
