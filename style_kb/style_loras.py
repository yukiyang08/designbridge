# finetune後的參數檔案放這
"""Style ID → fine-tuned LoRA weights for fal.ai FLUX-general (`loras` param).

`path` must be a direct file URL (HuggingFace: .../resolve/main/xxx.safetensors),
not a repo homepage link. Leave `path` empty to skip LoRA for that style.
"""

STYLE_ID_TO_LORA: dict[str, dict] = {
    "modern": {"path": "https://huggingface.co/MovingForward/designbridge-flux-lora/resolve/main/designbridge_v5_flux1dev_modern.safetensors", "scale": 1.0},
    "country": {"path": "https://huggingface.co/MovingForward/designbridge-flux-lora/resolve/main/designbridge_v5_flux1dev_country.safetensors", "scale": 1.0},
    "classic": {"path": "https://huggingface.co/MovingForward/designbridge-flux-lora/resolve/main/designbridge_v5_flux1dev_classic.safetensors", "scale": 1.0},
    "nordic": {"path": "https://huggingface.co/MovingForward/designbridge-flux-lora/resolve/main/designbridge_v5_flux1dev_nordic.safetensors", "scale": 1.0},
    "industrial": {"path": "https://huggingface.co/MovingForward/designbridge-flux-lora/resolve/main/designbridge_v5_flux1dev_industrial.safetensors", "scale": 1.0},
    "japanese": {"path": "https://huggingface.co/MovingForward/designbridge-flux-lora/resolve/main/designbridge_v5_flux1dev_japanese.safetensors", "scale": 1.0},
    "american": {"path": "https://huggingface.co/MovingForward/designbridge-flux-lora/resolve/main/designbridge_v5_flux1dev_american.safetensors", "scale": 1.0},
    "luxury": {"path": "https://huggingface.co/MovingForward/designbridge-flux-lora/resolve/main/designbridge_v5_flux1dev_luxury.safetensors", "scale": 1.0},
}
