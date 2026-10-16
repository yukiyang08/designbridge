"""Verify occlusion-based camera candidate selection actually resolves occlusion.

A single fixed station point (the pre-unification behaviour) has no way to recover
when one piece of furniture happens to block another from that exact viewpoint.
These checks construct a layout where the base/default camera hides a short item
behind a closer one, and assert the candidate-scoring machinery (a) notices the
occlusion, (b) a nearby candidate resolves it, and (c) ``select_best_camera``
actually picks that better-scoring candidate rather than always the base one.
"""

from __future__ import annotations

from designbridge.layout.camera_projection import (
    CameraParams,
    build_tagged_scene,
    generate_candidates,
    score_camera,
    select_best_camera,
)

ROOM_W, ROOM_D, ROOM_H = 3.0, 3.0, 2.7
IMG = 512

# A 1.1m-tall cabinet standing close to the camera, directly in front of a short
# coffee table at the same x — from the base station point the cabinet should
# fully block the table behind it.
_OCCLUDER = {"id": "occ", "type": "cabinet", "x": 0.30, "y": 0.60, "w": 0.40, "h": 0.30}
_TARGET = {"id": "tgt", "type": "coffee_table", "x": 0.35, "y": 0.05, "w": 0.30, "h": 0.20}
_PLACEMENTS = [_OCCLUDER, _TARGET]


def _scored_candidates(base: CameraParams):
    tagged, id_to_type = build_tagged_scene(_PLACEMENTS, ROOM_W, ROOM_D, ROOM_H)
    furn_ids = [oid for oid, t in id_to_type.items() if not t.startswith("_")]
    by_id: dict[int, list] = {}
    for tri, oid in tagged:
        if oid in furn_ids:
            by_id.setdefault(oid, []).append((tri, oid))
    out = []
    for params in generate_candidates(base, 6):
        score, info = score_camera(params, base, ROOM_W, ROOM_D, IMG, IMG, tagged, furn_ids, by_id)
        out.append((params, score, info))
    return out


def test_base_candidate_is_occluded():
    """From the default station point, the table directly behind the cabinet is
    (almost) entirely hidden — this is the failure mode a single fixed camera
    cannot recover from."""
    base = CameraParams()
    candidates = _scored_candidates(base)
    base_score, base_info = candidates[0][1], candidates[0][2]
    target_ratio = base_info["ratios"].get(5, 0.0)
    assert target_ratio < 0.1, f"expected the table to be occluded, visible ratio={target_ratio:.2f}"
    print(f"[base] score={base_score:.3f}, table visible ratio={target_ratio:.2f}")


def test_a_candidate_resolves_the_occlusion():
    """At least one nearby candidate sees meaningfully more of the table than the
    base station point does. The candidate search is deliberately tight (small
    nudges, not a free roam to "pull back until nothing is occluded") — see
    generate_candidates' docstring — so this only expects a modest, not total,
    improvement."""
    base = CameraParams()
    candidates = _scored_candidates(base)
    base_score = candidates[0][1]
    better = [(p, s) for p, s, _ in candidates[1:] if s > base_score + 0.05]
    assert better, f"no candidate improved meaningfully on base score {base_score:.3f}"
    best_params, best_score = max(better, key=lambda t: t[1])
    print(f"[resolved] {best_params} -> score={best_score:.3f} (base={base_score:.3f})")


def test_select_best_camera_picks_the_better_candidate():
    """``select_best_camera`` must not just default to candidate 0 — it has to
    actually compare scores and return the best one."""
    base = CameraParams()
    candidates = _scored_candidates(base)
    base_score = candidates[0][1]
    chosen_params, info = select_best_camera(
        base, ROOM_W, ROOM_D, ROOM_H, IMG, IMG, _PLACEMENTS, candidates=6,
    )
    assert chosen_params != base, "selection should have moved off the occluded base candidate"
    assert info["score"] > base_score, (
        f"chosen candidate should score better than base, got {info['score']:.3f} vs {base_score:.3f}"
    )
    print(f"[selected] {chosen_params} -> score={info['score']:.3f} (base={base_score:.3f})")


def test_empty_layout_keeps_the_base_candidate():
    """With no furniture to occlude anything, there is nothing to score — the
    base camera should win (no gratuitous angle changes)."""
    base = CameraParams()
    chosen_params, info = select_best_camera(
        base, ROOM_W, ROOM_D, ROOM_H, IMG, IMG, [], candidates=6,
    )
    assert chosen_params == base
    assert info["score"] == 0.0
    print("[empty] base candidate kept when there is no furniture to score")


if __name__ == "__main__":
    test_base_candidate_is_occluded()
    test_a_candidate_resolves_the_occlusion()
    test_select_best_camera_picks_the_better_candidate()
    test_empty_layout_keeps_the_base_candidate()
    print("\nALL CAMERA-CANDIDATE-SCORING CHECKS PASSED ✅")
