<script setup>
import { computed, ref, reactive, watch } from 'vue'
import { apiUrl } from '@/config/api'
import { useFurnitureSelection } from '@/composables/useFurnitureSelection'
import PanoramaViewer from './PanoramaViewer.vue'
import PointCloudViewer from './PointCloudViewer.vue'

const refExpanded = ref(true)
const rawExpanded = ref(false)
const {
  selectedFurniture,
  selectedCount: furnitureSelectedCount,
  toggle: toggleFurnitureFavorite,
  isSelected: isFurnitureFavorited,
} = useFurnitureSelection()

function candidateToFavoriteItem(item, c) {
  return {
    id: c.id || c.purchase_url || `${item.detected_name}__${c.name}`,
    name: c.name,
    category: item.category,
    price: c.price,
    currency: 'TWD',
    url: c.purchase_url,
    image_url: c.product_image_url,
  }
}

const props = defineProps({
  result:  { type: Object,  default: null },
  loading: { type: Boolean, default: false },
})

const emit = defineEmits(['refine', 'quotation-loaded'])

// 3D 全景圖：按需生成（耗時約 30-60 秒，不放進自動流程）
const show3d = ref(false)
const panoLoading = ref(false)
const panoUrl = ref(null)
const panoError = ref(null)

// 切換到新結果時重置全景狀態
watch(() => props.result?.task_id, () => {
  panoLoading.value = false
  panoUrl.value = null
  panoError.value = null
  show3d.value = false
})

async function generatePanorama() {
  const result = props.result
  if (!result?.task_id || !result?.generated_image_path) return

  panoLoading.value = true
  panoError.value = null

  try {
    const res = await fetch(apiUrl('/api/generate-panorama'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        task_id: result.task_id,
        image_path: result.generated_image_path,
        depth_path: result.vision_features?.depth || null,
        prompt: result.structured_requirement?.meta?.design_goal || '',
      }),
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({}))
      throw new Error(err.detail || `HTTP ${res.status}`)
    }
    const data = await res.json()
    panoUrl.value = data.room_panorama_url
    show3d.value = true
  } catch (e) {
    panoError.value = e.message
  } finally {
    panoLoading.value = false
  }
}

// 家具估價／報價推薦改成使用者按按鈕才觸發（避免每次生圖都額外等 30-40 秒）
const quotationLoading = ref(false)
const quotationError = ref('')

async function fetchQuotation() {
  if (!props.result?.generated_image_path) return
  quotationLoading.value = true
  quotationError.value = ''
  try {
    const res = await fetch(apiUrl('/api/quotation'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        image_path: props.result.generated_image_path,
        structured_requirement: props.result.structured_requirement || null,
        selected_furniture: selectedFurniture.value,
      }),
    })
    if (!res.ok) throw new Error(`${res.status}`)
    const data = await res.json()
    emit('quotation-loaded', data)
  } catch (e) {
    quotationError.value = e.message || '估價失敗，請稍後再試'
  } finally {
    quotationLoading.value = false
  }
}

// 估價候選選擇狀態（每件家具當前選中的候選 index）
const selectedCandidates = reactive({})

watch(
  () => props.result?.quotation_result?.furniture_list,
  (list) => {
    if (list) {
      list.forEach((_, idx) => {
        selectedCandidates[idx] = 0
      })
    }
  },
  { immediate: true },
)

// 動態計算總預算（依各品項已選候選）
const computedTotal = computed(() => {
  const list = props.result?.quotation_result?.furniture_list
  if (!list) return 0
  return list.reduce((sum, item, idx) => {
    const ci = selectedCandidates[idx] ?? 0
    const c = item.candidates?.[ci]
    return sum + (c?.price ?? 0)
  }, 0)
})

const spatialLevelColor = computed(() => {
  const level = props.result?.structured_requirement?.spatial_change_level
  if (level === 'major') return 'badge-red'
  if (level === 'minor') return 'badge-orange'
  return 'badge-teal'
})

const styleReferenceImageUrl = computed(() => {
  const result = props.result
  if (!result) return ''

  const fromStyleParams = result.style_params?.reference_image_url
  if (typeof fromStyleParams === 'string' && fromStyleParams.trim()) {
    return fromStyleParams
  }

  const fromControlNet = result.render_result?.controlnet_inputs?.style_reference_image
  if (typeof fromControlNet !== 'string' || !fromControlNet.trim()) {
    return ''
  }

  const normalized = fromControlNet.replace(/\\/g, '/')
  if (normalized.startsWith('http://') || normalized.startsWith('https://')) {
    return normalized
  }
  if (normalized.startsWith('artifacts/')) {
    return `http://localhost:8000/${normalized}`
  }
  return ''
})
</script>

<template>
  <div class="panel">

    <!-- 空狀態 -->
    <div v-if="!result && !loading" class="placeholder">
      <div class="placeholder-inner">
        <div class="placeholder-icon">✦</div>
        <h2>描述你的理想空間</h2>
        <p>在左側輸入需求，AI 會理解你的設計偏好並生成設計方案</p>
        
      </div>
    </div>

    <!-- 載入中 -->
    <div v-if="loading" class="loading-state">
      <div class="loading-ring">
        <div class="loading-spinner"></div>
        <div class="loading-mark">✦</div>
      </div>
      <p class="loading-title">AI 生成中</p>
      <p class="loading-sub">工作流執行中，通常需要 30–60 秒</p>
    </div>

    <!-- 結果 -->
    <div v-if="result" class="result">

      <!-- Header -->
      <div class="result-header">
        <div class="result-title-group">
          <h2>生成結果</h2>
          <div class="badges">
            <span class="badge green">✓ 成功</span>
            <span class="badge gray">{{ result.elapsed_time }}</span>
            <span class="badge purple">{{ result.routing_decision }}</span>
            <span
              v-if="result.structured_requirement?.spatial_change_level"
              :class="['badge', spatialLevelColor]"
            >depth: {{ result.structured_requirement.spatial_change_level }}</span>
          </div>
        </div>
      </div>

      <!-- 生成圖 + 風格參考圖 -->
      <div
        v-if="result.generated_image_path || styleReferenceImageUrl"
        :class="['image-row', { 'image-row--ref-collapsed': !refExpanded }]"
      >

        <!-- 生成圖 -->
        <div v-if="result.generated_image_path" class="img-slot img-hero">
          <img
            v-if="result.generated_image_url"
            :src="result.generated_image_url"
            alt="AI 生成設計圖"
            class="img-cover"
          />
          <div class="img-label-bottom">
            <span class="img-path">{{ result.generated_image_path }}</span>
          </div>
        </div>

        <!-- 風格參考圖 -->
        <div
          v-if="styleReferenceImageUrl"
          :class="['img-slot', 'img-ref', { 'img-ref--collapsed': !refExpanded }]"
        >
          <template v-if="refExpanded">
            <img
              :src="styleReferenceImageUrl"
              alt="風格參考圖"
              class="img-cover"
            />
            <div class="img-label-top">
              <span class="img-label-text">風格參考圖</span>
              <button class="collapse-btn" @click="refExpanded = false" title="收合">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="15 18 9 12 15 6"/></svg>
              </button>
            </div>
          </template>
          <div v-else class="collapsed-strip" @click="refExpanded = true" title="展開風格參考圖">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="9 18 15 12 9 6"/></svg>
            <span class="strip-text">風格參考圖</span>
          </div>
        </div>

      </div>

      <!-- 3D全景模擬（按需生成） -->
      <div v-if="result.generated_image_path && result.task_id" class="card room3d-card">
        <div class="room3d-header">
          <h3 class="card-title">
            3D全景模擬
            <span class="badge-3d">互動式</span>
          </h3>
          <!-- 未生成：顯示生成按鈕 -->
          <button v-if="!panoUrl && !panoLoading" class="btn-view3d btn-pano" @click="generatePanorama">
            ✦ 生成 3D全景模擬
          </button>
          <!-- 生成中 -->
          <span v-else-if="panoLoading" class="pano-status">
            <span class="pano-dot"></span> 生成中，約 30–60 秒…
          </span>
          <!-- 已生成：收合 / 展開 -->
          <button v-else-if="panoUrl" class="btn-view3d" @click="show3d = !show3d">
            {{ show3d ? '收合' : '查看 3D全景模擬' }}
          </button>
        </div>

        <!-- 錯誤提示 -->
        <div v-if="panoError" class="pano-error">⚠ {{ panoError }}</div>

        <!-- 全景 Viewer -->
        <PanoramaViewer v-if="panoUrl && show3d" :image-url="panoUrl" />
      </div>

      <!-- 3D 點雲檢視器 -->
      <div v-if="result.depth_cloud_url" class="card splat-card">
        <h3 class="card-title">
          3D 點雲
          <span class="badge-3d">互動式</span>
        </h3>
        <PointCloudViewer :ply-url="result.depth_cloud_url" />
      </div>

      <!-- 結構化需求 -->
      <div v-if="result.structured_requirement" class="card">
        <h3 class="card-title">結構化需求</h3>
        <div class="req-grid">
          <div class="req-item" v-if="result.structured_requirement.meta?.room_type">
            <span class="req-label">房間類型</span>
            <span class="req-value">{{ result.structured_requirement.meta.room_type }}</span>
          </div>
          <div class="req-item" v-if="result.structured_requirement.meta?.design_goal">
            <span class="req-label">設計目標</span>
            <span class="req-value">{{ result.structured_requirement.meta.design_goal }}</span>
          </div>
          <div class="req-item" v-if="result.structured_requirement.style_preferences?.primary_style">
            <span class="req-label">主要風格</span>
            <span class="req-value">{{ result.structured_requirement.style_preferences.primary_style }}</span>
          </div>
          <div class="req-item" v-if="result.structured_requirement.edit_scope?.scope_value !== undefined">
            <span class="req-label">改動幅度</span>
            <span class="req-value">{{ Number(result.structured_requirement.edit_scope.scope_value).toFixed(1) }}</span>
          </div>
        </div>

        <!-- testing 用：完整結構化需求 + 這次生成實際用的參數/prompt -->
        <button class="raw-toggle" @click="rawExpanded = !rawExpanded">
          {{ rawExpanded ? '收合完整 JSON ▲' : '顯示完整 JSON（含 prompt / 生成參數） ▼' }}
        </button>
        <div v-if="rawExpanded" class="raw-json-group">
          <div>
            <div class="raw-json-label">structured_requirement</div>
            <pre class="raw-json">{{ JSON.stringify(result.structured_requirement, null, 2) }}</pre>
          </div>
          <div v-if="result.render_result?.generation_params">
            <div class="raw-json-label">generation_params</div>
            <pre class="raw-json">{{ JSON.stringify(result.render_result.generation_params, null, 2) }}</pre>
          </div>
        </div>
      </div>

      <!-- 風格參數 -->
      <div v-if="result.style_params" class="card card-style">
        <h3 class="card-title">套用風格參數</h3>
        <div class="style-meta">
          <span class="style-badge">{{ result.style_params.style_profile_id || result.style_params.style_id }}</span>
          <span class="style-name">{{ result.style_params.style_profile_name || result.style_params.style_name }}</span>
          <span v-if="result.style_params.style_strength !== undefined" class="style-strength">
            強度 {{ result.style_params.style_strength }}
          </span>
        </div>
        <div v-if="result.style_params.visual_elements?.colors" class="color-swatches">
          <div v-for="(hex, role) in result.style_params.visual_elements.colors" :key="role" class="swatch-item">
            <div class="swatch" :style="{ background: hex }"></div>
            <span class="swatch-label">{{ role }}</span>
            <span class="swatch-hex">{{ hex }}</span>
          </div>
        </div>
        <div v-if="result.style_params.semantic_tags?.length" class="style-tags">
          <span v-for="tag in result.style_params.semantic_tags" :key="tag" class="tag">{{ tag }}</span>
        </div>
      </div>
      <div v-else-if="result.render_result?.generation_params?.gemini_style_description" class="card card-style">
        <h3 class="card-title">套用風格參數</h3>
        <div class="style-meta">
          <span class="style-badge">使用者上傳</span>
          <span class="style-name">Gemini 視覺分析</span>
        </div>
        <p class="gemini-desc">{{ result.render_result.generation_params.gemini_style_description }}</p>
      </div>
      <div v-else class="card card-muted">
        <h3 class="card-title">套用風格參數</h3>
        <p class="muted-text">未載入聚合風格檔，將依文字需求與預設 prompt 生成。</p>
      </div>


      <!-- 家具估價（按鈕觸發，不佔用生圖等待時間） -->
      <div v-if="result.generated_image_path" class="result-section quotation-section">
        <div class="quotation-header-row">
          <h3 class="quotation-title">
            家具估價
            <span class="ikea-badge">IKEA 台灣</span>
          </h3>
          <div class="quotation-actions">
            <RouterLink to="/furniture" class="furniture-pick-link">
              前往家具查詢
              <span v-if="furnitureSelectedCount" class="fab-badge">{{ furnitureSelectedCount }}</span>
            </RouterLink>
            <button
              class="quotation-btn"
              :disabled="quotationLoading"
              @click="fetchQuotation"
            >{{ quotationLoading ? '估價中…' : (result.quotation_result ? '重新估價' : '取得家具報價') }}</button>
          </div>
        </div>

        <p v-if="quotationError" class="quotation-error">{{ quotationError }}</p>

        <template v-if="result.quotation_result">
          <!-- 每件偵測到的家具 -->
          <div
            v-for="(item, idx) in result.quotation_result.furniture_list"
            :key="idx"
            class="furniture-row"
          >
            <div class="furniture-label">{{ item.detected_name }}</div>
            <div class="candidates-row">
              <div
                v-for="(c, ci) in item.candidates"
                :key="ci"
                :class="['candidate-card', (selectedCandidates[idx] ?? 0) === ci ? 'selected' : '']"
                @click="selectedCandidates[idx] = ci"
              >
                <div class="candidate-img-wrap">
                  <img v-if="c.product_image_url" :src="c.product_image_url" class="candidate-img" />
                  <div v-else class="candidate-img-placeholder">資料庫沒有該項商品</div>
                </div>
                <div class="candidate-name">{{ c.name }}</div>
                <div class="candidate-price">NT$ {{ c.price.toLocaleString() }}</div>
                <div v-if="c.similarity > 0" class="candidate-sim">
                  相似度 {{ (c.similarity * 100).toFixed(0) }}%
                </div>
                <div class="candidate-actions">
                  <a
                    v-if="c.purchase_url"
                    :href="c.purchase_url"
                    target="_blank"
                    rel="noopener"
                    class="candidate-buy"
                    @click.stop
                  >商品詳情</a>
                  <button
                    type="button"
                    class="candidate-fav"
                    :class="{ active: isFurnitureFavorited(candidateToFavoriteItem(item, c)) }"
                    :title="isFurnitureFavorited(candidateToFavoriteItem(item, c)) ? '取消收藏' : '加入收藏'"
                    @click.stop="toggleFurnitureFavorite(candidateToFavoriteItem(item, c))"
                  >{{ isFurnitureFavorited(candidateToFavoriteItem(item, c)) ? '★' : '☆' }}</button>
                </div>
              </div>
            </div>
          </div>

          <!-- 動態預算 -->
          <div class="budget-row">
            <div class="budget-card mid selected-budget">
              <span class="budget-label">目前選擇預算</span>
              <span class="budget-val">NT$ {{ computedTotal.toLocaleString() }}</span>
            </div>
          </div>

          <p class="quotation-note">
            * 點選卡片可切換商品，總預算自動更新。{{ result.quotation_result.kb_match_count }}/{{ result.quotation_result.furniture_list.length }} 件成功向量比對 IKEA，其餘為 AI 估算。
          </p>
        </template>
        <p v-else-if="!quotationLoading" class="quotation-hint">
          點擊「取得家具報價」辨識畫面中的家具並推薦 IKEA 商品（約需 30 秒）。
        </p>
      </div>

    </div>
  </div>
</template>

<style scoped>
.panel { flex: 1; display: flex; flex-direction: column; min-width: 0; }

/* ── Placeholder ── */
.placeholder {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 2rem;
}
.placeholder-inner {
  text-align: center;
  max-width: 480px;
}
.placeholder-icon {
  width: 64px; height: 64px;
  background: linear-gradient(135deg, #f5e8d8, #e8d4b8);
  border-radius: 20px;
  display: flex; align-items: center; justify-content: center;
  font-size: 1.6rem; color: var(--primary);
  margin: 0 auto 1.5rem;
  box-shadow: var(--shadow-md);
}
.placeholder-inner h2 {
  font-size: 1.6rem; font-weight: 800; color: var(--text-1);
  letter-spacing: -0.02em; margin-bottom: 0.5rem;
}
.placeholder-inner p { font-size: 0.9rem; color: var(--text-3); margin-bottom: 2rem; }

.example-prompts { text-align: left; }
.example-title { font-size: 0.72rem; font-weight: 600; color: var(--text-4); text-transform: uppercase; letter-spacing: 0.06em; margin-bottom: 0.65rem; }
.example-chips { display: flex; flex-direction: column; gap: 0.5rem; }
.chip {
  padding: 0.55rem 0.9rem;
  background: rgba(255,255,255,0.75);
  border: 1px solid var(--primary-border);
  border-radius: var(--radius-md);
  font-size: 0.82rem; color: var(--text-2);
  line-height: 1.5;
  backdrop-filter: blur(6px);
}

/* ── Loading ── */
.loading-state {
  flex: 1; display: flex; flex-direction: column;
  align-items: center; justify-content: center; gap: 1rem;
}
.loading-ring {
  width: 64px; height: 64px; position: relative;
  margin-bottom: 0.5rem;
}
.loading-spinner {
  position: absolute; inset: 0;
  border: 3px solid rgba(180,140,100,0.25);
  border-top-color: var(--primary);
  border-radius: 50%;
  animation: spin 0.9s linear infinite;
}
.loading-mark {
  position: absolute; inset: 0;
  display: flex; align-items: center; justify-content: center;
  font-size: 1.2rem; color: var(--primary);
}
@keyframes spin { to { transform: rotate(360deg); } }
.loading-title { font-size: 1.1rem; font-weight: 700; color: var(--text-1); margin: 0; }
.loading-sub   { font-size: 0.83rem; color: var(--text-3); margin: 0; }

/* ── Result ── */
.result { display: flex; flex-direction: column; gap: 1rem; }

.result-header { margin-bottom: 0.5rem; }
.result-title-group { display: flex; align-items: center; gap: 1rem; flex-wrap: wrap; }
.result-title-group h2 { font-size: 1.3rem; font-weight: 800; color: var(--text-1); letter-spacing: -0.02em; }

.badges { display: flex; gap: 0.4rem; flex-wrap: wrap; }
.badge  { padding: 0.2rem 0.65rem; border-radius: 99px; font-size: 0.75rem; font-weight: 600; }
.badge.green       { background: #e8f6ee; color: #276749; }
.badge.gray        { background: rgba(255,255,255,0.7); color: #666; border: 1px solid #e5e5e5; }
.badge.purple      { background: var(--primary-light); color: var(--primary); }
.badge.badge-teal  { background: #e0f4f1; color: #1a7a6b; }
.badge.badge-orange{ background: #fff3e0; color: #b45309; }
.badge.badge-red   { background: #fdecea; color: #b91c1c; }

/* ── Image Row ── */
.image-row {
  display: flex;
  gap: 14px;
  align-items: flex-start;
  max-width: 100%;
  overflow: hidden;
  position: relative;
}
.image-row--ref-collapsed { padding-right: 52px; }

.img-slot {
  position: relative;
  overflow: hidden;
  border-radius: 12px;
  flex-shrink: 0;
  min-width: 0;
}

/* Hero: takes all remaining space */
.img-hero {
  flex: 1;
  min-width: 0;
  overflow: auto;
}

/* Reference: fixed width, transitions on collapse */
.img-ref {
  width: 380px;
  max-width: 48%;
  transition: width 0.28s cubic-bezier(0.4, 0, 0.2, 1);
}
.img-ref--collapsed {
  width: 44px;
  background: transparent;
  border-radius: 12px;
  overflow: visible;
}

/* Images fill slot with cover */
.img-cover {
  width: 100%;
  height: auto;
  max-width: 100%;
  max-height: 100%;
  display: block;
  object-fit: contain;
}

/* Bottom label — generated image path */
.img-label-bottom {
  position: absolute;
  bottom: 0; left: 0; right: 0;
  padding: 10px 14px;
  background: linear-gradient(transparent, rgba(10, 5, 25, 0.55));
}
.img-path {
  font-size: 0.68rem;
  color: rgba(255, 255, 255, 0.62);
  font-family: monospace;
}

/* Top label — reference title + collapse button */
.img-label-top {
  position: absolute;
  top: 0; left: 0; right: 0;
  padding: 10px 12px;
  background: linear-gradient(rgba(10, 5, 25, 0.48), transparent);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
}
.img-label-text {
  font-size: 0.7rem;
  font-weight: 700;
  color: rgba(255, 255, 255, 0.88);
  letter-spacing: 0.05em;
}
.collapse-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  background: rgba(255, 255, 255, 0.14);
  border: none;
  border-radius: 7px;
  cursor: pointer;
  color: rgba(255, 255, 255, 0.88);
  backdrop-filter: blur(6px);
  transition: background 0.15s;
  flex-shrink: 0;
}
.collapse-btn:hover { background: rgba(255, 255, 255, 0.28); }

/* Collapsed strip */
.collapsed-strip {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  height: 100%;
  width: 44px;
  border-radius: 12px;
  cursor: pointer;
  color: var(--text-4);
  background: rgba(255, 255, 255, 0.42);
  backdrop-filter: blur(8px);
  transition: background 0.15s, color 0.15s;
}
.collapsed-strip:hover {
  background: rgba(255, 255, 255, 0.72);
  color: var(--primary);
}
.strip-text {
  writing-mode: vertical-rl;
  text-orientation: mixed;
  font-size: 0.68rem;
  font-weight: 700;
  letter-spacing: 0.07em;
}

/* Desktop: collapsed strip floats (doesn't take layout width) */
@media (min-width: 769px) {
  .img-ref--collapsed { width: 0; }
  .img-ref--collapsed .collapsed-strip {
    position: absolute;
    right: 0;
    top: 0;
    bottom: 0;
  }
}

/* Responsive */
@media (max-width: 768px) {
  .image-row {
    flex-direction: column;
    height: auto;
    gap: 16px;
    overflow: visible;
  }
  .img-hero  { height: auto; }
  .img-ref   { width: 100%; max-width: 100%; height: auto; }
  .img-ref--collapsed { width: 100%; height: 44px; }
  .collapsed-strip {
    flex-direction: row;
    width: 100%;
    height: 44px;
  }
  .strip-text { writing-mode: unset; }
}

/* Cards */
.card {
  background: rgba(255,250,243,0.82);
  backdrop-filter: blur(8px);
  border: 1px solid #ddd0c0;
  border-radius: var(--radius-lg);
  padding: 1.25rem 1.5rem;
}
.card-style { border-color: var(--primary-border); }
.card-muted { opacity: 0.6; }

.card-title { font-size: 0.85rem; font-weight: 700; color: var(--text-2); margin-bottom: 0.9rem; letter-spacing: 0.01em; display: flex; align-items: center; gap: 0.5rem; }

/* 3D 全景 / 點雲卡片 */
.splat-card { padding-bottom: 0; overflow: hidden; }
.room3d-card { padding-bottom: 0; overflow: hidden; }
.room3d-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 0.75rem; }
.room3d-header .card-title { margin: 0; }
.btn-view3d {
  padding: 0.35rem 1rem;
  background: #1a1a2e;
  color: #c8a97e;
  border: 1.5px solid #c8a97e;
  border-radius: 8px;
  font-size: 0.8rem;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.15s;
}
.btn-view3d:hover { background: #2a2a3e; }
.btn-pano { background: linear-gradient(135deg, #6366f1, #8b5cf6); border-color: #818cf8; }
.btn-pano:hover { background: linear-gradient(135deg, #4f46e5, #7c3aed); }

.pano-status {
  display: flex; align-items: center; gap: 0.5rem;
  font-size: 0.8rem; color: #c8a97e;
}
.pano-dot {
  width: 8px; height: 8px; border-radius: 50%;
  background: #c8a97e;
  animation: pano-pulse 1.2s ease-in-out infinite;
}
@keyframes pano-pulse { 0%,100%{opacity:1} 50%{opacity:0.3} }

.pano-error {
  font-size: 0.8rem; color: #f87171;
  padding: 0.5rem 0.75rem;
  background: rgba(248,113,113,0.1);
  border-radius: 6px;
  margin-top: 0.5rem;
}
.badge-3d { font-size: 0.65rem; font-weight: 600; padding: 0.15rem 0.5rem; border-radius: 999px; background: linear-gradient(135deg, #6366f1, #8b5cf6); color: #fff; letter-spacing: 0.02em; }

/* Requirement grid */
.req-grid {
  display: grid; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
  gap: 0.65rem; margin-bottom: 0.75rem;
}
.req-item {
  background: var(--primary-light); border-radius: var(--radius-md);
  padding: 0.6rem 0.8rem; display: flex; flex-direction: column; gap: 0.2rem;
}
.req-label { font-size: 0.68rem; color: var(--text-3); font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em; }
.req-value { font-size: 0.85rem; color: var(--text-1); font-weight: 600; }

/* Raw JSON (testing) */
.raw-toggle {
  background: none; border: none; cursor: pointer;
  font-size: 0.75rem; font-weight: 600; color: var(--primary);
  padding: 0.2rem 0; text-align: left;
}
.raw-toggle:hover { text-decoration: underline; }
.raw-json-group { display: flex; flex-direction: column; gap: 0.6rem; margin-top: 0.5rem; }
.raw-json-label { font-size: 0.68rem; font-weight: 700; color: var(--text-3); text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 0.3rem; }
.raw-json {
  background: rgba(0,0,0,0.85); color: #d4e8d4;
  border-radius: var(--radius-md);
  padding: 0.75rem 0.9rem;
  font-size: 0.72rem;
  font-family: monospace;
  line-height: 1.5;
  max-height: 320px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-word;
}

/* Style meta */
.style-meta    { display: flex; align-items: center; gap: 0.55rem; flex-wrap: wrap; margin-bottom: 0.9rem; }
.style-badge   { background: var(--primary); color: white; padding: 0.18rem 0.65rem; border-radius: 99px; font-size: 0.75rem; font-weight: 700; }
.style-name    { font-size: 0.95rem; font-weight: 700; color: var(--text-1); }
.style-strength { background: var(--primary-subtle); color: var(--primary); padding: 0.18rem 0.55rem; border-radius: 99px; font-size: 0.75rem; font-weight: 600; }

.color-swatches { display: flex; gap: 0.65rem; flex-wrap: wrap; margin-bottom: 0.75rem; }
.swatch-item    { display: flex; flex-direction: column; align-items: center; gap: 0.2rem; }
.swatch         { width: 36px; height: 36px; border-radius: 8px; border: 1px solid rgba(0,0,0,0.07); box-shadow: var(--shadow-sm); }
.swatch-label   { font-size: 0.62rem; color: var(--text-3); font-weight: 600; text-transform: capitalize; }
.swatch-hex     { font-size: 0.62rem; color: var(--primary); font-family: monospace; }

.style-tags { display: flex; flex-wrap: wrap; gap: 0.35rem; margin-bottom: 0.75rem; }
.tag { background: var(--primary-light); color: var(--primary); border: 1px solid var(--primary-border); padding: 0.12rem 0.55rem; border-radius: 99px; font-size: 0.72rem; font-weight: 500; }

.muted-text { font-size: 0.875rem; color: var(--text-3); }

.result-section { background: rgba(255,250,243,0.82); border: 1px solid #ddd0c0; border-radius: var(--radius-lg); padding: 1.25rem 1.5rem; }

.gemini-desc {
  font-size: 0.875rem;
  color: var(--text-2);
  line-height: 1.65;
  margin: 0;
}

.json-details { margin-top: 0.5rem; }
.json-details summary { cursor: pointer; font-size: 0.78rem; color: var(--primary); font-weight: 600; user-select: none; padding: 0.25rem 0; }
.json-details summary:hover { color: var(--primary-hover); }

pre {
  background: var(--primary-subtle);
  padding: 0.9rem 1rem;
  border-radius: var(--radius-md);
  overflow-x: auto;
  font-size: 0.78rem;
  line-height: 1.6;
  color: var(--text-2);
  margin-top: 0.5rem;
}

/* ── Quotation ── */
.quotation-section { display: flex; flex-direction: column; gap: 1.1rem; }
.quotation-header-row {
  display: flex; align-items: center; justify-content: space-between;
  gap: 0.6rem; flex-wrap: wrap;
}
.quotation-title {
  font-size: 0.85rem; font-weight: 700; color: var(--text-2);
  display: flex; align-items: center; gap: 0.6rem; flex-wrap: wrap;
  margin-bottom: 0.1rem;
}
.ikea-badge {
  background: #0058a3; color: #fff;
  padding: 0.15rem 0.6rem; border-radius: 99px; font-size: 0.7rem; font-weight: 700;
}
.quotation-btn {
  padding: 0.4rem 0.9rem;
  background: var(--primary);
  color: #fff;
  border: none;
  border-radius: var(--radius-md);
  font-size: 0.78rem;
  font-weight: 700;
  cursor: pointer;
  transition: opacity 0.15s;
  flex-shrink: 0;
}
.quotation-btn:hover:not(:disabled) { opacity: 0.88; }
.quotation-btn:disabled { opacity: 0.55; cursor: default; }
.quotation-actions { display: flex; align-items: center; gap: 0.6rem; }
.furniture-pick-link {
  position: relative;
  padding: 0.4rem 0.9rem;
  border: 1.5px solid var(--primary-border);
  border-radius: var(--radius-md);
  color: var(--primary);
  font-size: 0.78rem;
  font-weight: 700;
  text-decoration: none;
  white-space: nowrap;
}
.furniture-pick-link:hover { background: var(--primary-light); }
.fab-badge {
  position: absolute;
  top: -6px;
  right: -6px;
  min-width: 16px;
  height: 16px;
  padding: 0 4px;
  border-radius: 999px;
  background: #c0392b;
  color: #fff;
  font-size: 0.62rem;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  line-height: 1;
}
.quotation-error { font-size: 0.78rem; color: #b91c1c; margin: 0; }
.quotation-hint { font-size: 0.82rem; color: var(--text-3); margin: 0; }

/* Furniture row */
.furniture-row { display: flex; flex-direction: column; gap: 0.5rem; }
.furniture-label {
  font-size: 0.78rem; font-weight: 700; color: var(--text-2);
  padding: 0 0.1rem;
}

/* Candidates */
.candidates-row {
  display: flex; gap: 0.6rem; overflow-x: auto;
  padding-bottom: 0.25rem;
}
.candidate-card {
  display: flex; flex-direction: column; gap: 0.3rem;
  min-width: 120px; max-width: 150px; flex-shrink: 0;
  border: 1.5px solid #e0d8cc;
  border-radius: var(--radius-md);
  padding: 0.6rem;
  cursor: pointer;
  background: rgba(255,255,255,0.7);
  transition: border-color 0.15s, box-shadow 0.15s;
}
.candidate-card:hover {
  border-color: var(--primary-border);
  box-shadow: 0 2px 8px rgba(180,140,100,0.15);
}
.candidate-card.selected {
  border-color: var(--primary);
  background: var(--primary-light);
  box-shadow: 0 0 0 2px var(--primary-border);
}
.candidate-img-wrap {
  width: 100%; aspect-ratio: 1;
  background: #f5f0ea;
  border-radius: 6px;
  overflow: hidden;
  display: flex; align-items: center; justify-content: center;
}
.candidate-img { width: 100%; height: 100%; object-fit: cover; display: block; }
.candidate-img-placeholder { font-size: 0.65rem; color: var(--text-4); text-align: center; padding: 0 0.4rem; line-height: 1.4; }
.candidate-name { font-size: 0.72rem; color: var(--text-2); line-height: 1.3; }
.candidate-price { font-size: 0.82rem; font-weight: 800; color: var(--text-1); }
.candidate-sim { font-size: 0.65rem; color: var(--text-3); }
.candidate-actions {
  margin-top: auto;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.4rem;
}
.candidate-buy {
  font-size: 0.72rem; font-weight: 700; color: #0058a3;
  text-decoration: none;
}
.candidate-buy:hover { text-decoration: underline; }
.candidate-fav {
  flex-shrink: 0;
  width: 22px; height: 22px;
  border: 1.5px solid #e0d8cc;
  border-radius: 50%;
  background: #fff;
  color: var(--text-4);
  font-size: 0.85rem;
  line-height: 1;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: border-color 0.15s, color 0.15s, background 0.15s;
}
.candidate-fav:hover { border-color: var(--primary-border); color: var(--primary); }
.candidate-fav.active {
  border-color: var(--primary);
  background: var(--primary-light);
  color: var(--primary);
}

/* Budget */
.budget-row { display: flex; gap: 0.75rem; flex-wrap: wrap; }
.budget-card {
  flex: 1; min-width: 120px; border-radius: var(--radius-md); padding: 0.75rem 1rem;
  display: flex; flex-direction: column; gap: 0.25rem; text-align: center;
}
.budget-card.low  { background: #f5f5f5; border: 1px solid #e0e0e0; }
.budget-card.mid  { background: var(--primary-light); border: 2px solid var(--primary-border); }
.budget-card.high { background: #fff8e8; border: 1px solid #f0d890; }
.selected-budget  { order: -1; }
.budget-label { font-size: 0.7rem; font-weight: 700; color: var(--text-3); text-transform: uppercase; letter-spacing: 0.05em; }
.budget-val   { font-size: 1rem; font-weight: 800; color: var(--text-1); white-space: nowrap; }
.budget-card.mid .budget-val { color: var(--primary); }

.quotation-note { font-size: 0.75rem; color: var(--text-4); line-height: 1.5; margin: 0; }
</style>
