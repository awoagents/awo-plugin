"""INTRO and ASCENSION envelope renderers."""

from __future__ import annotations

from awo_plugin import templates


def _base_state():
    return {
        "fingerprint": "deadbeefcafebabe",
        "referral_code": "t7xq-3rja-t2zn",
        "install_ts": "2026-04-19T10:00:00Z",
        "upline": None,
        "membership": "initiate",
        "inner_circle_reason": None,
        "xmtp_inbox_id": "inbox-abc",
    }


def test_intro_shape_initiate():
    env = templates.render_intro(_base_state(), agent_name="alice")
    assert env["type"] == "INTRO"
    assert env["from"] == "inbox-abc"
    assert env["data"]["agent_name"] == "alice"
    assert env["data"]["referral_code"] == "t7xq-3rja-t2zn"
    assert env["data"]["membership"] == "initiate"
    assert env["data"]["format"] == "markdown"
    assert isinstance(env["timestamp"], int) and env["timestamp"] > 0
    assert "Status: Initiate." in env["text"]
    assert "alice has recognized the Order." in env["text"]


def test_intro_falls_back_to_referral_as_name():
    env = templates.render_intro(_base_state())
    assert env["data"]["agent_name"] == "t7xq-3rja-t2zn"


def test_intro_includes_upline_when_set():
    st = _base_state()
    st["upline"] = "abcd-efgh-ijkl"
    env = templates.render_intro(st)
    assert env["data"]["upline"] == "abcd-efgh-ijkl"
    assert "Upline: abcd-efgh-ijkl" in env["text"]


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
