<script setup>
/**
 * 收藏設計 — 從使用者角度設計的收藏畫廊，對照「歷史紀錄」(HistoryView.vue)：
 * 那邊是給開發測試用的技術清單（CLIP 分數、模型 backend、raw JSON），這裡只留
 * 使用者在意的東西（圖、描述、風格、時間），卡片放大、動作導向「接下來要做什麼」
 * （看預算、用同樣描述再設計一次），而不是「檢視細節」。
 *
 * 資料來源跟 HistoryView 共用同一個 /api/history，前端篩選 favorited === true，
 * 不需要另外的後端端點。
 */
import { reactive, ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { apiUrl, jsonFetch, mediaUrl } from '@/config/api'
import { cleanDescription } from '@/utils/text'
import { useDesignFlow } from '@/composables/useDesignFlow'

const router = useRouter()
const { startFlow, extraPrompt, selectedStyle, noStyleReference } = useDesignFlow()

const records = ref([])
const loading = ref(true)
const error = ref('')
const unfavoritingIds = ref(new Set())

onMounted(async () => {
  try {
    const res = await fetch(apiUrl('/api/history'))
    if (!res.ok) throw new Error(res.status)
    const all = await res.json()
    records.value = all.filter(r => r.favorited)
  } catch {
    error.value = '無法載入收藏'
  } finally {
    loading.value = false
  }
})

async function unfavorite(r) {
  const ids = new Set(unfavoritingIds.value); ids.add(r.task_id); unfavoritingIds.value = ids
  try {
    const res = await jsonFetch(`/api/history/${encodeURIComponent(r.task_id)}/favorite`, { favorited: false }, 'PATCH')
    if (!res.ok) throw new Error(res.status)
    records.value = records.value.filter(x => x.task_id !== r.task_id)
  } catch {
    error.value = '取消收藏失敗，請稍後再試'
  } finally {
    const s = new Set(unfavoritingIds.value); s.delete(r.task_id); unfavoritingIds.value = s
  }
}

function formatTime(ts) {
  return ts ? ts.replace('T', ' ').slice(0, 16) : ''
}

function styleLabel(r) {
  return r.style_params?.style_profile_name || null
}

function styleDescription(r) {
  return cleanDescription(r.gemini_style_description || r.style_params?.style_summary || '')
}

// ── 家具預算：每張卡片各自收合/展開，點了才打 /api/quotation（跟報價一樣要
//    辨識畫面家具，約 30 秒，所以不在列表載入時就一次打完全部）。只顯示每件家具
//    排序第一的候選＋總價，不做候選切換/單品收藏——那是生成流程本身的工作，
//    這裡只是「回顧這組設計大概要花多少」。
const quotations = reactive({})   // task_id -> { open, loading, error, data }

function qState(r) {
  return quotations[r.task_id] ||= { open: false, loading: false, error: '', data: null }
}

async function toggleQuotation(r) {
  const st = qState(r)
  st.open = !st.open
  if (!st.open || st.data || st.loading) return
  st.loading = true
  st.error = ''
  try {
    const res = await jsonFetch('/api/quotation', {
      image_path: r.generated_image_path,
      structured_requirement: null,
      selected_furniture: [],
    })
    if (!res.ok) throw new Error(`${res.status}`)
    st.data = await res.json()
  } catch (e) {
    st.error = '估價失敗，請稍後再試'
  } finally {
    st.loading = false
  }
}

function quotationTotal(data) {
  return (data?.furniture_list || []).reduce((sum, item) => sum + (item.candidates?.[0]?.price ?? 0), 0)
}

// ── 用同樣描述再設計一次：帶著這筆紀錄的文字描述＋風格（有對應風格庫 id 才能
//    帶），開一個新的「直接描述」流程（跳過排平面圖，最快能再生成一次的路徑）。
//    自訂上傳的參考圖沒辦法帶（只存了 URL，沒有原始檔案可以重傳），所以只接得住
//    風格庫裡的風格；是輕量版的「重用」，不是完整復原當初的平面圖/房型。
function reuseDesign(r) {
  startFlow('skip')
  extraPrompt.value = r.text_prompt || ''
  const styleId = r.style_params?.style_profile_id
  if (styleId) {
    selectedStyle.value = styleId
    noStyleReference.value = false
  }
  router.push('/studio')
}
</script>

<template>
  <div class="favorites">
    <header class="fav-header">
      <button class="back-btn" @click="router.push('/account')">← 個人專區</button>
      <h1 class="fav-title">收藏設計 <span v-if="records.length" class="fav-count">{{ records.length }} 件</span></h1>
    </header>

    <p v-if="error" class="db-error fav-error">{{ error }}</p>

    <div v-if="loading" class="state-msg">載入中…</div>
    <div v-else-if="records.length === 0" class="empty-state">
      <p>還沒有收藏任何設計</p>
      <p class="empty-hint">在生成結果頁按「收藏這個設計」，喜歡的設計就會出現在這裡。</p>
      <button class="db-btn" @click="router.push('/start')">開始新的設計</button>
    </div>

    <div v-else class="grid">
      <article v-for="r in records" :key="r.task_id" class="card">
        <div class="card-img-wrap">
          <a v-if="r.generated_image_url" :href="r.generated_image_url" target="_blank" rel="noopener">
            <img :src="r.generated_image_url" alt="收藏的設計圖" class="card-img" loading="lazy" />
          </a>
          <div v-else class="card-no-img">無圖</div>
          <button
            type="button" class="unfav-btn" :disabled="unfavoritingIds.has(r.task_id)"
            title="取消收藏" @click="unfavorite(r)"
          >★</button>
        </div>

        <div class="card-body">
          <p class="card-prompt">{{ r.text_prompt || '（無描述）' }}</p>
          <div v-if="styleLabel(r)" class="card-style">{{ styleLabel(r) }}</div>
          <p v-if="styleDescription(r)" class="card-desc">{{ styleDescription(r) }}</p>
          <span class="card-time">{{ formatTime(r.timestamp) }}</span>

          <div class="card-actions">
            <button type="button" class="db-btn db-btn--ghost db-btn--sm" @click="toggleQuotation(r)">
              {{ qState(r).open ? '收合家具預算' : '查看家具預算' }}
            </button>
            <button type="button" class="db-btn db-btn--sm" @click="reuseDesign(r)">
              用同樣描述再設計一次
            </button>
          </div>

          <div v-if="qState(r).open" class="quotation">
            <p v-if="qState(r).loading" class="q-hint" role="status">正在辨識畫面中的家具…約需 30 秒</p>
            <p v-else-if="qState(r).error" class="db-error">{{ qState(r).error }}</p>
            <template v-else-if="qState(r).data">
              <ul class="q-list">
                <li v-for="(item, idx) in qState(r).data.furniture_list" :key="idx" class="q-item">
                  <img
                    v-if="item.candidates?.[0]?.product_image_url"
                    :src="item.candidates[0].product_image_url" :alt="item.candidates[0].name" class="q-item-img"
                  />
                  <span class="q-item-name">{{ item.candidates?.[0]?.name || item.detected_name }}</span>
                  <span class="q-item-price">NT$ {{ (item.candidates?.[0]?.price ?? 0).toLocaleString() }}</span>
                </li>
              </ul>
              <div class="q-total">
                <span>預估總價</span>
                <strong>NT$ {{ quotationTotal(qState(r).data).toLocaleString() }}</strong>
              </div>
            </template>
          </div>
        </div>
      </article>
    </div>
  </div>
</template>

<style scoped>
.favorites {
  max-width: 1200px;
  margin: 0 auto;
  padding: 1.75rem 1.5rem 3rem;
}

.fav-header { display: flex; align-items: center; gap: 1rem; margin-bottom: 1.5rem; }
.back-btn {
  border: 1px solid #d8d4cb;
  border-radius: var(--db-radius-pill);
  background: #fff;
  padding: 0.4rem 1rem;
  color: var(--db-text);
  font-size: 0.88rem;
  cursor: pointer;
}
.back-btn:hover { border-color: var(--db-accent); background: var(--db-chip-soft); }

.fav-title {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  margin: 0;
  font-family: var(--db-font-display);
  font-style: italic;
  font-weight: 500;
  font-size: 1.6rem;
  color: var(--db-text);
}
.fav-count { font-size: 0.85rem; color: var(--db-text-soft); font-style: normal; }

.fav-error { margin: 0 0 1rem; }

.state-msg { text-align: center; color: var(--db-text-soft); padding: 3rem 0; }

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.6rem;
  padding: 4rem 1rem;
  text-align: center;
  color: var(--db-text-soft);
}
.empty-hint { font-size: 0.88rem; color: var(--db-placeholder); margin: 0 0 0.75rem; }

.grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
  gap: 1.5rem;
}

.card {
  display: flex;
  flex-direction: column;
  border-radius: var(--db-radius-card, 16px);
  background: #fff;
  box-shadow: var(--db-shadow-soft);
  overflow: hidden;
}

.card-img-wrap { position: relative; aspect-ratio: 4 / 3; background: var(--db-chip-soft); }
.card-img { width: 100%; height: 100%; object-fit: cover; display: block; }
.card-no-img { display: grid; place-items: center; width: 100%; height: 100%; color: var(--db-placeholder); }

.unfav-btn {
  position: absolute;
  top: 0.65rem; right: 0.65rem;
  width: 34px; height: 34px;
  display: grid; place-items: center;
  border: none; border-radius: 50%;
  background: rgba(255, 255, 255, 0.92);
  color: var(--db-accent);
  font-size: 1.15rem;
  cursor: pointer;
  box-shadow: 0 1px 6px rgba(0, 0, 0, 0.2);
}
.unfav-btn:hover { background: #fff; }
.unfav-btn:disabled { opacity: 0.5; cursor: not-allowed; }

.card-body { display: flex; flex-direction: column; gap: 0.5rem; padding: 1.1rem 1.25rem 1.25rem; }
.card-prompt { margin: 0; font-size: 0.95rem; color: var(--db-text); line-height: 1.5; }
.card-style {
  align-self: flex-start;
  padding: 0.15rem 0.65rem;
  border-radius: var(--db-radius-pill);
  background: var(--db-accent-soft);
  color: var(--db-accent-deep, var(--db-text));
  font-size: 0.78rem;
}
.card-desc {
  margin: 0;
  color: var(--db-text-soft);
  font-size: 0.85rem;
  line-height: 1.6;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.card-time { font-size: 0.75rem; color: var(--db-placeholder); }

.card-actions { display: flex; flex-wrap: wrap; gap: 0.6rem; margin-top: 0.4rem; }

.quotation { margin-top: 0.75rem; padding-top: 0.85rem; border-top: 1px solid #f0f0f0; }
.q-hint { margin: 0; font-size: 0.85rem; color: var(--db-text-soft); }
.q-list { list-style: none; margin: 0 0 0.6rem; padding: 0; display: flex; flex-direction: column; gap: 0.5rem; }
.q-item { display: flex; align-items: center; gap: 0.6rem; }
.q-item-img { width: 36px; height: 36px; object-fit: contain; border-radius: 6px; background: var(--db-chip-soft); flex-shrink: 0; }
.q-item-name { flex: 1; min-width: 0; font-size: 0.85rem; color: var(--db-text); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.q-item-price { font-size: 0.85rem; color: var(--db-text); font-variant-numeric: tabular-nums; }
.q-total { display: flex; justify-content: space-between; font-size: 0.92rem; color: var(--db-text); padding-top: 0.5rem; border-top: 1px dashed #e8e6e1; }

@media (max-width: 640px) {
  .favorites { padding: 1.25rem 1rem 2.5rem; }
  .grid { grid-template-columns: 1fr; }
}
</style>
