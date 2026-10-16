"""Shared SKILL.md YAML-frontmatter parsing, used by the constraint registries."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any


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
