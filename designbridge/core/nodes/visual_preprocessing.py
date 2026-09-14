"""Visual Preprocessing graph node."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from designbridge.core.config import Config
from designbridge.core.state import DesignBridgeState
from designbridge.layout.vision import run_visual_preprocessing


def visual_preprocessing_local(state: DesignBridgeState) -> dict[str, Any]:
    """Local Visual Preprocessing: run depth + segmentation on the initial image (if provided)."""
    user = state.get("user_input") or {}
    image_path = user.get("initial_image")
    task_id = state.get("task_id") or "no_task_id"

    vision_features: dict[str, Any] = {"geometry_constraints": {}}

    if image_path:
        try:
            artifacts = run_visual_preprocessing(
                image_path,
                task_id=task_id,
                enable_depth=Config.ENABLE_DEPTH,
                enable_segmentation=Config.ENABLE_SEGMENTATION,
                depth_model=Config.DEPTH_MODEL,
                segmentation_model=Config.SEGMENTATION_MODEL,
                artifacts_root=Path(Config.ARTIFACTS_DIR),
                max_edge=Config.VISION_MAX_EDGE,
                parallel=Config.VISION_PARALLEL,
                use_cache=Config.VISION_CACHE,
            )
            if artifacts.depth_path:
                vision_features["depth"] = artifacts.depth_path
            if artifacts.segmentation_path:
                vision_features["segmentation"] = artifacts.segmentation_path
            if artifacts.segmentation_meta_path:
                vision_features["segmentation_meta"] = artifacts.segmentation_meta_path
        except Exception as e:
            print(f"⚠️  Visual preprocessing failed ({e}), falling back to empty vision_features")
            return {"vision_features": vision_features}

        result: dict[str, Any] = {"vision_features": vision_features}
        if artifacts.layout_json:
            result["layout_from_depth"] = artifacts.layout_json
        return result

    return {"vision_features": vision_features}
