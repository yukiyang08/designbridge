#!/usr/bin/env python3
# app.py
"""DesignBridge Streamlit web interface for testing."""

import json
import tempfile
import time
from pathlib import Path
import streamlit as st
from designbridge import get_compiled_graph
from designbridge.style.style_apply import list_available_style_profiles


@st.cache_resource
def _get_cached_graph():
    return get_compiled_graph()



st.set_page_config(page_title="DesignBridge Test Interface", page_icon="🏠", layout="wide")

st.title("DesignBridge 測試介面")
st.markdown("輸入設計需求，查看 LangGraph 工作流的路由與執行結果")

# Sidebar for input
st.sidebar.header("輸入參數")

text_prompt = st.sidebar.text_area(
    "文字需求 (text_prompt)",
    value="客廳想要北歐風格，希望動線順暢",
    height=100,
    help="描述你的室內設計需求，例如風格、功能、布局等",
)

# 生成模型選擇
st.sidebar.markdown("**生成模型**")
model_type = st.sidebar.radio(
    "選擇生成模型",
    options=["flux"],
    format_func=lambda x: {
        "flux": "Flux.1 Schnell (快速，高品質)",
    }[x],
    help="Flux 生成速度快且品質高；之後接上微調模型可再加回選項",
    label_visibility="collapsed",
)
import os as _os
_os.environ["DESIGNBRIDGE_LOCAL_MODEL_TYPE"] = model_type


# 風格功能 
available_style_profiles = list_available_style_profiles()
style_options = ["自動（依文字需求判斷）"] + [
    f"{item['style_name']} ({item['style_id']})" for item in available_style_profiles
]

selected_style_option = st.sidebar.selectbox(
    "指定風格",
    options=style_options,
    index=0,
    help="若選擇特定風格，會限定向量搜尋（Supabase → 本地 ChromaDB）只在該風格內找參考圖來組裝生成 prompt。",
)

# 風格參考圖上傳欄位（移到指定風格下方）
st.sidebar.markdown("**風格參考圖（可選）**")
style_reference_file = st.sidebar.file_uploader(
    "上傳風格參考圖",
    type=["jpg", "jpeg", "png", "webp"],
    help="可上傳一張作為風格參考的圖片。",
    key="style_reference_image_unique"
)

# 圖片上傳：上傳檔案或留空表示從空布局開始
st.sidebar.markdown("**初始空間圖片（可選）**")
uploaded_file = st.sidebar.file_uploader(
    "上傳現況照片或參考圖",
    type=["jpg", "jpeg", "png", "webp"],
    help="支援 JPG、PNG、WebP。留空表示從空布局開始。",
    label_visibility="collapsed",
)

# 上傳後顯示預覽與路徑
initial_image = ""
if uploaded_file is not None:
    # 暫存到 temp，取得路徑供工作流使用
    suffix = Path(uploaded_file.name).suffix or ".png"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(uploaded_file.getvalue())
        initial_image = tmp.name
    st.sidebar.image(uploaded_file, caption="已上傳預覽", width="stretch")
    st.sidebar.caption(f"路徑：`{initial_image}`")
else:
    st.sidebar.caption("未上傳圖片：將從空布局開始")
    with st.sidebar.expander("進階：手動輸入圖片路徑"):
        manual_path = st.text_input(
            "圖片路徑",
            value="",
            help="若已有本機路徑可在此輸入",
            label_visibility="collapsed",
        )
        if manual_path and manual_path.strip():
            initial_image = manual_path.strip()


run_button = st.sidebar.button("▶️ 生成設計", type="primary", width="stretch")

# Example prompts
st.sidebar.markdown("---")
st.sidebar.markdown("**💡 範例提示詞**")
example_prompts = {
    "布局優化": "客廳動線不順暢，希望重新規劃布局",
    "風格變更": "想要改成現代簡約風格",
    "局部微調": "只想調整沙發位置和顏色",
    "布局+風格": "北歐風格，開放式空間，動線順暢",
}
for name, prompt in example_prompts.items():
    if st.sidebar.button(f"📌 {name}", key=name, width="stretch"):
        st.session_state["example_prompt"] = prompt
        st.rerun()

if "example_prompt" in st.session_state:
    text_prompt = st.session_state["example_prompt"]
    del st.session_state["example_prompt"]


# 風格參考圖處理（應放在 sidebar 輸入區段）
style_reference_image = ""
if style_reference_file is not None:
    suffix = Path(style_reference_file.name).suffix or ".png"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(style_reference_file.getvalue())
        style_reference_image = tmp.name
    st.sidebar.image(style_reference_file, caption="風格參考圖預覽", width="stretch")
    st.sidebar.caption(f"路徑：`{style_reference_image}`")
else:
    st.sidebar.caption("未上傳風格參考圖")

# Main content: 工作流圖示（Mermaid，可收合）
with st.expander("Workflow Diagram", expanded=True):
    try:
        _compiled = _get_cached_graph()
        _drawable = _compiled.get_graph()
        _mermaid_str = _drawable.draw_mermaid()
        # Cache the PNG bytes in session_state so we only fetch once per session
        if "workflow_png" not in st.session_state:
            try:
                st.session_state["workflow_png"] = _drawable.draw_mermaid_png()
            except Exception:
                st.session_state["workflow_png"] = None
        if st.session_state["workflow_png"]:
            st.image(st.session_state["workflow_png"], use_container_width=True)
        else:
            st.caption("圖示以 Mermaid 原始碼顯示於下方。")
        with st.expander("🔍 檢視 / 複製 Mermaid 原始碼"):
            st.code(_mermaid_str, language="mermaid")
            st.caption("可複製到 [mermaid.live](https://mermaid.live) 編輯或匯出。")
    except Exception as e:
        st.warning(f"工作流圖無法載入：{e}")

st.markdown("---")

if run_button:
    # 只要三者任一有值即可
    has_text = bool(text_prompt.strip())
    has_style = selected_style_option != "自動（依文字需求判斷）"
    has_image = bool(initial_image)
    has_style_reference = bool(style_reference_image)
    if not (has_text or has_style or has_image):
        st.error("❌ 請至少輸入文字需求、選擇風格，或上傳圖片（任一即可）")
    else:
        with st.spinner("🔄 執行 DesignBridge 工作流..."):
            # Build initial state
            user_input = {}
            if has_text:
                user_input["text_prompt"] = text_prompt
            if has_style:
                selected_style_id = selected_style_option.rsplit("(", 1)[-1].rstrip(")")
                user_input["style_profile_id"] = selected_style_id
            if has_image:
                user_input["initial_image"] = initial_image
            if has_style_reference:
                user_input["style_reference_image"] = style_reference_image

            initial_state = {"user_input": user_input}

            # Invoke graph
            try:
                compiled = _get_cached_graph()
                t0 = time.perf_counter()
                result = compiled.invoke(initial_state)
                elapsed = time.perf_counter() - t0

                # Display results
                st.success(f"工作流執行完成！（耗時 {elapsed:.2f} 秒）")
                # Key results in columns
                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    st.metric("Task ID", result.get("task_id", "N/A")[:8] + "...")
                with col2:
                    st.metric("Iteration", result.get("iteration", 0))
                with col3:
                    routing = result.get("routing_decision", "N/A")
                    emoji_map = {
                        "layout": "📐",
                        "style": "🎨",
                        "design_adjuster": "🔧",
                        "layout_and_style": "📐🎨",
                    }
                    st.metric("路由決策", f"{emoji_map.get(routing, '❓')} {routing}")
                with col4:
                    st.metric("執行秒數", f"{elapsed:.2f} s")

                # Generated image (Renderer output)
                st.subheader("🖼️ 生成圖")
                gen_path = result.get("generated_image")
                render_result = result.get("render_result") or {}
                if gen_path and Path(gen_path).exists():
                    import base64
                    with open(gen_path, "rb") as _f:
                        _b64 = base64.b64encode(_f.read()).decode()
                    st.markdown(
                        f'<img src="data:image/png;base64,{_b64}" '
                        f'style="width:480px; max-width:100%; border-radius:6px;">',
                        unsafe_allow_html=True,
                    )
                    st.caption("Renderer 輸出")
                    st.caption(f"路徑：`{gen_path}`")
                    gp = render_result.get("generation_params") or {}
                    backend = gp.get("backend", "")
                    if backend == "flux":
                        st.success(f"Flux　`{gp.get('model','')}`")
                    elif backend == "hf_inference":
                        st.success(f"HF Inference API　`{gp.get('model','')}`")
                    elif backend == "imagen":
                        st.caption("Imagen API")
                    elif gp.get("fallback") == "placeholder":
                        st.info("⚠️ 生成失敗，顯示佔位圖")
                elif gen_path:
                    st.warning(f"生成圖路徑不存在：`{gen_path}`")
                else:
                    st.info("無生成圖")

                # Structured requirement
                st.subheader("📋 結構化需求（Requirement JSON）")
                req = result.get("structured_requirement", {})
                if req:
                    # Display key fields
                    col1, col2, col3 = st.columns(3)
                    meta = req.get("meta", {})
                    style_prefs = req.get("style_preferences", {})

                    with col1:
                        st.write("**房間類型**")
                        st.code(meta.get("room_type", "N/A"))
                    with col2:
                        st.write("**設計目標**")
                        st.code(meta.get("design_goal", "N/A"))
                    with col3:
                        st.write("**主要風格**")
                        st.code(style_prefs.get("primary_style", "N/A"))

                    # Priority weights
                    weights = req.get("priority_weights", {})
                    if weights:
                        st.write("**評估權重**")
                        wcol1, wcol2, wcol3 = st.columns(3)
                        with wcol1:
                            st.metric("佈局合理性", f"{weights.get('layout_rationality', 0):.1f}")
                        with wcol2:
                            st.metric("風格一致性", f"{weights.get('style_consistency', 0):.1f}")
                        with wcol3:
                            st.metric("創新程度", f"{weights.get('novelty', 0):.1f}")

                    # Constraints summary
                    constraints = req.get("layout_constraints", {})
                    must_add = constraints.get("must_add", [])
                    must_keep = constraints.get("must_keep", [])
                    if must_add or must_keep:
                        st.write("**佈局約束**")
                        if must_keep:
                            st.write(f"必留家具：{', '.join(must_keep)}")
                        if must_add:
                            st.write(f"必加家具：{', '.join(must_add)}")

                    with st.expander("🔍 完整 Requirement JSON"):
                        st.json(req)
                else:
                    st.info("無結構化需求")

                # Vision features
                st.subheader("👁️ 視覺前處理結果")
                vision = result.get("vision_features", {})
                if vision:
                    col1, col2 = st.columns(2)
                    with col1:
                        st.write("**Segmentation**")
                        seg_path = vision.get("segmentation")
                        if isinstance(seg_path, str) and Path(seg_path).exists():
                            try:
                                import numpy as np
                                from PIL import Image as _PIL
                                _arr = np.array(_PIL.open(seg_path), dtype=np.float32)
                                _mn, _mx = _arr.min(), _arr.max()
                                _u8 = ((_arr - _mn) / (_mx - _mn + 1e-8) * 255).astype(np.uint8)
                                st.image(_u8, caption="Segmentation", use_container_width=True)
                            except Exception as _e:
                                st.warning(f"載入失敗：{_e}")
                        else:
                            st.info("未產出（需上傳圖片）")
                    with col2:
                        st.write("**Depth Map**")
                        depth_path = vision.get("depth")
                        if isinstance(depth_path, str) and Path(depth_path).exists():
                            try:
                                st.image(depth_path, caption="Depth Map", use_container_width=True)
                            except Exception as _e:
                                st.warning(f"載入失敗：{_e}")
                        else:
                            st.info("未產出（需上傳圖片）")
                    with st.expander("🔍 完整 vision_features JSON"):
                        st.json(vision)
                else:
                    st.info("無視覺特徵")

                # Intermediate outputs
                st.subheader("🔄 中間輸出")
                intermediate = result.get("intermediate_outputs", {})
                if intermediate:
                    st.json(intermediate)
                else:
                    st.info("無中間輸出")

                st.subheader("套用風格參數")
                style_params = result.get("style_params", {})
                if style_params:
                    scol1, scol2, scol3 = st.columns(3)
                    with scol1:
                        st.write("**風格檔**")
                        st.code(style_params.get("style_profile_id", "N/A"))
                    with scol2:
                        st.write("**風格名稱**")
                        st.code(style_params.get("style_profile_name", "N/A"))
                    with scol3:
                        st.write("**風格強度**")
                        st.code(str(style_params.get("style_strength", "N/A")))
                    with st.expander("🔍 完整 style_params"):
                        st.json(style_params)
                else:
                    st.info("未載入聚合風格檔，將依文字需求與預設 prompt 生成。")

                # Full state
                with st.expander("🗂️ 完整 State JSON"):
                    st.json(result)

            except Exception as e:
                st.error(f"❌ 執行失敗：{e}")
                st.exception(e)
else:
    # Show placeholder
    st.info("👈 請在左側輸入參數，然後點擊「執行工作流」按鈕")

    # Display workflow diagram
    st.subheader("DesignBridge 工作流")
    st.markdown(
        """
```
START
  ↓
Requirement Analyzer (需求解析)
  ↓
Visual Preprocessing (視覺前處理, stub)
  ↓
Design Director (任務路由)
  ↓
  ├─→ Layout Agent (佈局代理人)
  ├─→ Style Agent (風格代理人)
  ├─→ Design Adjuster (微調代理人)
  └─→ Layout + Style Agent (協作)
  ↓
END
```
    """
    )

    st.markdown("---")
    st.markdown("**路由邏輯**")
    st.markdown(
        """
- **Design Adjuster**：語意判斷為局部微調，或關鍵字「局部」、「微調」
- **Layout**：關鍵字「動線」、「布局」、「layout」
- **Style**：關鍵字「風格」、「style」、「色彩」
- **Layout + Style**：同時包含布局與風格，或預設值
    """
    )

# Footer
st.sidebar.markdown("---")
st.sidebar.markdown("**DesignBridge v0.1**")
st.sidebar.markdown("使用 LangGraph 建構的多代理室內設計工作流")
