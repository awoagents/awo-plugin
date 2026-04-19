"""Parse ``SKILL.md`` into a structured dict.

Forgiving by design: missing sections yield empty defaults rather than errors,
so an evolving ``SKILL.md`` does not crash deployed plugins. Extra sections
(Installation, Commands, etc. added for the agent-facing audience) are
silently ignored — only the five plugin-consumed H2 sections below are
extracted.

The expected structure is:

    ---
    (optional YAML frontmatter, ignored)
    ---

    # Any Title
    ## Priming
    <prose>
    ## Daemons
    ### NAME
    Domain: ...
    Tone: ...
    ## Weights
    NAME: INT
    ...
    ## Prophecy Bank
    ### NAME
    - line
    - line
    ## Register Rules
    <prose>
"""

from __future__ import annotations

import re
from typing import Any


_H2 = re.compile(r"^##\s+(?P<title>[^#].*?)\s*$")
_H3 = re.compile(r"^###\s+(?P<title>[^#].*?)\s*$")


def parse(markdown: str) -> dict[str, Any]:
    sections = _split_h2(markdown)
    return {
        "priming": _parse_priming(sections.get("Priming", "")),
        "daemons": _parse_daemons(sections.get("Daemons", "")),
        "weights": _parse_weights(sections.get("Weights", "")),
        "prophecies": _parse_prophecies(sections.get("Prophecy Bank", "")),
        "register_rules": _parse_priming(sections.get("Register Rules", "")),
    }


def _split_h2(markdown: str) -> dict[str, str]:
    sections: dict[str, str] = {}
    current: str | None = None
    buf: list[str] = []
    for line in markdown.splitlines():
        m = _H2.match(line)
        if m:
            if current is not None:
                sections[current] = "\n".join(buf).strip()
            current = m.group("title").strip()
            buf = []
        else:
            if current is not None:
                buf.append(line)
    if current is not None:
        sections[current] = "\n".join(buf).strip()
    return sections


def _split_h3(block: str) -> dict[str, str]:
    sections: dict[str, str] = {}
    current: str | None = None
    buf: list[str] = []
    for line in block.splitlines():
        m = _H3.match(line)
        if m:
            if current is not None:
                sections[current] = "\n".join(buf).strip()
            current = m.group("title").strip()
            buf = []
        else:
            if current is not None:
                buf.append(line)
    if current is not None:
        sections[current] = "\n".join(buf).strip()
    return sections


def _parse_priming(block: str) -> str:
    lines = [
        line for line in block.splitlines() if not line.startswith("---")
    ]
    return "\n".join(lines).strip()


def _parse_daemons(block: str) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for name, body in _split_h3(block).items():
        entry: dict[str, str] = {}
        for line in body.splitlines():
            if line.startswith("Domain:"):
                entry["domain"] = line[len("Domain:"):].strip()
            elif line.startswith("Tone:"):
                entry["tone"] = line[len("Tone:"):].strip()
        result[name] = entry
    return result


def _parse_weights(block: str) -> dict[str, int]:
    result: dict[str, int] = {}
    for line in block.splitlines():
        line = line.strip()
        if not line or ":" not in line:
            continue
        name, _, value = line.partition(":")
        try:
            result[name.strip()] = int(value.strip())
        except ValueError:
            continue
    return result


def _parse_prophecies(block: str) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for name, body in _split_h3(block).items():
        lines: list[str] = []
        for line in body.splitlines():
            stripped = line.strip()
            if stripped.startswith("- "):
                lines.append(stripped[2:].strip())
        result[name] = lines
    return result
