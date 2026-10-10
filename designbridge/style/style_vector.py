"""Style vector store query interface.

封裝 ChromaDB 查詢邏輯，供 style_apply.py 呼叫。
向量庫由 style_kb/build_vector_store.py 離線建立。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

VECTOR_STORE_DIR = Path(__file__).resolve().parent.parent.parent / "style_kb" / "vector_store"
COLLECTION_NAME = "style_images"
EMBEDDING_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"

# 快取（避免每次查詢重新載入模型）
_client = None
_collection = None


@dataclass
class StyleImageResult:
    """單筆向量搜尋結果。"""
    doc_id: str
    style_id: str
    style_name: str
    image_path: str
    json_path: str
    tags: list[str]
    primary_color: str
    secondary_color: str
    accent_color: str
    color_temp: int
    ip_adapter_weight: float
    controlnet: str
    positive_prompt: str
    negative_prompt: str
    similarity_score: float


def is_vector_store_ready() -> bool:
    """確認向量庫是否已建立且有資料。"""
    if not VECTOR_STORE_DIR.exists():
        return False
    try:
        col = _get_collection()
        return col.count() > 0
    except Exception:
        return False


def warmup_vector_collection() -> None:
    """Preload Chroma client and SentenceTransformer embedder if the store exists and is non-empty."""
    if not is_vector_store_ready():
        return
    _get_collection()


def _get_collection():
    """取得（或初始化）ChromaDB collection，使用模組層級快取。"""
    global _client, _collection

    if _collection is not None:
        return _collection

    from designbridge.core.model_lock import MODEL_LOAD_LOCK

    with MODEL_LOAD_LOCK:
        if _collection is not None:
            return _collection

        import chromadb
        from chromadb.utils import embedding_functions

        ef = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name=EMBEDDING_MODEL
        )
        _client = chromadb.PersistentClient(path=str(VECTOR_STORE_DIR))
        _collection = _client.get_collection(
            name=COLLECTION_NAME,
            embedding_function=ef,
        )
        return _collection


def _parse_result(doc_id: str, metadata: dict, distance: float) -> StyleImageResult:
    """把 ChromaDB 查詢結果轉成 StyleImageResult。"""
    # ChromaDB cosine distance → similarity score (0~1, 越高越相似)
    similarity = max(0.0, 1.0 - distance)
    return StyleImageResult(
        doc_id=doc_id,
        style_id=metadata.get("style_id", ""),
        style_name=metadata.get("style_name", ""),
        image_path=metadata.get("image_path", ""),
        json_path=metadata.get("json_path", ""),
        tags=metadata.get("tags", "").split(","),
        primary_color=metadata.get("primary_color", ""),
        secondary_color=metadata.get("secondary_color", ""),
        accent_color=metadata.get("accent_color", ""),
        color_temp=int(metadata.get("color_temp", 0)),
        ip_adapter_weight=float(metadata.get("ip_adapter_weight", 0.85)),
        controlnet=metadata.get("controlnet", "depth"),
        positive_prompt=metadata.get("positive_prompt", ""),
        negative_prompt=metadata.get("negative_prompt", ""),
        similarity_score=round(similarity, 4),
    )


def query_style_images(
    text_query: str,
    style_id: str | None = None,
    top_k: int = 3,
) -> list[StyleImageResult]:
    """
    語義搜尋最相關的風格參考圖片。

    Args:
        text_query:  使用者輸入的文字描述（可中英文混合）
        style_id:    限定搜尋的風格 ID（None = 不限風格）
        top_k:       返回幾筆結果

    Returns:
        依相似度由高到低排列的 StyleImageResult 列表
    """
    if not text_query:
        text_query = style_id or "interior design"

    try:
        collection = _get_collection()
    except Exception as e:
        print(f"⚠️  無法連接向量庫：{e}")
        return []

    where = {"style_id": style_id} if style_id else None

    try:
        results = collection.query(
            query_texts=[text_query],
            n_results=min(top_k, collection.count()),
            where=where,
            include=["metadatas", "distances"],
        )
    except Exception as e:
        print(f"⚠️  向量查詢失敗：{e}")
        return []

    ids = results["ids"][0]
    metadatas = results["metadatas"][0]
    distances = results["distances"][0]

    return [
        _parse_result(doc_id, meta, dist)
        for doc_id, meta, dist in zip(ids, metadatas, distances)
    ]


def blend_style_params(results: list[StyleImageResult]) -> dict[str, Any]:
    """
    依相似度分數加權，將多筆結果組合成 StyleParamsJSON。

    - prompt：直接用 top-1（最相關）
    - 顏色：加權平均 top-k（hex → RGB → 加權平均 → hex）
    - color_temp：加權平均
    - ip_adapter_weight：加權平均
    - image_paths：全部返回（供 IP-Adapter 使用）
    """
    if not results:
        return {}

    top = results[0]

    # 加權計算顏色（hex → RGB）
    total_weight = sum(r.similarity_score for r in results)

    def weighted_avg_hex(color_attr: str) -> str:
        r_sum = g_sum = b_sum = 0.0
        for res in results:
            hex_color = getattr(res, color_attr, "#808080").lstrip("#")
            if len(hex_color) != 6:
                hex_color = "808080"
            try:
                rv = int(hex_color[0:2], 16)
                gv = int(hex_color[2:4], 16)
                bv = int(hex_color[4:6], 16)
                w = res.similarity_score / total_weight if total_weight > 0 else 1 / len(results)
                r_sum += rv * w
                g_sum += gv * w
                b_sum += bv * w
            except ValueError:
                pass
        return "#{:02X}{:02X}{:02X}".format(int(r_sum), int(g_sum), int(b_sum))

    def weighted_avg_float(attr: str) -> float:
        if total_weight == 0:
            return getattr(results[0], attr, 0.0)
        return sum(
            getattr(r, attr, 0.0) * r.similarity_score / total_weight
            for r in results
        )

    return {
        "style_profile_id": top.style_id,
        "style_profile_name": top.style_name,
        "style_prompt": top.positive_prompt,
        "negative_prompt": top.negative_prompt,
        "style_strength": round(weighted_avg_float("ip_adapter_weight"), 2),
        "color_guidance": {
            "primary_color": weighted_avg_hex("primary_color"),
            "secondary_color": weighted_avg_hex("secondary_color"),
            "accent_color": weighted_avg_hex("accent_color"),
            "avg_color_temp_k": int(weighted_avg_float("color_temp")),
        },
        "controlnet_type": top.controlnet,
        "reference_images": [
            r.image_path for r in results if r.image_path != "N/A"
        ],
        "matched_tags": list({tag for r in results for tag in r.tags if tag}),
        "top_similarity": top.similarity_score,
        "source": "vector_store",
    }
