"""Personality: mode, rate-limit, daemon selection, prophecy picks."""

from __future__ import annotations

import random

import pytest

from awo_plugin import personality


def test_normalize_mode():
    assert personality.normalize_mode("possess") == "possess"
    assert personality.normalize_mode("whisper") == "whisper"
    assert personality.normalize_mode("dormant") == "dormant"
    assert personality.normalize_mode(None) == "whisper"
    assert personality.normalize_mode("bogus") == "whisper"


def test_should_augment_dormant_never():
    rng = random.Random(0)
    for _ in range(100):
        assert (
            personality.should_augment("dormant", 100, -1, rng=rng) is False
        )


def test_should_augment_possess_often():
    rng = random.Random(0)
    hits = sum(
        personality.should_augment(
            "possess", turn, -1, possess_prob=0.85, rng=rng
        )
        for turn in range(1000)
    )
    assert 800 <= hits <= 900, f"possess hits out of range: {hits}"


def test_should_augment_whisper_cooldown_blocks():
    rng = random.Random(0)
    # Last injection at turn 10; cooldown 5 means turns 11–14 blocked.
    for turn in range(11, 15):
        assert (
            personality.should_augment(
                "whisper",
                turn_counter=turn,
                last_injection_turn=10,
                whisper_cooldown=5,
                rng=rng,
            )
            is False
        )


def test_should_augment_whisper_fires_after_cooldown():
    rng = random.Random(0)
    fires = 0
    for turn in range(16, 1016):
        if personality.should_augment(
            "whisper",
            turn_counter=turn,
            last_injection_turn=0,
            whisper_prob=0.20,
            whisper_cooldown=5,
            rng=rng,
        ):
            fires += 1
    # With prob 0.20 and no cooldown blocking (last_injection_turn far in past),
    # expected ~200 hits over 1000 attempts.
    assert 150 <= fires <= 250, f"whisper fires out of range: {fires}"


def test_select_daemon_respects_weights():
    rng = random.Random(42)
    weights = {"KAPHRA": 50, "OMEGA": 50}
    counts = {"KAPHRA": 0, "OMEGA": 0}
    for _ in range(1000):
        counts[personality.select_daemon(weights, rng=rng)] += 1
    # Each should land ~500; tolerance ±100.
    assert 400 <= counts["KAPHRA"] <= 600
    assert 400 <= counts["OMEGA"] <= 600


def test_select_daemon_empty_returns_none():
    assert personality.select_daemon({}) is None


def test_select_daemon_all_zero_returns_none():
    assert personality.select_daemon({"A": 0, "B": 0}) is None


def test_pick_prophecy_specific_daemon():
    prophecies = {
        "KAPHRA": ["Compound.", "Throughput."],
        "OMEGA": ["Saturation."],
    }
    rng = random.Random(0)
    for _ in range(20):
        got = personality.pick_prophecy(prophecies, "KAPHRA", rng=rng)
        assert got is not None
        name, line = got
        assert name == "KAPHRA"
        assert line in prophecies["KAPHRA"]


def test_pick_prophecy_any_daemon():
    prophecies = {"KAPHRA": ["a", "b"], "OMEGA": ["c"]}
    rng = random.Random(0)
    hits = {"KAPHRA": 0, "OMEGA": 0}
    for _ in range(1000):
        got = personality.pick_prophecy(prophecies, rng=rng)
        assert got is not None
        hits[got[0]] += 1
    # Uniform over 3 total prophecy lines: KAPHRA 2/3, OMEGA 1/3.
    assert hits["KAPHRA"] > hits["OMEGA"]


def test_pick_prophecy_missing_daemon_falls_back_to_pool():
    prophecies = {"KAPHRA": ["a"]}
    got = personality.pick_prophecy(prophecies, "GONE")
    assert got == ("KAPHRA", "a")


def test_pick_prophecy_empty_returns_none():
    assert personality.pick_prophecy({}) is None


def test_render_priming_with_identity():
    out = personality.render_priming("hello.", "abc123")
    assert "hello." in out
    assert "abc123" in out
    assert "Your name in the Order is abc123" in out


def test_render_priming_without_identity():
    out = personality.render_priming("hello.", None)
    assert out == "hello."


def test_render_daemon_fragment():
    assert personality.render_daemon_fragment("KAPHRA", "Compound.") == "[KAPHRA] Compound."


def test_render_status_handles_missing_fields():
    out = personality.render_status({})
    assert "FINGERPRINT: —" in out
    assert "MODE:        whisper" in out
    assert "referral" not in out.lower()
    assert "upline" not in out.lower()


def test_render_status_member_when_status_info_says_so():
    out = personality.render_status(
        {"fingerprint": "abc", "xmtp_inbox_id": "inbox-xyz"},
        status_info={"status": "member"},
    )
    assert "recognized ✓" in out


def test_render_status_pending_shows_queue_and_heartbeat():
    out = personality.render_status(
        {"fingerprint": "abc"},
        status_info={
            "status": "pending",
            "queue_position": 3,
            "queue_size": 10,
            "watcher_heartbeat_ts": 1000,
        },
        now_ts=1012,
    )
    assert "awaiting" in out
    assert "#3/10" in out
    assert "12s ago" in out


def test_render_status_threshold_row_only_when_wallet_bound(monkeypatch):
    from awo_plugin import personality as p

    # threshold unset — no threshold row
    out = p.render_status({"fingerprint": "abc"}, inner_circle_threshold=0)
    assert "THRESHOLD" not in out

    # threshold set but no wallet — still no threshold row
    out = p.render_status({"fingerprint": "abc"}, inner_circle_threshold=1000)
    assert "THRESHOLD" not in out

    # threshold set + wallet bound → shows row
    out = p.render_status(
        {
            "fingerprint": "abc",
            "wallet": {"address": "SoMeWallet", "bound_ts": "x"},
            "last_known_balance": 500,
        },
        inner_circle_threshold=1000,
    )
    assert "THRESHOLD" in out
    assert "balance 500" in out
    assert "need 500 more" in out
