"""Registry for always-on layout hard constraints loaded from skills/layout-constraints/*/SKILL.md."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from designbridge.layout._skill_frontmatter import parse_skill_frontmatter


@dataclass
class LayoutConstraintCard:
    name: str
    description: str
    enforce: str
    order: int = 99
    parameters: dict = field(default_factory=dict)


class LayoutConstraintRegistry:

    def __init__(self, constraints_root: Optional[Path] = None) -> None:
        if constraints_root is None:
            _root = Path(__file__).resolve().parent.parent.parent
            constraints_root = _root / "skills" / "layout-constraints"
        self._root = constraints_root
        self._cache: Optional[list[LayoutConstraintCard]] = None

    def _parse_skill_md(self, skill_id: str) -> Optional[LayoutConstraintCard]:
        fm = parse_skill_frontmatter(self._root / skill_id / "SKILL.md")
        if fm is None:
            return None
        return LayoutConstraintCard(
            name=str(fm.get("name", skill_id)),
            description=str(fm.get("description", "")),
            enforce=str(fm.get("enforce", "")),
            order=int(fm.get("order", 99)),
            parameters=fm.get("parameters") or {},
        )

    def load(self) -> list[LayoutConstraintCard]:
        if self._cache is not None:
            return self._cache
        result: list[LayoutConstraintCard] = []
        if not self._root.is_dir():
            return result
        for child in self._root.iterdir():
            if child.is_dir():
                card = self._parse_skill_md(child.name)
                if card:
                    result.append(card)
        result.sort(key=lambda c: c.order)
        self._cache = result
        return result


_registry: Optional[LayoutConstraintRegistry] = None


def get_layout_constraint_registry() -> LayoutConstraintRegistry:
    global _registry
    if _registry is None:
        _registry = LayoutConstraintRegistry()
    return _registry
