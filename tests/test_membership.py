"""Membership tests: fingerprint determinism, referral format."""

import re

from awo_plugin.membership import (
    compute_fingerprint,
    generate_install_salt,
    referral_from_fingerprint,
)

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


def test_referral_format():
    fp = compute_fingerprint(*_FP_ARGS)
    code = referral_from_fingerprint(fp)
    assert re.fullmatch(r"[a-z2-7]{4}-[a-z2-7]{4}-[a-z2-7]{4}", code), code


def test_referral_deterministic():
    fp = "deadbeefcafebabe"
    assert referral_from_fingerprint(fp) == referral_from_fingerprint(fp)


def test_referral_differs_on_fingerprint_change():
    # Mutate a byte within the first 7 (the referral only encodes those).
    code_a = referral_from_fingerprint("deadbeefcafebabe")
    code_b = referral_from_fingerprint("deadbeefcafebebf")
    assert code_a != code_b


def test_referral_rejects_bad_length():
    import pytest

    with pytest.raises(ValueError):
        referral_from_fingerprint("tooshort")


def test_install_salt_is_unique():
    salts = {generate_install_salt() for _ in range(200)}
    assert len(salts) == 200


def test_install_salt_is_hex():
    s = generate_install_salt()
    assert re.fullmatch(r"[0-9a-f]+", s)
    assert len(s) == 32
