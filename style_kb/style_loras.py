# finetune後的參數檔案放這
"""Style ID → fine-tuned LoRA weights for fal.ai FLUX-general (`loras` param).

`path` must be a direct file URL (HuggingFace: .../resolve/main/xxx.safetensors),
not a repo homepage link. Leave `path` empty to skip LoRA for that style.
"""

# 2026-09-28 查證：MovingForward/designbridge-flux-lora 這個 repo 裡，除了 industrial
# 跟 luxury，其餘風格都沒有對應的 v5_flux1dev 檔案（modern/country/classic/japanese/
# american 完全沒上傳；nordic 只有舊一代的 v3 checkpoint，路徑/rank 都跟 v5 系列不同）。
# path 錯誤時 fal.ai 會回 422 file_download_error，renderer 再 fallback 到 Kontext
# depth-editing 路徑（用深度圖本身做 img2img），輸出看起來會像深度圖而非正常渲染。
# path 留空＝該風格先不套 LoRA、仍走正常 ControlNet 渲染（見 resolve_style_loras）。
STYLE_ID_TO_LORA: dict[str, dict] = {
    "modern": {"path": "", "scale": 1.0},  # 尚未上傳 v5 權重
    "country": {"path": "", "scale": 1.0},  # 尚未上傳 v5 權重
    "classic": {"path": "", "scale": 1.0},  # 尚未上傳 v5 權重
    "nordic": {"path": "", "scale": 1.0},  # 只有舊版 v3（nordic/designbridge_v3_nordic_000001500.safetensors），尚無 v5
    "industrial": {"path": "https://huggingface.co/MovingForward/designbridge-flux-lora/resolve/main/designbridge_v5_flux1dev_industrial.safetensors", "scale": 1.0},
    "japanese": {"path": "", "scale": 1.0},  # 尚未上傳 v5 權重
    "american": {"path": "", "scale": 1.0},  # 尚未上傳 v5 權重
    "luxury": {"path": "https://huggingface.co/MovingForward/designbridge-flux-lora/resolve/main/flux1dev/luxury/designbridge_v5_flux1dev_luxury/designbridge_v5_flux1dev_luxury.safetensors", "scale": 1.0},
}
