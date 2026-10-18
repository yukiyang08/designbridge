<script setup>
/**
 * 各環節耗時面板：顯示 /api/generate 回傳的 timings（後端 log_stage 收集）。
 * 子步驟以時間區間包含關係判斷層級，長條的位置/長度對應實際起訖時間。
 */
import { computed, onMounted, onBeforeUnmount } from 'vue'

const props = defineProps({
  timings: { type: Array, required: true },
  elapsed: { type: String, default: '' },        // 後端回傳的 "123.45s"
  routing: { type: String, default: '' },
})
const emit = defineEmits(['close'])

const NODE_LABEL = {
  requirement_analyzer: '需求分析（Gemini）',
  visual_preprocessing: '視覺前處理',
  layout_and_style_agent: '家具佈局與風格',
  composer: '合併提示詞',
  renderer: '渲染出圖',
  adjuster_agent: '局部重繪（微調）',
  clip_evaluator: 'CLIP 評分',
}
const STEP_LABEL = {
  depth_estimation: '深度估計',
  segmentation: '語意分割',
  parallel: '深度＋分割（並行）',
  depth_to_layout: '深度轉房間佈局',
  style_search: '風格搜尋',
  layout_agent: '家具佈局',
  llm_layout: 'LLM 擺放家具',
  optimize_positions: '位置最佳化',
  gemini_style_analysis: 'Gemini 風格分析',
  post_depth_estimation: '出圖後補跑深度估計',
  evaluate: '評分',
  translate: '翻譯提示詞',
  intent: '判斷修改意圖',
  sam2: 'SAM 2 圈選物件',
  lama: 'LaMa 移除物件',
  fal_inpainting: 'fal.ai 局部重繪',
}

function labelOf(raw) {
  if (NODE_LABEL[raw]) return NODE_LABEL[raw]
  if (raw.startsWith('fal.')) return `fal.ai 請求（${raw.slice(4)}）`
  const step = raw.split('.').pop()
  if (STEP_LABEL[step]) return STEP_LABEL[step]
  if (/fal/.test(step)) return `fal.ai 出圖（${step}）`
  if (/hf_/.test(step)) return `Hugging Face（${step}）`
  return step
}

const total = computed(() => {
  const fromApi = parseFloat(props.elapsed)
  if (fromApi > 0) return fromApi
  return Math.max(0.01, ...props.timings.map(t => t.start + t.seconds))
})

// graph 節點（名稱沒有「.」）固定在第一層；子步驟依被幾段時間區間包住決定縮排
const rows = computed(() => {
  const eps = 0.05
  const isNode = t => !t.label.includes('.')
  const list = props.timings.filter(t => t.seconds >= 0.01 || isNode(t))
  const contains = (p, t) => p !== t && p.seconds > t.seconds
    && p.start <= t.start + eps && p.start + p.seconds + eps >= t.start + t.seconds
  return list
    .map(t => ({ ...t, depth: isNode(t) ? 0 : Math.min(2, list.filter(p => contains(p, t)).length) }))
    .sort((a, b) => a.start - b.start || a.depth - b.depth || (a.start + a.seconds) - (b.start + b.seconds))
    .map(t => ({
      ...t,
      name: labelOf(t.label),
      left: (t.start / total.value) * 100,
      width: Math.max(0.6, (t.seconds / total.value) * 100),
    }))
})

const title = computed(() => props.routing === 'design_adjuster' ? '微調耗時' : '生成耗時')
const fmt = s => s >= 60 ? `${Math.floor(s / 60)} 分 ${(s % 60).toFixed(1)} 秒` : `${s.toFixed(1)} 秒`

function onKey(e) { if (e.key === 'Escape') emit('close') }
onMounted(() => window.addEventListener('keydown', onKey))
onBeforeUnmount(() => window.removeEventListener('keydown', onKey))
</script>

<template>
  <!-- 掛到 body：結果頁外層有 transform，fixed 會被侷限在卡片內 -->
  <Teleport to="body">
  <div class="tp-backdrop" @click.self="emit('close')">
    <div class="tp" role="dialog" aria-modal="true" :aria-label="title">
      <header class="tp-head">
        <div>
          <h3 class="tp-title">{{ title }}</h3>
          <p class="tp-total">總計 {{ fmt(total) }}</p>
        </div>
        <button type="button" class="tp-close" aria-label="關閉" @click="emit('close')">✕</button>
      </header>

      <ul class="tp-list">
        <li v-for="(r, i) in rows" :key="i" :class="['tp-row', `d${r.depth}`]" :title="r.detail ? `${r.label}（${r.detail}）` : r.label">
          <span class="tp-name">{{ r.name }}</span>
          <span class="tp-track">
            <span class="tp-bar" :style="{ left: r.left + '%', width: r.width + '%' }" />
          </span>
          <span class="tp-sec">{{ fmt(r.seconds) }}</span>
        </li>
      </ul>
      <p class="tp-note">長條位置代表開始與結束的時間點；縮排的是上一層裡的子步驟。</p>
    </div>
  </div>
  </Teleport>
</template>

<style scoped>
.tp-backdrop {
  position: fixed;
  inset: 0;
  z-index: 50;
  display: grid;
  place-items: center;
  padding: 16px;
  background: rgba(20, 18, 14, 0.45);
  line-height: normal;
}
.tp {
  width: min(640px, 100%);
  max-height: 85vh;
  overflow-y: auto;
  padding: 1.25rem 1.4rem;
  border-radius: 12px;
  background: #fff;
  box-shadow: var(--db-shadow-soft);
  color: var(--db-text);
}
.tp-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 1rem; margin-bottom: 0.9rem; }
.tp-title { margin: 0; font-family: var(--db-font-display); font-style: italic; font-weight: 500; font-size: 1.2rem; }
.tp-total { margin: 0.2rem 0 0; font-size: 0.85rem; color: var(--db-text-soft); }
.tp-close { border: none; background: none; font-size: 1rem; color: var(--db-text-soft); cursor: pointer; padding: 0.2rem; }
.tp-close:hover { color: var(--db-text); }
.tp-list { list-style: none; margin: 0; padding: 0; }
.tp-row {
  display: grid;
  grid-template-columns: minmax(0, 11rem) 1fr 5.5rem;
  align-items: center;
  gap: 0.75rem;
  padding: 0.35rem 0;
  font-size: 0.85rem;
}
.tp-row.d0 { font-weight: 600; border-top: 1px solid #f0ede6; padding-top: 0.55rem; }
.tp-row.d0:first-child { border-top: none; }
.tp-row.d1 .tp-name { padding-left: 1rem; color: var(--db-text-soft); }
.tp-row.d2 .tp-name { padding-left: 2rem; color: var(--db-placeholder); }
.tp-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.tp-track { position: relative; height: 8px; border-radius: 4px; background: #f2efe8; }
.tp-bar { position: absolute; top: 0; bottom: 0; border-radius: 4px; background: var(--db-text-soft); }
.tp-row.d0 .tp-bar { background: var(--db-text); }
.tp-row.d2 .tp-bar { background: var(--db-placeholder); }
.tp-sec { text-align: right; font-variant-numeric: tabular-nums; }
.tp-note { margin: 0.9rem 0 0; font-size: 0.75rem; color: var(--db-placeholder); }
@media (max-width: 520px) {
  .tp-row { grid-template-columns: minmax(0, 1fr) 4.8rem; }
  .tp-track { grid-column: 1 / -1; grid-row: 2; }
}
</style>
