<script setup>
/**
 * Step 預算估計 — Figma MacBook Air - 20
 *
 * 設計稿只畫了一張商品清單。實際功能比那多：要先按鈕觸發估價（跑約 30 秒，不放進
 * 自動流程），每件家具有多個候選可切換、可收藏、可開商品頁，總預算跟著選擇即時算。
 * 這些全部保留。
 */
import { computed, reactive, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { useDesignFlow } from '@/composables/useDesignFlow'
import { useFurnitureSelection } from '@/composables/useFurnitureSelection'

const {
  result, quotationLoading, quotationError, fetchQuotation, prevStep, resetFlow,
  favoriteLoading, favoriteError, toggleFavoriteDesign,
} = useDesignFlow()
const {
  selectedCount: furnitureSelectedCount,
  toggle: toggleFavorite,
  isSelected: isFavorited,
} = useFurnitureSelection()

const quotation = computed(() => result.value?.quotation_result || null)

// 每件家具目前選中的候選 index
const selectedCandidates = reactive({})
watch(
  () => quotation.value?.furniture_list,
  (list) => { if (list) list.forEach((_, idx) => { selectedCandidates[idx] = 0 }) },
  { immediate: true },
)

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
  <div class="budget-step">
    <div class="head">
      <h2 class="title">
        根據設計方案，進行家具推薦
        <span class="badge">IKEA 台灣</span>
      </h2>
      <div class="head-actions">
        <RouterLink to="/furniture" class="link">
          前往家具查詢
          <span v-if="furnitureSelectedCount" class="count">{{ furnitureSelectedCount }}</span>
        </RouterLink>
        <button class="db-btn db-btn--sm" :disabled="quotationLoading" @click="fetchQuotation">
          {{ quotationLoading ? '估價中…' : (quotation ? '重新估價' : '取得家具報價') }}
        </button>
      </div>
    </div>

    <p v-if="quotationError" class="db-error">{{ quotationError }}</p>

    <template v-if="quotation">
      <div v-for="(item, idx) in quotation.furniture_list" :key="idx" class="row">
        <div class="row-label">{{ item.detected_name }}</div>
        <div class="candidates">
          <button
            v-for="(c, ci) in item.candidates"
            :key="ci"
            type="button"
            :class="['candidate', { selected: (selectedCandidates[idx] ?? 0) === ci }]"
            @click="selectedCandidates[idx] = ci"
          >
            <span class="img-wrap">
              <img v-if="c.product_image_url" :src="c.product_image_url" :alt="c.name" />
              <span v-else class="img-placeholder">資料庫沒有該項商品</span>
            </span>
            <span class="name">{{ c.name }}</span>
            <span class="price">NT$ {{ c.price.toLocaleString() }}</span>
            <span v-if="c.similarity > 0" class="sim">相似度 {{ (c.similarity * 100).toFixed(0) }}%</span>
            <span class="card-actions">
              <a
                v-if="c.purchase_url" :href="c.purchase_url"
                target="_blank" rel="noopener" class="buy" @click.stop
              >商品詳情</a>
              <span
                class="fav"
                :class="{ active: isFavorited(toFavoriteItem(item, c)) }"
                :title="isFavorited(toFavoriteItem(item, c)) ? '取消收藏' : '加入收藏'"
                @click.stop="toggleFavorite(toFavoriteItem(item, c))"
              >{{ isFavorited(toFavoriteItem(item, c)) ? '★' : '☆' }}</span>
            </span>
          </button>
        </div>
      </div>

      <div class="total">
        <span class="total-label">目前選擇預算</span>
        <span class="total-val">NT$ {{ computedTotal.toLocaleString() }}</span>
      </div>

      <p class="note">
        * 點選卡片可切換商品，總預算自動更新。{{ quotation.kb_match_count }}/{{ quotation.furniture_list.length }}
        件成功向量比對 IKEA，其餘為 AI 估算。
      </p>
    </template>

    <p v-else-if="!quotationLoading" class="hint">
      點擊「取得家具報價」辨識畫面中的家具並推薦 IKEA 商品（約需 30 秒）。
    </p>

    <!-- 整個流程走完，最後留一個收藏這次設計的地方——它其實一直都在
         歷史紀錄裡（每次生成都自動存檔），收藏只是標記起來、之後在
         歷史紀錄好找，也不怕被批次刪除誤刪。 -->
    <div v-if="result?.task_id" class="collect-row">
      <button
        type="button"
        :class="['collect-btn', { active: result.favorited }]"
        :disabled="favoriteLoading"
        @click="toggleFavoriteDesign()"
      >
        <span class="collect-star">{{ result.favorited ? '★' : '☆' }}</span>
        {{ result.favorited ? '已收藏這個設計' : '收藏這個設計' }}
      </button>
      <RouterLink to="/history" class="collect-link">在歷史紀錄查看 →</RouterLink>
      <p v-if="favoriteError" class="db-error collect-error">{{ favoriteError }}</p>
    </div>

    <div class="actions">
      <button class="db-btn db-btn--ghost db-btn--sm" @click="prevStep">← 回微調編輯</button>
      <button class="db-btn db-btn--ghost db-btn--sm" @click="resetFlow">開始新的設計</button>
    </div>
  </div>
</template>

<style scoped>
.budget-step { display: flex; flex-direction: column; }

.head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 1rem;
  margin-bottom: 1.25rem;
}
.title {
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
.badge {
  padding: 0.15rem 0.6rem;
  border-radius: var(--db-radius-pill);
  background: var(--db-accent);
  color: var(--db-on-accent);
  font-family: var(--db-font-body);
  font-style: normal;
  font-size: 0.72rem;
}

.head-actions {
  display: flex;
  align-items: center;
  gap: 0.85rem;
  margin-left: auto;
}
.link {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  color: var(--db-text-soft);
  font-size: 0.9rem;
  text-decoration: none;
}
.link:hover { color: var(--db-text); }
.count {
  display: inline-grid;
  place-items: center;
  min-width: 18px; height: 18px;
  padding: 0 5px;
  border-radius: var(--db-radius-pill);
  background: var(--db-accent);
  color: var(--db-on-accent);
  font-size: 0.68rem;
}

.row {
  display: grid;
  grid-template-columns: 120px 1fr;
  gap: 1rem;
  align-items: start;
  padding: 1rem 0;
  border-bottom: 1px solid #f0f0f0;
}
.row-label {
  font-family: var(--db-font-display);
  font-style: italic;
  font-size: 1.05rem;
  color: var(--db-text);
}

.candidates {
  display: flex;
  gap: 0.85rem;
  overflow-x: auto;
  padding-bottom: 0.4rem;
}

.candidate {
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
  flex-shrink: 0;
  width: 168px;
  padding: 0.65rem;
  border: 2px solid #ececec;
  border-radius: var(--db-radius-chip);
  background: #fff;
  text-align: left;
  cursor: pointer;
  transition: border-color 0.16s, box-shadow 0.16s;
}
.candidate:hover { border-color: var(--db-accent-soft); }
.candidate.selected {
  border-color: var(--db-accent);
  box-shadow: var(--db-shadow-soft);
}

.img-wrap {
  display: grid;
  place-items: center;
  height: 104px;
  border-radius: 6px;
  background: var(--db-chip-soft);
  overflow: hidden;
}
.img-wrap img { max-width: 100%; max-height: 100%; object-fit: contain; }
.img-placeholder {
  padding: 0 0.5rem;
  color: var(--db-placeholder);
  font-size: 0.72rem;
  text-align: center;
}

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

.card-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 0.25rem;
}
.buy {
  color: var(--db-accent-deep);
  font-size: 0.75rem;
  text-decoration: underline;
}
.fav { cursor: pointer; color: var(--db-placeholder); font-size: 1.05rem; line-height: 1; }
.fav.active { color: var(--db-accent); }

.total {
  display: flex;
  align-items: baseline;
  justify-content: flex-end;
  gap: 0.85rem;
  padding: 1.25rem 0 0.5rem;
}
.total-label { color: var(--db-text-soft); font-size: 0.9rem; }
.total-val {
  font-family: var(--db-font-display);
  font-style: italic;
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

.collect-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: center;
  gap: 1rem;
  margin-top: 1.5rem;
  padding: 1.1rem 1.25rem;
  border-radius: var(--db-radius-chip);
  background: var(--db-chip-soft);
}
.collect-btn {
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.55rem 1.3rem;
  border: 2px solid var(--db-accent);
  border-radius: var(--db-radius-pill);
  background: #fff;
  color: var(--db-text);
  font-family: var(--db-font-display);
  font-style: italic;
  font-weight: 500;
  font-size: 1rem;
  cursor: pointer;
  transition: background 0.16s, color 0.16s;
}
.collect-btn:hover:not(:disabled) { background: var(--db-accent-soft); }
.collect-btn.active {
  background: var(--db-accent);
  color: var(--db-on-accent);
}
.collect-btn:disabled { opacity: 0.6; cursor: not-allowed; }
.collect-star { font-size: 1.15rem; line-height: 1; }
.collect-link {
  color: var(--db-accent-deep);
  font-size: 0.88rem;
  text-decoration: underline;
  text-underline-offset: 3px;
}
.collect-error { margin: 0; width: 100%; text-align: center; }

.actions {
  display: flex;
  justify-content: center;
  gap: 1rem;
  padding-top: 1.75rem;
}

@media (max-width: 900px) {
  .head-actions { margin-left: 0; }
  .row { grid-template-columns: 1fr; }
  .actions { flex-direction: column; }
  .actions .db-btn { width: 100%; }
}
</style>
