<script setup>
/**
 * 房型配置 CAD 平面圖產生器 — 獨立新功能，跟既有精靈流程（useDesignFlow）無關。
 * 使用者輸入幾房幾廳幾衛幾廚幾陽台＋總坪數，後端 /api/generate-room-plan
 * 直接切割整層樓的房間配置（牆／門／窗／尺寸標註），回傳 SVG 給這頁顯示。
 */
import { reactive, ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import LoadingState from '@/components/shell/LoadingState.vue'
import { apiUrl, mediaUrl } from '@/config/api'

const router = useRouter()
function goHome() { router.push('/') }

const PING_TO_M2 = 3.305785

const COUNT_FIELDS = [
  { key: 'bedroom_count', label: '臥室' },
  { key: 'living_count', label: '客餐廳' },
  { key: 'bathroom_count', label: '衛浴' },
  { key: 'kitchen_count', label: '廚房' },
  { key: 'balcony_count', label: '陽台' },
]

const counts = reactive({
  bedroom_count: 2,
  living_count: 1,
  bathroom_count: 1,
  kitchen_count: 1,
  balcony_count: 1,
})
const totalPing = ref(25)

const loading = ref(false)
const error = ref('')
const result = ref(null)

const estimatedM2 = computed(() => (totalPing.value || 0) * PING_TO_M2)

function setCount(key, delta) {
  counts[key] = Math.max(0, Math.min(10, counts[key] + delta))
}

async function generate() {
  loading.value = true
  error.value = ''
  result.value = null
  try {
    const res = await fetch(apiUrl('/api/generate-room-plan'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...counts, total_ping: totalPing.value }),
    })
    const data = await res.json()
    if (!res.ok) throw new Error(data.detail || `生成失敗（${res.status}）`)
    result.value = data
  } catch (e) {
    error.value = e.message || '生成失敗，請稍後再試'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="room-plan-page">
    <header class="room-plan-header">
      <button class="back-btn" @click="goHome">← 返回</button>
      <h1>房型配置 CAD 平面圖</h1>
    </header>

    <div class="db-card room-plan-card">
      <p class="page-hint">輸入幾房幾廳＋總坪數，自動生成含牆體、門窗與尺寸標註的房間配置平面圖。</p>

      <div class="count-grid">
        <div v-for="f in COUNT_FIELDS" :key="f.key" class="count-row">
          <span class="count-label">{{ f.label }}</span>
          <div class="count-stepper">
            <button type="button" class="count-btn" @click="setCount(f.key, -1)">−</button>
            <span class="count-num">{{ counts[f.key] }}</span>
            <button type="button" class="count-btn" @click="setCount(f.key, 1)">＋</button>
          </div>
        </div>
      </div>

      <div class="ping-main">
        <span class="ping-word-lg">總坪數 約</span>
        <input
          v-model.number="totalPing"
          type="number" min="1" max="200" step="0.5"
          class="db-input ping-input-lg"
          aria-label="總坪數"
        />
        <span class="ping-word-lg">坪</span>
      </div>
      <p class="ping-hint">≈ {{ estimatedM2.toFixed(1) }} m²</p>

      <div class="actions">
        <button class="db-btn" :disabled="loading" @click="generate">生成平面圖</button>
      </div>

      <LoadingState v-if="loading" title="正在生成平面圖" sub="依房型配置切割空間、繪製牆體與門窗…" />
      <p v-if="error" class="db-error">{{ error }}</p>

      <div v-if="result && !loading" class="result">
        <div class="svg-wrap" v-html="result.svg_markup"></div>

        <div class="summary">
          <span>總面積 {{ result.total_m2.toFixed(1) }} m²（約 {{ result.total_ping }} 坪）</span>
          <a :href="mediaUrl(result.svg_path)" target="_blank" rel="noopener" class="download-link" download>
            開新分頁／下載 SVG
          </a>
        </div>

        <ul v-if="result.warnings && result.warnings.length" class="warnings">
          <li v-for="(w, i) in result.warnings" :key="i">⚠ {{ w }}</li>
        </ul>

        <div class="room-list">
          <div v-for="r in result.rooms" :key="r.id" class="room-item">
            <span class="room-label">{{ r.label_zh }}</span>
            <span class="room-area">{{ r.actual_area_m2.toFixed(1) }} m²</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.room-plan-page {
  max-width: 960px;
  margin: 0 auto;
  padding: 1.5rem 1rem 4rem;
  font-family: var(--db-font-body);
  color: var(--db-text);
}

.room-plan-header {
  display: flex;
  align-items: center;
  gap: 1rem;
  margin-bottom: 1.25rem;
}
.room-plan-header h1 {
  margin: 0;
  font-family: var(--db-font-display);
  font-style: italic;
  font-weight: 500;
  font-size: 1.4rem;
}
.back-btn {
  background: none;
  border: 1px solid #999;
  border-radius: 6px;
  padding: 0.3rem 0.8rem;
  cursor: pointer;
  font-size: 0.88rem;
  color: var(--db-text);
  font-weight: 600;
}
.back-btn:hover { background: #eee; border-color: #666; }

.room-plan-card {
  padding: clamp(1.5rem, 4vw, 2.5rem);
}

.page-hint {
  margin: 0 0 1.75rem;
  text-align: center;
  color: var(--db-text-soft);
  font-size: 0.92rem;
}

.count-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 1rem;
  max-width: 720px;
  margin: 0 auto 1.75rem;
}
.count-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  padding: 0.6rem 1rem;
  border-radius: var(--db-radius-chip);
  background: var(--db-chip-soft);
}
.count-label {
  font-family: var(--db-font-display);
  font-style: italic;
  font-weight: 500;
  color: var(--db-text);
}
.count-stepper { display: flex; align-items: center; gap: 0.6rem; }
.count-btn {
  width: 28px; height: 28px;
  border: none; border-radius: 50%;
  background: #fff;
  color: var(--db-text);
  font-size: 1rem;
  line-height: 1;
  cursor: pointer;
}
.count-btn:hover { background: var(--db-accent); color: var(--db-on-accent); }
.count-num {
  min-width: 1.4em;
  text-align: center;
  font-variant-numeric: tabular-nums;
  font-size: 1.05rem;
}

.ping-main {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.7rem;
}
.ping-word-lg {
  font-family: var(--db-font-display);
  font-style: italic;
  font-size: 1.2rem;
  color: var(--db-text);
}
.ping-input-lg {
  width: 120px;
  height: 58px;
  border: 2px solid var(--db-chip);
  border-radius: 8px;
  background: #fff;
  text-align: center;
  font-size: 1.5rem;
  font-variant-numeric: tabular-nums;
}
.ping-input-lg:focus { border-color: var(--db-accent); background: #fff; }
.ping-hint {
  margin: 0.6rem 0 0;
  text-align: center;
  font-size: 0.85rem;
  color: var(--db-text-soft);
}

.actions {
  display: flex;
  justify-content: center;
  padding-top: 1.5rem;
}

.result { margin-top: 2rem; }
.svg-wrap {
  overflow-x: auto;
  text-align: center;
  padding: 1rem;
  border-radius: var(--db-radius-chip);
  background: #fafafa;
}
.svg-wrap :deep(svg) { max-width: 100%; height: auto; }

.summary {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: center;
  gap: 1rem;
  margin-top: 1rem;
  font-size: 0.95rem;
  color: var(--db-text);
}
.download-link {
  color: var(--db-text-soft);
  text-decoration: underline;
}
.download-link:hover { color: var(--db-text); }

.warnings {
  margin: 1rem auto 0;
  max-width: 560px;
  padding: 0.75rem 1rem;
  border-radius: 8px;
  background: var(--db-danger-soft);
  color: var(--db-danger);
  font-size: 0.85rem;
  list-style: none;
}
.warnings li + li { margin-top: 0.3rem; }

.room-list {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 0.6rem;
  margin-top: 1.25rem;
}
.room-item {
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.4rem 0.9rem;
  border-radius: var(--db-radius-pill);
  background: var(--db-chip-soft);
  font-size: 0.88rem;
}
.room-area { color: var(--db-text-soft); font-variant-numeric: tabular-nums; }

@media (max-width: 640px) {
  .count-grid { grid-template-columns: 1fr; }
}
</style>
