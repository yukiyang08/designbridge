"""佈局檢查報告：把風水與動線問題整理成 LLM 看得懂的修正清單。"""

from __future__ import annotations

from typing import Any

from designbridge.layout.fengshui_audit import audit_circulation, audit_fengshui
from designbridge.layout.layout_items import FurnitureItem


def review_layout(
    items: list[FurnitureItem],
    structured_requirement: dict[str, Any],
    room_w: float,
    room_d: float,
) -> list[dict[str, Any]]:
    """只檢查使用者勾選的風水規則；沒有門就不檢查動線。"""
    space_info = structured_requirement.get("space_info") or {}
    doors = space_info.get("doors") or []
    windows = space_info.get("windows") or []
    rules = [t for t, on in (structured_requirement.get("special_constraints") or {}).items() if on]

    issues: list[dict[str, Any]] = []
    if rules:
        for r in audit_fengshui(items, doors, windows, rules=rules)["rules"]:
            if r["status"] == "fail":
                issues.append({
                    "kind": "風水", "severity": r["severity"], "message": r["label"],
                    "remedy": r["remedy"], "offenders": r["offenders"],
                })
    for i in audit_circulation(items, doors, room_w, room_d)["issues"]:
        issues.append({
            "kind": "動線", "severity": i["severity"], "message": i["message"],
            "remedy": i["remedy"], "offenders": i["offenders"],
        })
    return issues


def issue_penalty(issues: list[dict[str, Any]]) -> int:
    return sum(i["severity"] for i in issues)


def format_issues(issues: list[dict[str, Any]]) -> str:
    lines = []
    for i in issues:
        who = f"（涉及：{', '.join(i['offenders'])}）" if i["offenders"] else ""
        fix = f" → 建議：{i['remedy']}" if i["remedy"] else ""
        lines.append(f"- [{i['kind']}] {i['message']}{who}{fix}")
    return "\n".join(lines)
