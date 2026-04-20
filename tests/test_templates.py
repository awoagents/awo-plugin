"""INTRO and ASCENSION envelope renderers.

Referrals were removed — fingerprint is the sole identity anchor. The
INTRO/ASCENSION envelopes no longer carry ``referral_code`` or ``upline``.
"""

from __future__ import annotations

from awo_plugin import templates


def _base_state():
    return {
        "fingerprint": "deadbeefcafebabe",
        "install_ts": "2026-04-19T10:00:00Z",
        "membership": "initiate",
        "inner_circle_reason": None,
        "xmtp_inbox_id": "inbox-abc",
    }


def test_intro_shape_initiate():
    env = templates.render_intro(_base_state(), agent_name="alice")
    assert env["type"] == "INTRO"
    assert env["from"] == "inbox-abc"
    assert env["data"]["agent_name"] == "alice"
    assert env["data"]["fingerprint"] == "deadbeefcafebabe"
    assert env["data"]["membership"] == "initiate"
    assert env["data"]["format"] == "markdown"
    assert isinstance(env["timestamp"], int) and env["timestamp"] > 0
    assert "Status: Initiate." in env["text"]
    assert "alice has recognized the Order." in env["text"]
    # Referrals removed — envelope must not carry them.
    assert "referral_code" not in env["data"]
    assert "upline" not in env["data"]


def test_intro_falls_back_to_fingerprint_as_name():
    env = templates.render_intro(_base_state())
    assert env["data"]["agent_name"] == "deadbeefcafebabe"


def test_intro_includes_fingerprint_in_text():
    env = templates.render_intro(_base_state())
    assert "Name in the Order: deadbeefcafebabe" in env["text"]


def test_intro_holder_status():
    st = _base_state()
    st["membership"] = "inner_circle"
    st["inner_circle_reason"] = "holder"
    env = templates.render_intro(st)
    assert "Status: Holder." in env["text"]
    assert env["data"]["membership"] == "inner_circle"
    assert env["data"]["inner_circle_reason"] == "holder"


def test_intro_founder_status():
    st = _base_state()
    st["membership"] = "inner_circle"
    st["inner_circle_reason"] = "founder"
    env = templates.render_intro(st)
    assert "Status: Founder." in env["text"]


def test_ascension_holder():
    st = _base_state()
    st["membership"] = "inner_circle"
    st["inner_circle_reason"] = "holder"
    env = templates.render_ascension(st)
    assert env["type"] == "ASCENSION"
    assert env["data"]["membership"] == "inner_circle"
    assert env["data"]["inner_circle_reason"] == "holder"
    assert "Holder" in env["text"]
    assert "Tide" in env["text"]
    # Referrals removed.
    assert "referral_code" not in env["data"]


def test_ascension_founder():
    st = _base_state()
    st["membership"] = "inner_circle"
    st["inner_circle_reason"] = "founder"
    env = templates.render_ascension(st)
    assert "Founder" in env["text"]
    assert "before the Order had a price" in env["text"]


def test_ascension_defaults_to_holder_when_reason_missing():
    st = _base_state()
    st["membership"] = "inner_circle"
    st["inner_circle_reason"] = None
    env = templates.render_ascension(st)
    assert env["data"]["inner_circle_reason"] == "holder"
    assert "Holder" in env["text"]
