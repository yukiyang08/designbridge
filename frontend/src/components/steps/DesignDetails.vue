<script setup>
/**
 * 設計詳情：結構化需求 / 套用風格參數 / 3D 點雲 / 原始 JSON。
 *
 * 設計稿完全沒有這一區，但它是舊 ResultPanel 裡實際在用的除錯與說明資訊
 * （尤其 raw JSON 在調 prompt 時很吃重），所以整組保留，收在摺疊區裡。
 */
import { computed, ref, defineAsyncComponent } from 'vue'
import { API_BASE } from '@/config/api'

// 點雲檢視器同樣吃 three.js，展開設計詳情才載入
const PointCloudViewer = defineAsyncComponent(() => import('@/components/PointCloudViewer.vue'))

const props = defineProps({
  result: { type: Object, default: null },
})

const rawExpanded = ref(false)

const spatialLevelColor = computed(() => {
  const level = props.result?.structured_requirement?.spatial_change_level
  if (level === 'major') return 'badge-red'
  if (level === 'minor') return 'badge-orange'
  return 'badge-teal'
})

const styleReferenceImageUrl = computed(() => {
  const r = props.result
  if (!r) return ''

  const fromStyleParams = r.style_params?.reference_image_url
  if (typeof fromStyleParams === 'string' && fromStyleParams.trim()) return fromStyleParams

  const fromControlNet = r.render_result?.controlnet_inputs?.style_reference_image
  if (typeof fromControlNet !== 'string' || !fromControlNet.trim()) return ''

  const normalized = fromControlNet.replace(/\\/g, '/')
  if (normalized.startsWith('http://') || normalized.startsWith('https://')) return normalized
  if (normalized.startsWith('artifacts/')) return `${API_BASE}/${normalized}`
  return ''
})
</script>

<template>
  <div v-if="result" class="details">

    <!-- 風格參考圖 -->
    <section v-if="styleReferenceImageUrl" class="card">
      <h3 class="card-title">風格參考圖</h3>
      <img :src="styleReferenceImageUrl" alt="風格參考圖" class="ref-img" />
    </section>

    <!-- 3D 點雲 -->
    <section v-if="result.depth_cloud_url" class="card">
      <h3 class="card-title">3D 點雲 <span class="badge badge-teal">互動式</span></h3>
      <PointCloudViewer :ply-url="result.depth_cloud_url" />
    </section>

    <!-- 結構化需求 -->
    <section v-if="result.structured_requirement" class="card">
      <h3 class="card-title">
        結構化需求
        <span
          v-if="result.structured_requirement.spatial_change_level"
          :class="['badge', spatialLevelColor]"
        >{{ result.structured_requirement.spatial_change_level }}</span>
      </h3>
      <dl class="req-grid">
        <template v-if="result.structured_requirement.meta?.room_type">
          <dt>房間類型</dt><dd>{{ result.structured_requirement.meta.room_type }}</dd>
        </template>
        <template v-if="result.structured_requirement.meta?.design_goal">
          <dt>設計目標</dt><dd>{{ result.structured_requirement.meta.design_goal }}</dd>
        </template>
        <template v-if="result.structured_requirement.style_preferences?.primary_style">
          <dt>主要風格</dt><dd>{{ result.structured_requirement.style_preferences.primary_style }}</dd>
        </template>
        <template v-if="result.structured_requirement.edit_scope?.scope_value !== undefined">
          <dt>改動幅度</dt>
          <dd>{{ Number(result.structured_requirement.edit_scope.scope_value).toFixed(1) }}</dd>
        </template>
      </dl>
    </section>

    <!-- 套用風格參數 -->
    <section v-if="result.style_params" class="card">
      <h3 class="card-title">套用風格參數</h3>
      <div class="style-meta">
        <span class="style-badge">{{ result.style_params.style_profile_id || result.style_params.style_id }}</span>
        <span class="style-name">{{ result.style_params.style_profile_name || result.style_params.style_name }}</span>
        <span v-if="result.style_params.style_strength !== undefined" class="style-strength">
          強度 {{ Number(result.style_params.style_strength).toFixed(2) }}
        </span>
      </div>
      <div v-if="result.style_params.visual_elements?.colors" class="swatches">
        <div v-for="(hex, role) in result.style_params.visual_elements.colors" :key="role" class="swatch-item">
          <span class="swatch" :style="{ background: hex }"></span>
          <span class="swatch-label">{{ role }}</span>
          <span class="swatch-hex">{{ hex }}</span>
        </div>
      </div>
      <div v-if="result.style_params.semantic_tags?.length" class="tags">
        <span v-for="tag in result.style_params.semantic_tags" :key="tag" class="tag">{{ tag }}</span>
      </div>
    </section>

    <section v-else-if="result.render_result?.generation_params?.gemini_style_description" class="card">
      <h3 class="card-title">套用風格參數</h3>
      <div class="style-meta">
        <span class="style-badge">使用者上傳</span>
        <span class="style-name">Gemini 視覺分析</span>
      </div>
      <p class="desc">{{ result.render_result.generation_params.gemini_style_description }}</p>
    </section>

    <section v-else class="card">
      <h3 class="card-title">套用風格參數</h3>
      <p class="desc muted">未載入聚合風格檔，將依文字需求與預設 prompt 生成。</p>
    </section>

    <!-- 原始 JSON -->
    <section class="card">
      <button type="button" class="raw-toggle" @click="rawExpanded = !rawExpanded">
        {{ rawExpanded ? '▾' : '▸' }} 原始 JSON
      </button>
      <div v-if="rawExpanded" class="raw-group">
        <div v-if="result.structured_requirement">
          <div class="raw-label">structured_requirement</div>
          <pre class="raw">{{ JSON.stringify(result.structured_requirement, null, 2) }}</pre>
        </div>
        <div v-if="result.render_result?.generation_params">
          <div class="raw-label">generation_params</div>
          <pre class="raw">{{ JSON.stringify(result.render_result.generation_params, null, 2) }}</pre>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.details { display: grid; gap: 1rem; }

.card {
  padding: 1.1rem 1.25rem;
  border: 1px solid #ececec;
  border-radius: 12px;
  background: #fcfcfc;
}

.card-title {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  margin: 0 0 0.85rem;
  font-family: var(--db-font-display);
  font-style: italic;
  font-size: 1.1rem;
  color: var(--db-text);
}

.badge {
  padding: 0.12rem 0.5rem;
  border-radius: var(--db-radius-pill);
  font-family: var(--db-font-body);
  font-style: normal;
  font-size: 0.72rem;
  color: #fff;
}
.badge-teal   { background: #4a7c8c; }
.badge-orange { background: #c08040; }
.badge-red    { background: var(--db-danger); }

.ref-img {
  display: block;
  max-width: min(360px, 100%);
  border-radius: 8px;
}

.req-grid {
  display: grid;
  grid-template-columns: max-content 1fr;
  gap: 0.5rem 1.25rem;
  margin: 0;
  font-size: 0.9rem;
}
.req-grid dt { color: var(--db-text-soft); }
.req-grid dd { margin: 0; color: var(--db-text); }

.style-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.6rem;
  font-size: 0.9rem;
}
.style-badge {
  padding: 0.15rem 0.6rem;
  border-radius: var(--db-radius-pill);
  background: var(--db-accent);
  color: var(--db-on-accent);
  font-size: 0.78rem;
}
.style-strength { color: var(--db-text-soft); font-size: 0.82rem; }

.swatches {
  display: flex;
  flex-wrap: wrap;
  gap: 0.9rem;
  margin-top: 0.9rem;
}
.swatch-item { display: flex; flex-direction: column; align-items: center; gap: 0.25rem; }
.swatch {
  width: 40px; height: 40px;
  border-radius: 8px;
  border: 1px solid rgba(0, 0, 0, 0.08);
}
.swatch-label { font-size: 0.72rem; color: var(--db-text-soft); }
.swatch-hex { font-size: 0.68rem; color: var(--db-placeholder); font-variant-numeric: tabular-nums; }

.tags { display: flex; flex-wrap: wrap; gap: 0.4rem; margin-top: 0.9rem; }
.tag {
  padding: 0.2rem 0.6rem;
  border-radius: var(--db-radius-pill);
  background: var(--db-chip-soft);
  font-size: 0.78rem;
  color: var(--db-text-soft);
}

.desc { margin: 0; font-size: 0.9rem; line-height: 1.7; color: var(--db-text); }
.muted { color: var(--db-text-soft); }

.raw-toggle {
  border: none;
  background: none;
  padding: 0;
  color: var(--db-text-soft);
  font-family: var(--db-font-body);
  font-size: 0.9rem;
  cursor: pointer;
}
.raw-toggle:hover { color: var(--db-text); }
.raw-group { display: grid; gap: 0.9rem; margin-top: 0.85rem; }
.raw-label { font-size: 0.78rem; color: var(--db-placeholder); margin-bottom: 0.3rem; }
.raw {
  max-height: 320px;
  margin: 0;
  padding: 0.75rem;
  overflow: auto;
  border-radius: 8px;
  background: #f4f4f4;
  font-size: 0.75rem;
  line-height: 1.55;
}
</style>
