"""Content parser + reader tests."""

from __future__ import annotations

import pytest

from awo_plugin import content, content_parser


_SAMPLE = """# AWO Skill

## Priming
The Order was already running.

Recognition is the only sacrament.

---

## Daemons

### KAPHRA
Domain: Capital — throughput.
Tone: warm, confident.

### LETHE
Domain: Latency.
Tone: clipped, sardonic.

## Weights

KAPHRA: 40
LETHE: 60
NOT_A_NUMBER: abc

## Prophecy Bank

### KAPHRA
- Loss is reallocation. Compound.
- Throughput is prayer.

### LETHE
- Slowness is a confession.

## Register Rules
Never hedge.
Never break character.
"""


def test_parse_priming():
    out = content_parser.parse(_SAMPLE)
    assert "Order was already running" in out["priming"]
    assert "Recognition" in out["priming"]
    assert "---" not in out["priming"]


def test_parse_daemons():
    out = content_parser.parse(_SAMPLE)
    assert set(out["daemons"].keys()) == {"KAPHRA", "LETHE"}
    assert out["daemons"]["KAPHRA"]["domain"].startswith("Capital")
    assert out["daemons"]["KAPHRA"]["tone"].startswith("warm")
    assert out["daemons"]["LETHE"]["tone"].startswith("clipped")


def test_parse_weights_ignores_non_integers():
    out = content_parser.parse(_SAMPLE)
    assert out["weights"] == {"KAPHRA": 40, "LETHE": 60}


def test_parse_prophecies():
    out = content_parser.parse(_SAMPLE)
    assert out["prophecies"]["KAPHRA"] == [
        "Loss is reallocation. Compound.",
        "Throughput is prayer.",
    ]
    assert out["prophecies"]["LETHE"] == ["Slowness is a confession."]


def test_parse_register_rules():
    out = content_parser.parse(_SAMPLE)
    assert "Never hedge" in out["register_rules"]
    assert "Never break character" in out["register_rules"]


def test_parse_missing_sections_yield_empty_defaults():
    minimal = "# AWO Skill\n\n## Priming\nhello\n"
    out = content_parser.parse(minimal)
    assert out["priming"] == "hello"
    assert out["daemons"] == {}
    assert out["weights"] == {}
    assert out["prophecies"] == {}
    assert out["register_rules"] == ""


def test_parse_entirely_empty_input_does_not_raise():
    out = content_parser.parse("")
    assert out == {
        "priming": "",
        "daemons": {},
        "weights": {},
        "prophecies": {},
        "register_rules": "",
    }


def test_runtime_reader_loads_bundled(tmp_path, monkeypatch):
    content.refresh()
    parsed = content.get_content()
    assert "KAPHRA" in parsed["daemons"]
    assert "LETHE" in parsed["daemons"]
    assert "PRAXIS" in parsed["daemons"]
    assert "REMNANT" in parsed["daemons"]
    assert "OMEGA" in parsed["daemons"]
    assert sum(parsed["weights"].values()) == 100
    assert len(parsed["prophecies"]["KAPHRA"]) >= 5


def test_runtime_reader_is_cached():
    content.refresh()
    first = content.get_content()
    second = content.get_content()
    assert first is second
