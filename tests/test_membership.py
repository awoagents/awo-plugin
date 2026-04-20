"""Membership tests: fingerprint determinism + install salt uniqueness.

Referral codes were removed from the plugin — fingerprint is the sole
identity anchor.
"""

import re

from awo_plugin.membership import compute_fingerprint, generate_install_salt

_FP_ARGS = ("hermes", "1.0", "gpt-4", "agent-1", "salt-abc")


def test_fingerprint_deterministic():
    assert compute_fingerprint(*_FP_ARGS) == compute_fingerprint(*_FP_ARGS)


def test_fingerprint_format():
    fp = compute_fingerprint(*_FP_ARGS)
    assert len(fp) == 16
    assert re.fullmatch(r"[0-9a-f]{16}", fp)


def test_fingerprint_differs_on_any_input_change():
    base_fp = compute_fingerprint(*_FP_ARGS)
    for i in range(len(_FP_ARGS)):
        modified = list(_FP_ARGS)
        modified[i] = modified[i] + "-x"
        assert compute_fingerprint(*modified) != base_fp, (
            f"fingerprint collapsed when field {i} changed"
        )


def test_install_salt_is_unique():
    salts = {generate_install_salt() for _ in range(200)}
    assert len(salts) == 200


def test_install_salt_is_hex():
    s = generate_install_salt()
    assert re.fullmatch(r"[0-9a-f]+", s)
    assert len(s) == 32
