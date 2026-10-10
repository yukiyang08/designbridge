# ControlNet 參數測試結果

測試腳本：[`scripts/controlnet_bench.py`](../scripts/controlnet_bench.py)
原始數據：[`images/controlnet_test/results.json`](images/controlnet_test/results.json)

## 測試設定

- 呼叫函式：`_render_flux_controlnet_depth_fal`（[render_backends.py:272](../designbridge/render/render_backends.py#L272)）
- depth 來源：`artifacts/layout/9d56e782-773e-414d-8021-7805cbd43be2_projected_depth.png`
- prompt：modern minimalist living room, gray fabric sofa, wooden coffee table, floor lamp, large window with soft daylight, indoor plant, photorealistic
- 固定參數：`conditioning_scale=0.7`、`guidance_scale=3.5`、`image_size=1024x1024`（正方形，無 LoRA、無 edge control 疊加）
- 變動參數：`num_inference_steps`、`control_end`（結構鎖定到去噪過程的百分比，1.0=全程鎖）
- 沒有固定 seed，每次呼叫用隨機種子 → 同組合多跑幾次才能排除「單張運氣不好」的雜訊

## 結果總覽

| 組合 | 耗時 | 畫質觀察 |
|---|---|---|
| steps=10, end=1.0 | 33.2s | 遠處窗景有雜訊絲狀偽影，燈具形狀變形 |
| steps=14, end=1.0 | 22.9s | **最差**——整片金色雜訊纏繞窗戶，家具幾何扭曲，植物位置怪異 |
| steps=20, end=1.0（目前預設） | 36.0s | 最乾淨——沙發、地板、窗簾都正常，細節最完整 |
| steps=10, end=0.7 | 29.1s | 乾淨，窗簾自然，沙發正常，僅遠景稍微單調 |
| steps=14, end=0.7 | 34.8s | 乾淨，人字拼地板、家具幾何都對，效果接近 20 步版本 |

## 圖片對照

### steps=10, control_end=1.0（33.2s）
![steps10_end1.0](images/controlnet_test/steps10_end1.0.png)

### steps=14, control_end=1.0（22.9s）—— 最差
![steps14_end1.0](images/controlnet_test/steps14_end1.0.png)

### steps=20, control_end=1.0（36.0s）—— 目前預設，畫質最好
![steps20_end1.0](images/controlnet_test/steps20_end1.0.png)

### steps=10, control_end=0.7（29.1s）
![steps10_end0.7](images/controlnet_test/steps10_end0.7.png)

### steps=14, control_end=0.7（34.8s）—— 推薦組合
![steps14_end0.7](images/controlnet_test/steps14_end0.7.png)

## 結論

`control_end=1.0`（全程鎖 ControlNet）在步數不足時，遠處窗戶等深度圖平坦區域容易出現雜訊絲狀偽影——模型沒機會把「沒資訊」的區域收斂成正常材質。`control_end=0.7`（後 30% 放手讓模型自由收斂）明顯改善這個問題，即使 steps 只有 10~14 也乾淨很多。

**推薦**：`steps=14, control_end=0.7`，畫質接近目前預設的 20 步版本，但穩定性更好（不會賭到雜訊）。想更快可以試 `steps=10, control_end=0.7`（29.1s，稍簡潔但無偽影）。

## 兩個但書

1. **耗時遠比正式流程快**：這次全部落在 23~36s，比 [PERFORMANCE_NOTES.md](PERFORMANCE_NOTES.md) 記錄的正式流程 125~154s 快很多。原因：這次測試只用單一 ControlNet、正方形尺寸、無 LoRA/edge 疊加，比正式流程輕量；也可能剛好遇到 fal.ai 排隊比較空。**不能直接當作「正式流程也會變這麼快」的證據**，需要用正式流程的完整參數（含 edge control、LoRA、實際輸出尺寸）重跑才準。
2. **沒固定 seed**：畫質差異可能部分來自運氣不好的隨機種子，不是純粹參數造成的。正式改預設值前，建議同組合多跑 2~3 張確認穩定性。

## 更新：第一輪測試方法有誤，已修正重測

第一輪測試把 `conditioning_scale` 固定寫成 `0.7`，但這是**投影出來的合成深度圖**（scene-graph 用箱型 bounding box 代表家具，不是真實照片），正式程式碼對這種深度圖有安全上限：

```
designbridge/core/nodes/renderer.py:538
depth_conditioning_scale = min(depth_conditioning_scale, Config.PROJECTED_DEPTH_MAX_CONDITIONING_SCALE)  # 預設 0.3
```

`0.7` 超過正式上限兩倍以上，導致：
- **沙發變箱子**——depth map 裡家具本來就是純箱型（見下方原始 depth map），conditioning_scale 太高逼模型死板貼著箱子輪廓畫
- **窗戶變雜訊**——depth map 上半部是平滑漸層（沒有紋理資訊），conditioning_scale 太高逼模型硬把這片「沒資訊」的區域解讀成畫面內容

### 原始 depth map
![depth_map](images/controlnet_test/source_depth_map.png)
（家具是純幾何箱型，牆面/窗戶是平滑漸層——這就是為什麼 conditioning_scale 太高會逼出箱型沙發跟雜訊窗戶）

### 修正後（conditioning_scale=0.3，符合正式上限）

| 組合 | 耗時 | 結果 |
|---|---|---|
| steps=10, end=1.0 | — | ❌ fal.ai 圖片上傳暫時性錯誤（跟參數無關） |
| steps=14, end=1.0 | 11.6s | ✅ 正常客廳、窗外有樹景、沙發正常布紋 |
| steps=20, end=1.0（目前預設） | 12.8s | ✅ 最完整——窗外城市天際線、沙發細節最豐富 |
| steps=10, end=0.7 | — | ❌ 同樣上傳暫時性錯誤 |
| steps=14, end=0.7 | 9.6s | ✅ 正常，木地板、扶手椅、窗外樹景自然 |

![cs0.3_steps14_end1.0](images/controlnet_test/cs0.3_steps14_end1.0.png)
![cs0.3_steps20_end1.0](images/controlnet_test/cs0.3_steps20_end1.0.png)
![cs0.3_steps14_end0.7](images/controlnet_test/cs0.3_steps14_end0.7.png)

**真正的結論**：用正確的 `conditioning_scale=0.3` 之後，三張全部正常，且耗時只要 9.6~12.8s——比第一輪測試（23~36s）跟正式流程記錄的 125~154s 都快很多（可能是這次 fal.ai 排隊比較空，見下方但書）。`steps=14` 跟目前預設的 `steps=20` 畫質差異不明顯，`control_end=0.7/1.0` 在這個 conditioning_scale 下也看不出明顯差別——真正決定畫質好壞的是 conditioning_scale 有沒有守住 `0.3` 這個上限，不是 steps 或 control_end。

## 待決定

1. 兩組因為 fal.ai 上傳服務暫時性錯誤失敗，要不要重跑補齊 steps=10 的數據
2. `DESIGNBRIDGE_FAL_CONTROLNET_STEPS` 從 20 調到 14 能省 ~1s，效益不大，可能不值得改
3. 這次測試耗時（9.6~12.8s）跟正式流程記錄的 125~154s 差距很大，建議用正式流程完整參數（多重 ControlNet、LoRA、實際輸出尺寸）重跑才能確認正式流程速度是否真的能大幅改善
