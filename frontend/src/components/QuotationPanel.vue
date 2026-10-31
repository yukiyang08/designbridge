<script setup>
/** 結果圖的家具推薦清單：每件家具選中的商品、換款、收藏與總價。 */
import { reactive, computed, ref, watch } from 'vue'
import { useDesignFlow } from '@/composables/useDesignFlow'
import { useFurnitureSelection } from '@/composables/useFurnitureSelection'

const { result, quotationLoading, quotationError, fetchQuotation } = useDesignFlow()
const { toggle: toggleFavorite, isSelected: isFavorited } = useFurnitureSelection()

const quotation = computed(() => result.value?.quotation_result || null)

// 有商品圖才算精準導購；預設選第一個有圖的候選，都沒圖才落到預估估價
const hasImg = (c) => !!c?.product_image_url
const firstWithImage = (item) => Math.max(0, (item.candidates || []).findIndex(hasImg))

// 每件家具目前選中的候選 index
const selectedCandidates = reactive({})
watch(
  () => quotation.value?.furniture_list,
  (list) => {
    if (list) list.forEach((item, idx) => { selectedCandidates[idx] = quotation.value?.selected_indices?.[idx] ?? firstWithImage(item) })
  },
  { immediate: true },
)
// 換款的選擇寫回這份報價（selected_indices）：整層總覽加總各房間預算時要用同一份選擇，
// 不然這裡換過款、總覽還是用預設推薦算
watch(selectedCandidates, () => {
  const q = quotation.value
  const list = q?.furniture_list
  if (!list) return
  const saved = list.map((_, i) => q.selected_indices?.[i] ?? 0)
  const now = list.map((_, i) => selectedCandidates[i] ?? 0)
  if (saved.every((v, i) => v === now[i])) return
  result.value = { ...result.value, quotation_result: { ...q, selected_indices: { ...now } } }
}, { deep: true })

// IKEA 商品名常只有代號（MALM、KALLAX），多一個中文類別才看得出是什麼；
// 沒有明確類別時退回偵測到的名稱
const CATEGORY_ZH = {
  sofa: '沙發', table: '桌子', chair: '椅子', lamp: '燈具', rug: '地毯',
  curtain: '窗簾', storage: '收納', shelf: '收納', bed: '床',
}
const categoryLabel = (item) => CATEGORY_ZH[item.category] || item.detected_name
// IKEA 商品全名後面一長串顏色、尺寸（"KALLAX 層架組, 白色, 77x147 公分"）：清單只留第一段，
// 全名放在 title（滑過去看得到）與商品頁；"VIHALS/VIHALS" 這種重複的也去掉
const shortName = (name = '') => name.split(/[,，]/)[0].trim().replace(/^(\S+)\/\1(?=\s|$)/, '$1')

// 候選完全相同的家具（例如同一款 KALLAX 被偵測到 4 次）合併成一行 ×N；
// 換款時同組的每一件一起換，總價仍是逐件加總
const furnitureGroups = computed(() => {
  const groups = new Map()
  ;(quotation.value?.furniture_list || []).forEach((item, idx) => {
    const key = (item.candidates || []).map(c => c.id || c.name).join('|') || `#${idx}`
    if (!groups.has(key)) groups.set(key, { key, item, idxs: [] })
    groups.get(key).idxs.push(idx)
  })
  return [...groups.values()]
})
const groupPick = (g) => selectedCandidates[g.idxs[0]] ?? 0
function setGroupPick(g, ci) { g.idxs.forEach(i => { selectedCandidates[i] = ci }) }
const pickedOf = (g) => g.item.candidates?.[groupPick(g)]
const shopGroups = computed(() => furnitureGroups.value.filter(g => hasImg(pickedOf(g))))
const estimateGroups = computed(() => furnitureGroups.value.filter(g => pickedOf(g) && !hasImg(pickedOf(g))))
// 換款只列有圖的商品，保留原本的 index 才能寫回 selectedCandidates
const imageAlts = (g) => (g.item.candidates || []).map((a, ai) => ({ a, ai })).filter(x => hasImg(x.a))

// 目前展開「換款」的那一組
const openRow = ref(null)
watch(quotation, () => { openRow.value = null })
// 向量與關鍵字都沒比到時後端只給一筆 LLM 估價：沒連結、沒圖、similarity 0
const isEstimate = (c) => !c.purchase_url && !c.product_image_url && !(c.similarity > 0)

const computedTotal = computed(() => {
  const list = quotation.value?.furniture_list
  if (!list) return 0
  return list.reduce((sum, item, idx) => {
    const c = item.candidates?.[selectedCandidates[idx] ?? 0]
    return sum + (c?.price ?? 0)
  }, 0)
})

function toFavoriteItem(item, c) {
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
</script>

<template>
  <section>
    <div class="head">
      <h2 class="block-title">家具推薦</h2>
      <button
        v-if="quotation"
        type="button" class="refresh" title="重新估價" aria-label="重新估價"
        :disabled="quotationLoading" @click="fetchQuotation"
      >
        <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <path d="M21 12a9 9 0 1 1-2.64-6.36M21 4v5h-5" />
        </svg>
      </button>
      <button v-else class="db-btn db-btn--sm" :disabled="quotationLoading" @click="fetchQuotation">
        {{ quotationLoading ? '估價中…' : '取得家具報價' }}
      </button>
    </div>

    <p v-if="quotationError" class="db-error">{{ quotationError }}</p>

    <template v-if="quotation">
      <div class="total">
        <span class="total-label">預算 · {{ quotation.furniture_list.length }} 件</span>
        <span class="total-val">NT$ {{ computedTotal.toLocaleString() }}</span>
      </div>

      <ul v-if="shopGroups.length" class="furn-list">
        <li v-for="g in shopGroups" :key="g.key" class="furn">
          <template v-for="c in [pickedOf(g)]" :key="c?.id || g.key">
            <div v-if="c" class="furn-main">
              <span class="furn-thumb">
                <img :src="c.product_image_url" :alt="c.name" />
              </span>
              <div class="furn-info" :title="g.item.detected_name">
                <span class="furn-cat">{{ categoryLabel(g.item) }}</span>
                <a v-if="c.purchase_url" :href="c.purchase_url" target="_blank" rel="noopener" class="name name--link" :title="c.name">{{ shortName(c.name) }}</a>
                <span v-else class="name" :title="c.name">{{ shortName(c.name) }}</span>
                <div class="furn-foot">
                  <span class="price">
                    NT$ {{ c.price.toLocaleString() }}
                    <small v-if="g.idxs.length > 1" class="qty">×{{ g.idxs.length }}</small>
                    <small v-if="isEstimate(c)" class="est">AI 估價</small>
                  </span>
                  <span class="furn-side">
                    <button
                      v-if="!isEstimate(c)"
                      type="button"
                      class="fav"
                      :class="{ active: isFavorited(toFavoriteItem(g.item, c)) }"
                      :title="isFavorited(toFavoriteItem(g.item, c)) ? '取消收藏' : '加入收藏'"
                      :aria-label="isFavorited(toFavoriteItem(g.item, c)) ? '取消收藏' : '加入收藏'"
                      @click="toggleFavorite(toFavoriteItem(g.item, c))"
                    >{{ isFavorited(toFavoriteItem(g.item, c)) ? '★' : '☆' }}</button>
                    <button
                      v-if="imageAlts(g).length > 1"
                      type="button" class="swap-btn" :class="{ open: openRow === g.key }"
                      title="換一款" aria-label="換一款"
                      :aria-expanded="openRow === g.key"
                      @click="openRow = openRow === g.key ? null : g.key"
                    >
                      <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                        <path d="m17 2 4 4-4 4" /><path d="M3 11v-1a4 4 0 0 1 4-4h14" />
                        <path d="m7 22-4-4 4-4" /><path d="M21 13v1a4 4 0 0 1-4 4H3" />
                      </svg>
                    </button>
                  </span>
                </div>
              </div>
            </div>
          </template>

          <!-- 其他候選：點了就換，並自動收合 -->
          <div v-if="openRow === g.key" class="alts">
            <button
              v-for="{ a, ai } in imageAlts(g)"
              :key="ai"
              type="button"
              :class="['alt', { selected: groupPick(g) === ai }]"
              @click="setGroupPick(g, ai); openRow = null"
            >
              <span class="alt-img">
                <img :src="a.product_image_url" :alt="a.name" />
              </span>
              <span class="alt-name" :title="a.name">{{ shortName(a.name) }}</span>
              <span class="alt-price">NT$ {{ a.price.toLocaleString() }}</span>
            </button>
          </div>
        </li>
      </ul>

      <!-- 找不到有圖的商品：只列預估價，不放圖 -->
      <template v-if="estimateGroups.length">
        <h3 class="sub-title">預估估價項目</h3>
        <ul class="est-list">
          <li v-for="g in estimateGroups" :key="g.key" class="est-row" :title="g.item.detected_name">
            <span class="est-cat">{{ categoryLabel(g.item) }}</span>
            <span class="est-name" :title="pickedOf(g).name">{{ shortName(pickedOf(g).name) }}</span>
            <span class="est-price">
              NT$ {{ pickedOf(g).price.toLocaleString() }}
              <small v-if="g.idxs.length > 1" class="qty">×{{ g.idxs.length }}</small>
            </span>
          </li>
        </ul>
      </template>
    </template>

    <p v-else-if="quotationLoading" class="hint" role="status">
      正在辨識畫面中的家具並比對 IKEA 商品…約需 30 秒
    </p>
    <p v-else class="hint">
      尚未取得報價，點右上角「取得家具報價」重試。
    </p>
  </section>
</template>

<style scoped>
.block-title {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  margin: 0;
  font-family: var(--db-font-display);
  font-style: italic;
  font-weight: 500;
  font-size: 1.3rem;
  color: var(--db-text);
}
.head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 1rem;
  margin-bottom: 0.5rem;
}
.head .db-btn, .refresh { margin-left: auto; }
.refresh {
  display: grid;
  place-items: center;
  width: 34px;
  height: 34px;
  border: none;
  border-radius: 50%;
  background: none;
  color: var(--db-text-soft);
  cursor: pointer;
  transition: background 0.16s, color 0.16s;
}
.refresh:hover:not(:disabled) { background: var(--db-chip-soft); color: var(--db-text); }
.refresh:disabled { opacity: 0.5; cursor: not-allowed; }

/* 家具清單：每件一行（選中的商品），其他候選按「換」才展開 */
.furn-list { margin: 0; padding: 0; list-style: none; }
.furn { padding: 0.4rem 0; border-bottom: 1px solid #f0f0f0; }
.furn:last-child { border-bottom: none; }
.furn-main { display: flex; align-items: center; gap: 0.75rem; }
.furn-thumb {
  display: grid;
  place-items: center;
  flex-shrink: 0;
  width: 76px;
  height: 76px;
  border-radius: 10px;
  background: var(--db-chip-soft);
  overflow: hidden;
}
.furn-thumb img { max-width: 100%; max-height: 100%; object-fit: contain; }
.sub-title { margin: 0.9rem 0 0.2rem; font-size: 0.8rem; font-weight: 600; color: var(--db-text-soft); letter-spacing: 0.04em; }
/* 預估估價：沒有商品圖，純文字一行一件 */
.est-list { margin: 0; padding: 0; list-style: none; }
.est-row {
  display: grid; grid-template-columns: auto 1fr auto; align-items: baseline; gap: 0.6rem;
  padding: 0.45rem 0; border-bottom: 1px solid #f0f0f0; font-size: 0.88rem;
}
.est-row:last-child { border-bottom: none; }
.est-cat { font-size: 0.74rem; color: var(--db-text-soft); }
.est-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--db-text-soft); }
.est-price { white-space: nowrap; }
.est-row .qty { font-size: 0.8rem; padding: 0.05rem 0.45rem; }
.furn-info { display: flex; flex-direction: column; gap: 0.15rem; flex: 1; min-width: 0; }
.furn-info .name { font-size: 0.92rem; }
.furn-cat { font-size: 0.74rem; color: var(--db-text-soft); letter-spacing: 0.04em; }
/* 價格在左、收藏／換款在右同一行，操作離資訊近、也看得到 */
.furn-foot { display: flex; align-items: center; justify-content: space-between; gap: 0.5rem; margin-top: 0.1rem; }
.est {
  margin-left: 0.4rem;
  padding: 0.05rem 0.4rem;
  border-radius: var(--db-radius-pill);
  background: var(--db-chip-soft);
  color: var(--db-text-soft);
  font-size: 0.68rem;
  font-weight: 400;
}
.furn-side { display: flex; align-items: center; gap: 0.5rem; flex-shrink: 0; }
.name--link { color: inherit; text-decoration: none; }
.name--link:hover { text-decoration: underline; text-underline-offset: 3px; }
.qty {
  margin-left: 0.5rem;
  padding: 0.1rem 0.6rem;
  border-radius: var(--db-radius-pill);
  background: var(--db-accent-ink);
  color: #fff;
  font-size: 1rem;
  font-weight: 600;
  line-height: 1.4;
}
/* 換一款：圓形「交換」圖示，跟旁邊的收藏星號同尺寸；展開候選時反白 */
.swap-btn svg { width: 20px; height: 20px; }
.swap-btn {
  display: grid;
  place-items: center;
  width: 40px;
  height: 40px;
  border: none;
  border-radius: 50%;
  background: none;
  color: var(--db-text-soft);
  cursor: pointer;
  transition: background 0.16s, color 0.16s;
}
.swap-btn:hover { background: var(--db-chip-soft); color: var(--db-text); }
.swap-btn.open { background: var(--db-accent-ink); color: #fff; }
.swap-btn:focus-visible { outline: 2px solid var(--db-text); outline-offset: 2px; }
.alts {
  display: flex;
  gap: 0.6rem;
  margin-top: 0.7rem;
  padding-bottom: 0.3rem;
  overflow-x: auto;
}
.alt {
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
  flex-shrink: 0;
  width: 112px;
  padding: 0.5rem;
  border: 2px solid #ececec;
  border-radius: var(--db-radius-chip);
  background: #fff;
  text-align: left;
  cursor: pointer;
  transition: border-color 0.16s;
}
.alt:hover { border-color: var(--db-accent-soft); }
.alt.selected { border-color: var(--db-accent); }
.alt-img {
  display: grid;
  place-items: center;
  height: 72px;
  border-radius: 6px;
  background: var(--db-chip-soft);
  overflow: hidden;
}
.alt-img img { max-width: 100%; max-height: 100%; object-fit: contain; }
.alt-name {
  font-size: 0.72rem;
  line-height: 1.35;
  color: var(--db-text);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.alt-price { font-size: 0.8rem; font-weight: 600; color: var(--db-text); }

.name {
  font-size: 0.82rem;
  line-height: 1.4;
  color: var(--db-text);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.price { font-size: 0.9rem; font-weight: 600; color: var(--db-text); }
.sim { font-size: 0.7rem; color: var(--db-placeholder); }

.fav {
  display: grid;
  place-items: center;
  width: 40px;
  height: 40px;
  border: none;
  border-radius: 50%;
  background: none;
  cursor: pointer;
  color: var(--db-text-soft);
  font-size: 1.75rem;
  line-height: 1;
  transition: background 0.16s, color 0.16s, transform 0.12s;
}
.fav:hover { background: var(--db-chip-soft); color: var(--db-text); }
.fav:active { transform: scale(0.9); }
.fav.active { color: var(--db-accent); }
.fav:focus-visible { outline: 2px solid var(--db-text); outline-offset: 2px; }

.total {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 0.85rem;
  padding: 0.75rem 0 0.6rem;
  border-bottom: 1px solid #f0f0f0;
}
.total-label { color: var(--db-text-soft); font-size: 0.9rem; }
.total-val {
  font-family: var(--db-font-display);
  font-style: normal;
  font-size: 1.6rem;
  color: var(--db-text);
  font-variant-numeric: tabular-nums;
}

.note, .hint {
  margin: 0.5rem 0 0;
  color: var(--db-placeholder);
  font-size: 0.8rem;
  line-height: 1.7;
}
.hint { padding: 2rem 0; text-align: center; font-size: 0.95rem; }
</style>
