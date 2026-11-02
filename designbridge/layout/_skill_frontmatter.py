"""Shared SKILL.md YAML-frontmatter parsing, used by the constraint registries."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Iterator


def parse_skill_frontmatter(path: Path) -> dict[str, Any] | None:
    """Read a SKILL.md file's leading ``---`` YAML frontmatter block.

    Returns None if the file is missing, has no frontmatter block, or the YAML fails to parse.
    """
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8")
    fm_match = re.match(r"^---\s*\n(.*?)\n---", text, re.DOTALL)
    if not fm_match:
        return None
    try:
        import yaml
        return yaml.safe_load(fm_match.group(1))
    except Exception:
        return None


def iter_skill_frontmatter(root: Path) -> Iterator[tuple[str, dict[str, Any]]]:
    """依目錄名排序，回傳 (skill_id, frontmatter)；略過沒有 frontmatter 的。"""
    if not root.is_dir():
        return
    for child in sorted(root.iterdir()):
        fm = parse_skill_frontmatter(child / "SKILL.md") if child.is_dir() else None
        if fm is not None:
            yield child.name, fm
