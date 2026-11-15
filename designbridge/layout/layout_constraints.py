"""Registry for always-on layout hard constraints loaded from skills/layout-constraints/*/SKILL.md."""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from designbridge.layout._skill_frontmatter import iter_skill_frontmatter


@dataclass
class LayoutConstraintCard:
    name: str
    description: str
    enforce: str
    order: int = 99
    parameters: dict = field(default_factory=dict)


_ROOT = Path(__file__).resolve().parent.parent.parent / "skills" / "layout-constraints"


@lru_cache(maxsize=None)
def load_layout_constraints() -> list[LayoutConstraintCard]:
    cards = [
        LayoutConstraintCard(
            name=str(fm.get("name", skill_id)),
            description=str(fm.get("description", "")),
            enforce=str(fm.get("enforce", "")),
            order=int(fm.get("order", 99)),
            parameters=fm.get("parameters") or {},
        )
        for skill_id, fm in iter_skill_frontmatter(_ROOT)
    ]
    return sorted(cards, key=lambda c: c.order)
