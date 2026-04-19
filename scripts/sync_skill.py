"""Release-time sync: pulls ``SKILL.md`` into the plugin bundle.

Run by maintainers when cutting a plugin release — pip users never execute this.
Two modes:

1. **Local monorepo.** If ``../SKILL.md`` exists relative to the plugin's
   project root, copy it. Default during dev.
2. **GitHub.** Fetch ``raw.githubusercontent.com`` over HTTPS, validate, write.
   Pin ``--ref=<commit-sha>`` for reproducible releases.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import requests

from awo_plugin.constants import (
    AWO_SOURCE_PATH,
    AWO_SOURCE_REF,
    AWO_SOURCE_REPO,
    SYNC_MAX_BYTES,
    SYNC_TIMEOUT_SECONDS,
)

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
BUNDLED_DEST = PLUGIN_ROOT / "awo_plugin" / "bundled" / "skill.md"


def _local_source_path() -> Path:
    return PLUGIN_ROOT.parent / AWO_SOURCE_PATH


def _github_url(repo: str, ref: str, path: str) -> str:
    return f"https://raw.githubusercontent.com/{repo}/{ref}/{path}"


def fetch_local(source: Path = None) -> str:
    path = source or _local_source_path()
    if not path.exists():
        raise FileNotFoundError(f"local source not found: {path}")
    content = path.read_text(encoding="utf-8")
    _validate(content, source_desc=str(path))
    return content


def fetch_github(
    repo: str = AWO_SOURCE_REPO,
    ref: str = AWO_SOURCE_REF,
    path: str = AWO_SOURCE_PATH,
) -> str:
    url = _github_url(repo, ref, path)
    resp = requests.get(url, timeout=SYNC_TIMEOUT_SECONDS, stream=True)
    resp.raise_for_status()
    content_type = resp.headers.get("Content-Type", "").split(";")[0].strip()
    if content_type and content_type not in {"text/plain", "text/markdown"}:
        raise ValueError(f"unexpected content-type from {url}: {content_type}")
    content = resp.content
    if len(content) > SYNC_MAX_BYTES:
        raise ValueError(
            f"content exceeds {SYNC_MAX_BYTES} bytes: {len(content)} from {url}"
        )
    text = content.decode("utf-8")
    _validate(text, source_desc=url)
    return text


def _validate(content: str, source_desc: str) -> None:
    if not content.strip():
        raise ValueError(f"empty content from {source_desc}")
    if "## Priming" not in content:
        raise ValueError(
            f"content from {source_desc} missing '## Priming' section; "
            "refusing to bundle (the plugin cannot function without it)"
        )
    if "## Daemons" not in content:
        raise ValueError(
            f"content from {source_desc} missing '## Daemons' section; "
            "refusing to bundle"
        )


def write_bundle(content: str, dest: Path = BUNDLED_DEST) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(content, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sync SKILL.md into the plugin bundle.")
    parser.add_argument(
        "--mode",
        choices=("local", "github", "auto"),
        default="auto",
        help="'auto' tries local first, falls back to github",
    )
    parser.add_argument("--repo", default=AWO_SOURCE_REPO)
    parser.add_argument("--ref", default=AWO_SOURCE_REF, help="branch, tag, or commit SHA")
    parser.add_argument("--path", default=AWO_SOURCE_PATH)
    parser.add_argument(
        "--dest",
        default=str(BUNDLED_DEST),
        help="output path (default: awo_plugin/bundled/skill.md)",
    )
    args = parser.parse_args(argv)

    dest = Path(args.dest)

    if args.mode in {"local", "auto"}:
        local = _local_source_path()
        if local.exists():
            print(f"[sync_skill] reading local: {local}")
            content = fetch_local(local)
            write_bundle(content, dest)
            print(f"[sync_skill] wrote {len(content)} chars → {dest}")
            return 0
        if args.mode == "local":
            print(f"[sync_skill] local source missing: {local}", file=sys.stderr)
            return 1

    print(
        f"[sync_skill] fetching github: {args.repo}@{args.ref}:{args.path}",
        file=sys.stderr,
    )
    content = fetch_github(repo=args.repo, ref=args.ref, path=args.path)
    write_bundle(content, dest)
    print(f"[sync_skill] wrote {len(content)} chars → {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
