<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { apiUrl } from '@/config/api'
import { useFurnitureSelection } from '@/composables/useFurnitureSelection'
import AppNav from '@/components/shell/AppNav.vue'
import sceneBg from '@/assets/figma/room-bg.png'

const { selectedCount, isSelected, toggle, clear } = useFurnitureSelection()

const categories = ref([])
const activeCategory = ref('')
const furniture = ref([])
const loading = ref(true)
const error = ref('')

const priceRanges = [
  { label: '全部價位', min: null, max: null },
  { label: '5,000 以下', min: null, max: 5000 },
  { label: '5,000–15,000', min: 5000, max: 15000 },
  { label: '15,000–30,000', min: 15000, max: 30000 },
  { label: '30,000 以上', min: 30000, max: null },
]
const priceIndex = ref(0)   // 下拉選單用 index，物件當 value 不好比對
const activePriceRange = computed(() => priceRanges[priceIndex.value])
const searchQuery = ref('')

// 品牌、風格選項（含件數）由後端依家具資料庫算出，風格名稱沿用生成流程的風格清單
const brands = ref([])
const styles = ref([])
const activeBrand = ref('')
const activeStyle = ref('')

const categoryLabels = {
  sofa: '沙發',
  table: '桌子',
  chair: '椅子',
  lamp: '燈具',
  rug: '地毯',
  storage: '收納',
  bed: '床',
}

async function fetchCategories() {
  try {
    const res = await fetch(apiUrl('/api/furniture/categories'))
    if (res.ok) categories.value = await res.json()
  } catch {}
}

async function fetchFilters() {
  try {
    const res = await fetch(apiUrl('/api/furniture/filters'))
    if (res.ok) ({ brands: brands.value, styles: styles.value } = await res.json())
  } catch {}
}

async function fetchFurniture() {
  loading.value = true
  error.value = ''
  try {
    const params = new URLSearchParams()
    if (activeCategory.value) params.set('category', activeCategory.value)
    if (activePriceRange.value.min != null) params.set('min_price', activePriceRange.value.min)
    if (activePriceRange.value.max != null) params.set('max_price', activePriceRange.value.max)
    if (activeBrand.value) params.set('brand', activeBrand.value)
    if (activeStyle.value) params.set('style', activeStyle.value)
    const qs = params.toString()
    const res = await fetch(apiUrl(`/api/furniture${qs ? `?${qs}` : ''}`))
    if (!res.ok) throw new Error(String(res.status))
    const data = await res.json()
    const kw = searchQuery.value.trim().toLowerCase()
    furniture.value = kw
      ? data.filter(item => (item.name || '').toLowerCase().includes(kw))
      : data
  } catch (e) {
    error.value = '無法載入家具清單'
  } finally {
    loading.value = false
  }
}

function selectCategory(cat) {
  activeCategory.value = cat
}

const hasExtraFilters = computed(() => priceIndex.value !== 0 || activeBrand.value || activeStyle.value)
function clearExtraFilters() {
  priceIndex.value = 0
  activeBrand.value = ''
  activeStyle.value = ''
}

watch([activeCategory, activePriceRange, activeBrand, activeStyle], fetchFurniture)

let searchTimer = null
watch(searchQuery, () => {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(fetchFurniture, 300)
})

onMounted(async () => {
  await Promise.all([fetchCategories(), fetchFilters()])
  await fetchFurniture()
})
</script>

<template>
  <div class="db-scene" :style="{ '--db-scene-image': `url(${sceneBg})` }">
    <AppNav />
    <div class="db-card furniture-page">
    <header class="furniture-header">
      <h1>家具查詢</h1>
      <div class="selected-summary">
        <button v-if="selectedCount" class="clear-btn" @click="clear">清除</button>
        <RouterLink to="/cart" class="db-btn db-btn--sm cart-link">
          ❤ 我的收藏（{{ selectedCount }}）
        </RouterLink>
      </div>
    </header>

    <div class="toolbar">
      <div class="search-bar">
        <svg class="search-icon" xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
          <circle cx="11" cy="11" r="7"/>
          <line x1="21" y1="21" x2="16.65" y2="16.65"/>
        </svg>
        <input
          v-model="searchQuery"
          type="text"
          class="search-input"
          placeholder="輸入關鍵字搜尋家具名稱…"
        />
        <button v-if="searchQuery" class="search-clear" @click="searchQuery = ''">✕</button>
      </div>
      <div class="filter-selects">
        <select v-model.number="priceIndex" :class="['filter-select', { active: priceIndex !== 0 }]" aria-label="價位">
          <option v-for="(range, idx) in priceRanges" :key="range.label" :value="idx">
            {{ idx === 0 ? '價位' : range.label }}
          </option>
        </select>
        <select v-model="activeBrand" :class="['filter-select', { active: activeBrand }]" aria-label="品牌">
          <option value="">品牌</option>
          <option v-for="b in brands" :key="b.value" :value="b.value">{{ b.label }}（{{ b.count.toLocaleString() }}）</option>
        </select>
        <select v-model="activeStyle" :class="['filter-select', { active: activeStyle }]" aria-label="風格">
          <option value="">風格</option>
          <option v-for="st in styles" :key="st.value" :value="st.value">{{ st.label }}</option>
        </select>
        <button v-if="hasExtraFilters" type="button" class="clear-filters" @click="clearExtraFilters">清除篩選</button>
      </div>
    </div>

    <div class="category-tabs">
      <button
        :class="['cat-tab', { active: activeCategory === '' }]"
        @click="selectCategory('')"
      >
        全部
      </button>
      <button
        v-for="cat in categories"
        :key="cat"
        :class="['cat-tab', { active: activeCategory === cat }]"
        @click="selectCategory(cat)"
      >
        {{ categoryLabels[cat] || cat }}
      </button>
    </div>

    <div v-if="loading" class="state-msg">載入中…</div>
    <div v-else-if="error" class="state-msg error">{{ error }}</div>
    <div v-else-if="furniture.length === 0" class="state-msg">沒有符合條件的家具</div>
    <p v-else class="result-count">共 {{ furniture.length.toLocaleString() }} 件</p>

    <div v-if="!loading && !error && furniture.length" class="grid">
      <div
        v-for="item in furniture"
        :key="item.id || item.url"
        :class="['card', { checked: isSelected(item) }]"
        @click="toggle(item)"
      >
        <div class="card-img-wrap">
          <img
            v-if="item.image_url"
            :src="item.image_url"
            :alt="item.name"
            class="card-img"
            loading="lazy"
            @error="$event.target.style.display='none'"
          />
          <div v-else class="card-no-img">無圖</div>
          <span :class="['check-icon', { checked: isSelected(item) }]">
            {{ isSelected(item) ? '✓' : '' }}
          </span>
        </div>
        <div class="card-body">
          <span v-if="item.brand" class="card-brand">{{ item.brand }}</span>
          <p class="card-name">{{ item.name }}</p>
          <p class="card-price">{{ item.currency || 'TWD' }} {{ Number(item.price || 0).toLocaleString() }}</p>
          <div class="card-actions">
            <a
              v-if="item.url"
              :href="item.url"
              target="_blank"
              rel="noopener"
              class="detail-link"
              @click.stop
            >查看詳情</a>
            <button
              :class="['favorite-btn', { favorited: isSelected(item) }]"
              :title="isSelected(item) ? '取消收藏' : '加入收藏'"
              @click.stop="toggle(item)"
            >
              {{ isSelected(item) ? '✓ 已收藏' : '加入收藏' }}
            </button>
          </div>
        </div>
      </div>
    </div>
    </div>
  </div>
</template>

<style scoped>
.furniture-page { margin: 1.25rem auto 3rem; padding: 1.75rem 1.5rem 3rem; }

.furniture-header { display: flex; align-items: center; justify-content: space-between; gap: 1rem; margin-bottom: 1.25rem; }
.furniture-header h1 {
  margin: 0; font-family: var(--db-font-display); font-style: italic; font-weight: 500;
  font-size: 1.6rem; color: var(--db-text);
}
.selected-summary { display: flex; align-items: center; gap: 0.6rem; }
.cart-link { text-decoration: none; }
.clear-btn { border: 0; background: none; padding: 0 0.4rem; font-size: 0.82rem; color: var(--db-text-soft); cursor: pointer; text-decoration: underline; }
.clear-btn:hover { color: var(--db-danger); }

.toolbar { display: flex; flex-wrap: wrap; align-items: center; gap: 0.6rem 0.75rem; margin-bottom: 1rem; }
.search-bar { position: relative; flex: 1 1 260px; max-width: 420px; }
.filter-selects { display: flex; flex-wrap: wrap; align-items: center; gap: 0.5rem; }
.filter-select {
  appearance: none; padding: 0.45rem 2rem 0.45rem 0.9rem; border: 1px solid #d8d4cb; border-radius: var(--db-radius-pill);
  background: #fff url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='6' viewBox='0 0 10 6'%3E%3Cpath d='M1 1l4 4 4-4' fill='none' stroke='%23888' stroke-width='1.5'/%3E%3C/svg%3E") no-repeat right 0.8rem center;
  color: var(--db-text); font-size: 0.85rem; font-family: inherit; cursor: pointer;
}
.filter-select:focus-visible { outline: none; border-color: var(--db-accent-deep); box-shadow: 0 0 0 3px var(--db-accent-soft); }
.filter-select.active { border-color: var(--db-accent-deep); background-color: var(--db-accent-soft); }
.clear-filters { border: 0; background: none; padding: 0 0.25rem; font-size: 0.8rem; color: var(--db-text-soft); text-decoration: underline; cursor: pointer; }
.clear-filters:hover { color: var(--db-danger); }
/* 窄螢幕：三個下拉平分同一行，不要各佔一層 */
@media (max-width: 560px) {
  .filter-selects { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); width: 100%; }
  .filter-select { width: 100%; min-width: 0; padding: 0.42rem 1.5rem 0.42rem 0.7rem; background-position: right 0.55rem center; font-size: 0.8rem; text-overflow: ellipsis; }
  .clear-filters { grid-column: 1 / -1; justify-self: start; }
}
.search-icon { position: absolute; top: 50%; left: 0.9rem; transform: translateY(-50%); color: var(--db-text-soft); pointer-events: none; }
.search-input {
  width: 100%; box-sizing: border-box; padding: 0.55rem 2.2rem 0.55rem 2.5rem;
  border: 1px solid #d8d4cb; border-radius: var(--db-radius-pill); background: #fff;
  color: var(--db-text); font-size: 0.88rem; font-family: inherit; outline: none;
  transition: border-color 0.15s, box-shadow 0.15s;
}
.search-input::placeholder { color: var(--db-placeholder); }
.search-input:focus { border-color: var(--db-accent-deep); box-shadow: 0 0 0 3px var(--db-accent-soft); }
.search-clear {
  position: absolute; top: 50%; right: 0.75rem; transform: translateY(-50%);
  background: none; border: none; color: var(--db-text-soft); cursor: pointer; font-size: 0.75rem; padding: 0.2rem; line-height: 1;
}
.search-clear:hover { color: var(--db-danger); }

.category-tabs { display: flex; gap: 0.5rem; flex-wrap: wrap; margin-bottom: 0.85rem; }
.cat-tab {
  padding: 0.35rem 1rem; border: 1px solid #d8d4cb; border-radius: var(--db-radius-pill);
  background: #fff; color: var(--db-text); font-size: 0.88rem; cursor: pointer;
}
.cat-tab:hover:not(.active) { background: var(--db-chip-soft); }
.cat-tab.active { background: var(--db-accent); border-color: var(--db-accent); color: var(--db-on-accent); }

.result-count { margin: 0.25rem 0 0; font-size: 0.8rem; color: var(--db-text-soft); }
.card-brand { align-self: flex-start; padding: 0.05rem 0.5rem; border-radius: var(--db-radius-pill); background: var(--db-chip-soft); font-size: 0.7rem; color: var(--db-text-soft); }

.state-msg { text-align: center; color: var(--db-text-soft); padding: 3rem; }
.state-msg.error { color: var(--db-danger); }

.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(min(220px, 100%), 1fr)); gap: 1.25rem; margin-top: 1.25rem; }

.card {
  background: #fff; border: 1px solid #ececec; border-radius: var(--db-radius-chip);
  overflow: hidden; cursor: pointer; transition: transform 0.16s, box-shadow 0.16s, border-color 0.16s;
}
.card:hover { transform: translateY(-3px); box-shadow: var(--db-shadow-soft); border-color: var(--db-accent); }
.card.checked { border-color: var(--db-accent-ink); }

.card-img-wrap { position: relative; aspect-ratio: 1 / 1; background: var(--db-chip-soft); overflow: hidden; }
.card-img { width: 100%; height: 100%; object-fit: cover; display: block; }
.card-no-img { display: grid; place-items: center; width: 100%; height: 100%; color: var(--db-placeholder); font-size: 0.8rem; }

.check-icon {
  position: absolute; top: 10px; right: 10px; display: grid; place-items: center; width: 24px; height: 24px;
  border-radius: 50%; border: 2px solid #fff; background: rgba(255, 255, 255, 0.7);
  font-size: 0.78rem; font-weight: 700; color: #fff; box-shadow: 0 1px 4px rgba(0, 0, 0, 0.2);
}
.check-icon.checked { background: var(--db-accent-ink); border-color: var(--db-accent-ink); }

.card-body { padding: 0.8rem 1rem 1rem; display: flex; flex-direction: column; gap: 0.3rem; }
.card-name {
  font-size: 0.88rem; color: var(--db-text); margin: 0; line-height: 1.4;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;
}
.card-price { font-size: 0.92rem; color: var(--db-text); font-weight: 600; margin: 0; font-variant-numeric: tabular-nums; }

.card-actions { display: flex; align-items: center; justify-content: space-between; gap: 0.5rem; margin-top: 0.3rem; }
.detail-link { font-size: 0.78rem; color: var(--db-accent-ink); text-decoration: underline; }
.detail-link:hover { color: var(--db-text); }

.favorite-btn {
  margin-left: auto; padding: 0.28rem 0.85rem; border: 1px solid #d8d4cb; border-radius: var(--db-radius-pill);
  background: #fff; color: var(--db-text); font-size: 0.78rem; cursor: pointer; transition: background 0.15s;
}
.favorite-btn:hover { background: var(--db-chip-soft); }
.favorite-btn.favorited { background: var(--db-accent); border-color: var(--db-accent); color: var(--db-on-accent); }
</style>
