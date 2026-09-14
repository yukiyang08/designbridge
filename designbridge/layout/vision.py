"""Local vision preprocessing for DesignBridge.

Implements:
- Depth estimation via HuggingFace Transformers:
  - Depth Anything V2 (Small/Base/Large) - recommended, finer details
  - Intel MiDaS DPT (legacy fallback)
- Semantic segmentation (UPerNet) via HuggingFace Transformers

Outputs are saved to disk and returned as file paths, so they can be stored in LangGraph state.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class VisionArtifacts:
    """Paths to vision preprocessing outputs on disk."""

    depth_path: str | None = None
    segmentation_path: str | None = None
    segmentation_meta_path: str | None = None
    layout_json: dict | None = None  # depth_to_layout 萃取結果


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def _load_image(image_path: str, max_edge: int = 0) -> Any:
    """Open as RGB, optionally capping the long edge.

    Depth and segmentation artifacts are written at whatever size comes out of here, and
    every consumer downstream (plane fitting, hole filling, boundary extraction, the
    ControlNet condition) is O(pixels). Since both models resize to ~512 internally
    anyway, a 4000px phone photo costs a lot and returns nothing.
    """
    from PIL import Image

    image = Image.open(image_path).convert("RGB")
    if max_edge and max(image.size) > max_edge:
        scale = max_edge / max(image.size)
        target = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
        image = image.resize(target, Image.LANCZOS)
    return image


def _get_device() -> tuple[str, int]:
    """Return (device_str, device_index_for_pipeline)."""
    try:
        import torch

        if torch.cuda.is_available():
            return ("cuda", 0)
    except Exception:
        # If torch isn't installed yet, default to CPU.
        pass
    return ("cpu", -1)


@lru_cache(maxsize=1)
def _load_depth_model(model_name: str) -> Any:
    """Load Depth Anything V2 model and processor once (cached)."""
    from designbridge.core.model_lock import MODEL_LOAD_LOCK

    with MODEL_LOAD_LOCK:
        from transformers import AutoImageProcessor, AutoModelForDepthEstimation

        processor = AutoImageProcessor.from_pretrained(model_name, use_fast=False)
        model = AutoModelForDepthEstimation.from_pretrained(model_name)

        device, _ = _get_device()
        if device == "cuda":
            import torch

            model = model.to(torch.device("cuda"))
        model.eval()
        return processor, model


def run_depth_estimation(
    image_path: str, *, model_name: str, out_dir: Path, max_edge: int = 0
) -> tuple[str, Path]:
    """Run depth estimation and save a PNG depth map."""
    import numpy as np
    import torch
    import torch.nn.functional as F
    from PIL import Image

    processor, model = _load_depth_model(model_name)

    image = _load_image(image_path, max_edge)
    inputs = processor(images=image, return_tensors="pt")
    device, _ = _get_device()
    if device == "cuda":
        inputs = {k: v.to("cuda") for k, v in inputs.items()}

    with torch.no_grad():
        outputs = model(**inputs)
        predicted_depth = outputs.predicted_depth  # (B, H, W)

    # Upsample to original size
    depth = F.interpolate(
        predicted_depth.unsqueeze(1),
        size=image.size[::-1],
        mode="bicubic",
        align_corners=False,
    ).squeeze()

    depth_np = depth.cpu().numpy()
    # Normalize to 0..255 for visualization
    d_min, d_max = float(depth_np.min()), float(depth_np.max())
    if d_max - d_min < 1e-8:
        depth_norm = np.zeros_like(depth_np, dtype=np.uint8)
    else:
        depth_norm = ((depth_np - d_min) / (d_max - d_min) * 255.0).astype(np.uint8)

    ensure_dir(out_dir)
    depth_out = out_dir / "depth.png"
    Image.fromarray(depth_norm).save(depth_out)
    return str(depth_out), depth_out


@lru_cache(maxsize=1)
def _load_upernet(model_name: str) -> Any:
    """Load UPerNet segmentation model and processor once (cached)."""
    from designbridge.core.model_lock import MODEL_LOAD_LOCK

    with MODEL_LOAD_LOCK:
        from transformers import AutoImageProcessor, UperNetForSemanticSegmentation

        processor = AutoImageProcessor.from_pretrained(model_name, use_fast=False)
        model = UperNetForSemanticSegmentation.from_pretrained(model_name)

        device, _ = _get_device()
        if device == "cuda":
            import torch

            model = model.to(torch.device("cuda"))
        model.eval()
        return processor, model


def run_segmentation(
    image_path: str,
    *,
    model_name: str,
    out_dir: Path,
    max_edge: int = 0,
) -> tuple[str, str, Path]:
    """Run semantic segmentation and save label map PNG + a JSON metadata file."""
    import json

    import numpy as np
    import torch
    import torch.nn.functional as F
    from PIL import Image

    processor, model = _load_upernet(model_name)
    image = _load_image(image_path, max_edge)
    inputs = processor(images=image, return_tensors="pt")

    device, _ = _get_device()
    if device == "cuda":
        inputs = {k: v.to("cuda") for k, v in inputs.items()}

    with torch.no_grad():
        outputs = model(**inputs)
        logits = outputs.logits  # (B, C, h, w)

    # Upsample logits to original size
    up = F.interpolate(
        logits,
        size=image.size[::-1],
        mode="bilinear",
        align_corners=False,
    )
    seg = up.argmax(dim=1)[0].detach().cpu().numpy().astype(np.uint16)

    ensure_dir(out_dir)
    seg_out = out_dir / "segmentation.png"
    # Save as 16-bit PNG label map (class ids)
    Image.fromarray(seg, mode="I;16").save(seg_out)

    # Build simple metadata: id2label + present class ids
    id2label = getattr(model.config, "id2label", {}) or {}
    present_ids = sorted({int(x) for x in np.unique(seg).tolist()})
    present_labels = {str(i): id2label.get(i, "unknown") for i in present_ids}

    meta = {
        "model": model_name,
        "present_class_ids": present_ids,
        "present_labels": present_labels,
    }
    meta_out = out_dir / "segmentation_meta.json"
    meta_out.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    return str(seg_out), str(meta_out), meta_out


def _cache_key(image_path: str, parts: tuple[Any, ...]) -> str:
    """Content hash of the photo plus everything that changes the output."""
    import hashlib

    h = hashlib.sha256()
    with open(image_path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    h.update("|".join(str(p) for p in parts).encode("utf-8"))
    return h.hexdigest()[:16]


def run_visual_preprocessing(
    image_path: str,
    *,
    task_id: str,
    enable_depth: bool,
    enable_segmentation: bool,
    depth_model: str,
    segmentation_model: str,
    artifacts_root: Path,
    max_edge: int = 0,
    parallel: bool = False,
    use_cache: bool = False,
) -> VisionArtifacts:
    """Run local visual preprocessing and save outputs.

    Output directory is content-addressed rather than keyed on task_id, so re-running the
    same photo — the normal case while a user iterates on the prompt — reuses the
    artifacts instead of paying for inference again.

    Depth and segmentation are independent, so with `parallel` they run on two threads.
    Torch releases the GIL inside its ops; measured 35% faster end-to-end on CPU even
    though the two then share the same thread pool.
    """
    from designbridge.layout.depth_to_layout import (
        load_depth,
        slice_zones,
        detect_furniture_blobs,
        compute_spatial_metrics,
        build_layout_json,
    )
    from designbridge.core.timing import log_stage

    key = task_id
    if use_cache:
        try:
            key = _cache_key(
                image_path,
                (depth_model if enable_depth else "-",
                 segmentation_model if enable_segmentation else "-",
                 max_edge),
            )
        except OSError as e:
            print(f"⚠️  無法讀取照片做快取鍵（{e}），改用 task_id")

    out_dir = ensure_dir(artifacts_root / "vision" / key)
    depth_out = out_dir / "depth.png"
    seg_out = out_dir / "segmentation.png"
    seg_meta_out = out_dir / "segmentation_meta.json"
    layout_out = out_dir / "layout_from_depth.json"

    cached = (
        use_cache
        and (depth_out.is_file() or not enable_depth)
        and (seg_out.is_file() and seg_meta_out.is_file() or not enable_segmentation)
    )
    if cached:
        import json

        layout_json = None
        if layout_out.is_file():
            try:
                layout_json = json.loads(layout_out.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                layout_json = None
        print(f"[vision] 命中快取：{out_dir.name}")
        return VisionArtifacts(
            depth_path=str(depth_out) if enable_depth else None,
            segmentation_path=str(seg_out) if enable_segmentation else None,
            segmentation_meta_path=str(seg_meta_out) if enable_segmentation else None,
            layout_json=layout_json,
        )

    def _depth() -> str:
        with log_stage("visual_preprocessing.depth_estimation", task_id=task_id):
            path, _ = run_depth_estimation(
                image_path, model_name=depth_model, out_dir=out_dir, max_edge=max_edge
            )
        return path

    def _seg() -> tuple[str, str]:
        with log_stage("visual_preprocessing.segmentation", task_id=task_id):
            path, meta, _ = run_segmentation(
                image_path, model_name=segmentation_model, out_dir=out_dir, max_edge=max_edge
            )
        return path, meta

    depth_path: str | None = None
    seg_path: str | None = None
    seg_meta_path: str | None = None
    layout_json: dict | None = None

    if parallel and enable_depth and enable_segmentation:
        from concurrent.futures import ThreadPoolExecutor

        with log_stage("visual_preprocessing.parallel", task_id=task_id):
            with ThreadPoolExecutor(max_workers=2) as pool:
                depth_future = pool.submit(_depth)
                seg_future = pool.submit(_seg)
                depth_path = depth_future.result()
                seg_path, seg_meta_path = seg_future.result()
    else:
        if enable_depth:
            depth_path = _depth()
        if enable_segmentation:
            seg_path, seg_meta_path = _seg()

    if depth_path:
        try:
            with log_stage("visual_preprocessing.depth_to_layout", task_id=task_id):
                _d = load_depth(depth_path)
                _zones = slice_zones(_d)
                _blobs = detect_furniture_blobs(_d, _zones)
                _metrics = compute_spatial_metrics(_d, _zones)
                layout_json = build_layout_json(depth_path, _d, _zones, _blobs, _metrics)
        except Exception as e:
            # 不影響主流程，失敗只記 warning
            import warnings
            warnings.warn(f"depth_to_layout 萃取失敗，略過：{e}")

    if use_cache and layout_json is not None:
        import json

        try:
            layout_out.write_text(
                json.dumps(layout_json, ensure_ascii=False), encoding="utf-8"
            )
        except OSError:
            pass

    return VisionArtifacts(
        depth_path=depth_path,
        segmentation_path=seg_path,
        segmentation_meta_path=seg_meta_path,
        layout_json=layout_json,
    )