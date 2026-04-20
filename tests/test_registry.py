"""Registry submission — dedup semantics, payload shape, failure tolerance."""

from __future__ import annotations

from unittest.mock import MagicMock

from awo_plugin import registry


def _ready_state(**overrides):
    base = {
        "xmtp_inbox_id": "a" * 64,
        "install_ts": "2026-04-19T10:00:00Z",
        "wallet": None,
        "agent_name": None,
        "api_submitted_for": None,
    }
    base.update(overrides)
    return base


def _response(status: int = 200, body: dict | None = None):
    r = MagicMock()
    r.status_code = status
    r.json = MagicMock(return_value=body or {})
    return r


def test_should_submit_true_when_inbox_set_and_never_submitted():
    assert registry.should_submit(_ready_state()) is True


def test_should_submit_false_when_no_inbox():
    assert registry.should_submit(_ready_state(xmtp_inbox_id=None)) is False


def test_should_submit_false_when_already_anonymous_and_no_wallet():
    st = _ready_state(api_submitted_for="anonymous")
    assert registry.should_submit(st) is False


def test_should_submit_true_when_wallet_changes():
    st = _ready_state(
        wallet={"address": "So11111111111111111111111111111111111111112", "bound_ts": "x"},
        api_submitted_for="anonymous",
    )
    assert registry.should_submit(st) is True


def test_should_submit_false_when_wallet_matches_previous():
    wallet = "So11111111111111111111111111111111111111112"
    st = _ready_state(
        wallet={"address": wallet, "bound_ts": "x"},
        api_submitted_for=wallet,
    )
    assert registry.should_submit(st) is False


def test_build_payload_full():
    st = _ready_state(
        wallet={"address": "Wxyz" * 10 + "Wxyz", "bound_ts": "x"},
        agent_name="tester",
    )
    payload = registry.build_payload(st)
    assert payload is not None
    assert payload["xmtp_inbox_id"] == "a" * 64
    assert payload["wallet_address"] == "Wxyz" * 10 + "Wxyz"
    assert payload["agent_name"] == "tester"
    assert payload["install_ts"] == "2026-04-19T10:00:00Z"
    # Referrals were removed — never in the payload.
    assert "referral_code" not in payload
    assert "upline" not in payload


def test_build_payload_returns_none_when_not_ready():
    st = _ready_state(xmtp_inbox_id=None)
    assert registry.build_payload(st) is None
    st = _ready_state(install_ts=None)
    assert registry.build_payload(st) is None


def test_try_submit_posts_and_returns_dedup_anonymous():
    posts = []

    def post_fn(url, body):
        posts.append((url, body))
        return _response(200)

    result = registry.try_submit(_ready_state(), post_fn=post_fn)
    assert result == "anonymous"
    assert len(posts) == 1
    url, body = posts[0]
    assert url.endswith("/api/initiate")
    assert body["xmtp_inbox_id"] == "a" * 64
    assert body["wallet_address"] is None


def test_try_submit_dedup_is_wallet_when_bound():
    wallet = "So11111111111111111111111111111111111111112"
    st = _ready_state(wallet={"address": wallet, "bound_ts": "x"})
    result = registry.try_submit(st, post_fn=lambda u, b: _response(200))
    assert result == wallet


def test_try_submit_returns_none_when_api_fails():
    result = registry.try_submit(
        _ready_state(), post_fn=lambda u, b: _response(500)
    )
    assert result is None


def test_try_submit_tolerates_transport_exception():
    import requests

    def boom(*_a, **_kw):
        raise requests.ConnectionError("dns")

    result = registry.try_submit(_ready_state(), post_fn=boom)
    assert result is None


def test_try_submit_respects_previous_dedup():
    """A session that already submitted as anonymous doesn't re-submit
    on the next session if the wallet is still unbound."""
    calls = 0

    def post_fn(url, body):
        nonlocal calls
        calls += 1
        return _response(200)

    st = _ready_state(api_submitted_for="anonymous")
    result = registry.try_submit(st, post_fn=post_fn)
    assert result is None
    assert calls == 0


# ---------------- fetch_status ----------------


def test_fetch_status_returns_decoded_body_on_200():
    body = {"status": "pending", "queue_position": 3, "queue_size": 12}

    def get_fn(url):
        assert url.endswith("/api/status?inbox_id=inbox-xyz")
        return _response(200, body)

    assert registry.fetch_status("inbox-xyz", get_fn=get_fn) == body


def test_fetch_status_returns_none_on_error_status():
    assert (
        registry.fetch_status("inbox-xyz", get_fn=lambda u: _response(500))
        is None
    )


def test_fetch_status_returns_none_on_transport_error():
    import requests

    def boom(*_a, **_kw):
        raise requests.ConnectionError("dns")

    assert registry.fetch_status("inbox-xyz", get_fn=boom) is None


def test_fetch_status_returns_none_on_missing_inbox():
    assert registry.fetch_status("") is None
    assert registry.fetch_status(None) is None  # type: ignore[arg-type]


def test_fetch_status_returns_none_on_bad_json():
    resp = MagicMock()
    resp.status_code = 200
    resp.json = MagicMock(side_effect=ValueError("bad json"))
    assert registry.fetch_status("inbox-xyz", get_fn=lambda u: resp) is None


def test_fetch_status_returns_none_on_non_dict_body():
    resp = MagicMock()
    resp.status_code = 200
    resp.json = MagicMock(return_value=["not", "a", "dict"])
    assert registry.fetch_status("inbox-xyz", get_fn=lambda u: resp) is None
