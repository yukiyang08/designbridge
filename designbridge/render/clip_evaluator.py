# designbridge/clip_evaluator.py
"""CLIP-based evaluator: compute cosine similarity between a generated image and a text prompt."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import torch
import numpy as np
from PIL import Image

_MODEL_ID = "openai/clip-vit-base-patch32"
_model: Optional[Any] = None
_processor: Optional[Any] = None


def _load_model() -> tuple[Any, Any]:
    global _model, _processor
    if _model is None:
        from designbridge.core.model_lock import MODEL_LOAD_LOCK

        with MODEL_LOAD_LOCK:
            if _model is None:
                from transformers import CLIPModel, CLIPProcessor

                _processor = CLIPProcessor.from_pretrained(_MODEL_ID)
                _model = CLIPModel.from_pretrained(_MODEL_ID)
                _model.eval()
    return _model, _processor


def _translate_to_english(text: str) -> str:
    """Translate text to English using the project LLM. Returns original text on failure."""
    # Skip translation if already ASCII/English
    if all(ord(c) < 128 for c in text):
        return text
    try:
        from designbridge.render.llm import call_llm
        result = call_llm(
            f"Translate the following text to English. Output only the translated text, nothing else:\n{text}",
            max_tokens=400,
            temperature=0.0,
        )
        translated = result.strip()
        # Sanity check: result should be non-empty and not identical to input
        return translated if translated and translated != text else text
    except Exception:
        return text


def compute_clip_score(image_path: str, text_prompt: str) -> float:
    """Return cosine similarity [0, 1] between the image at image_path and text_prompt."""
    path = Path(image_path)
    if not path.exists():
        raise FileNotFoundError(f"Image not found: {image_path}")

    model, processor = _load_model()
    image = Image.open(path).convert("RGB")

    inputs = processor(text=[text_prompt], images=[image], return_tensors="pt", padding=True, truncation=True, max_length=77)
    with torch.no_grad():
        outputs = model(**inputs)
        image_emb = outputs.image_embeds  # (1, D)
        text_emb = outputs.text_embeds    # (1, D)

    image_emb = image_emb / image_emb.norm(dim=-1, keepdim=True)
    text_emb = text_emb / text_emb.norm(dim=-1, keepdim=True)
    score: float = (image_emb * text_emb).sum(dim=-1).item()

    # CLIP cosine similarity is typically in [-1, 1]; clamp to [0, 1] for readability
    return float(np.clip(score, 0.0, 1.0))


def evaluate(image_path: str, text_prompt: str) -> dict:
    """Run CLIP evaluation and return a result dict compatible with EvalFeedbackJSON."""
    clip_score = compute_clip_score(image_path, text_prompt)

    if clip_score >= 0.28:
        decision = "stop"
        feedback = f"生成圖像與指令高度吻合（CLIP score: {clip_score:.3f}）"
    elif clip_score >= 0.20:
        decision = "continue"
        feedback = f"生成圖像與指令部分吻合，建議優化（CLIP score: {clip_score:.3f}）"
    else:
        decision = "continue"
        feedback = f"生成圖像與指令相似度偏低，需重新生成（CLIP score: {clip_score:.3f}）"

    return {
        "scores": {"clip_similarity": clip_score},
        "weighted_score": clip_score,
        "decision": decision,
        "feedback": feedback,
        "issues_found": [] if clip_score >= 0.20 else ["圖像與文字指令相似度不足"],
        "suggestions": [] if clip_score >= 0.28 else ["嘗試調整 prompt 或生成參數以提升與指令的一致性"],
    }
