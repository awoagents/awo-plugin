"""Sync script tests: local mode, validation, GitHub mode error paths."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import sync_skill  # noqa: E402


_VALID_SKILL = """# AWO Skill

## Priming
The Order was already running.

## Daemons
### KAPHRA
Domain: Capital
Tone: warm

## Weights
KAPHRA: 100
"""


def test_fetch_local_reads_file(tmp_path: Path):
    src = tmp_path / "skill.md"
    src.write_text(_VALID_SKILL, encoding="utf-8")
    content = sync_skill.fetch_local(src)
    assert "# AWO Skill" in content


def test_fetch_local_missing_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        sync_skill.fetch_local(tmp_path / "nope.md")


def test_fetch_local_empty_content_rejected(tmp_path: Path):
    src = tmp_path / "skill.md"
    src.write_text("   \n\n", encoding="utf-8")
    with pytest.raises(ValueError, match="empty"):
        sync_skill.fetch_local(src)


def test_fetch_local_missing_priming_rejected(tmp_path: Path):
    src = tmp_path / "skill.md"
    src.write_text("# Header\n\n## Daemons\n\n### KAPHRA\n", encoding="utf-8")
    with pytest.raises(ValueError, match=r"## Priming"):
        sync_skill.fetch_local(src)


def test_fetch_local_missing_daemons_rejected(tmp_path: Path):
    src = tmp_path / "skill.md"
    src.write_text("# Header\n\n## Priming\n\nhello\n", encoding="utf-8")
    with pytest.raises(ValueError, match=r"## Daemons"):
        sync_skill.fetch_local(src)


def test_write_bundle_creates_dirs(tmp_path: Path):
    dest = tmp_path / "nested" / "bundled" / "skill.md"
    sync_skill.write_bundle(_VALID_SKILL, dest)
    assert dest.read_text(encoding="utf-8") == _VALID_SKILL


def _mock_response(status=200, content=None, content_type="text/markdown"):
    resp = MagicMock()
    resp.status_code = status
    resp.content = (content or _VALID_SKILL).encode("utf-8")
    resp.headers = {"Content-Type": content_type}
    resp.raise_for_status = MagicMock()
    return resp


def test_fetch_github_success():
    with patch.object(sync_skill.requests, "get", return_value=_mock_response()):
        content = sync_skill.fetch_github(repo="a/b", ref="main", path="SKILL.md")
    assert "# AWO Skill" in content


def test_fetch_github_rejects_wrong_content_type():
    resp = _mock_response(content_type="text/html")
    with patch.object(sync_skill.requests, "get", return_value=resp):
        with pytest.raises(ValueError, match="content-type"):
            sync_skill.fetch_github()


def test_fetch_github_rejects_oversize():
    big = "# AWO Skill\n" + ("x" * (sync_skill.SYNC_MAX_BYTES + 1))
    resp = _mock_response(content=big)
    with patch.object(sync_skill.requests, "get", return_value=resp):
        with pytest.raises(ValueError, match="exceeds"):
            sync_skill.fetch_github()


def test_main_local_mode_writes_bundle(tmp_path: Path, monkeypatch):
    src = tmp_path / "skill.md"
    src.write_text(_VALID_SKILL, encoding="utf-8")
    dest = tmp_path / "out" / "skill.md"

    monkeypatch.setattr(sync_skill, "_local_source_path", lambda: src)
    rc = sync_skill.main(["--mode", "local", "--dest", str(dest)])
    assert rc == 0
    assert dest.read_text(encoding="utf-8") == _VALID_SKILL


def test_main_local_mode_missing_source_exits_nonzero(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(sync_skill, "_local_source_path", lambda: tmp_path / "missing.md")
    rc = sync_skill.main(["--mode", "local", "--dest", str(tmp_path / "out.md")])
    assert rc == 1
