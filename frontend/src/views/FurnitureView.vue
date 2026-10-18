<script setup>
import { ref, onMounted, watch } from 'vue'
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
const activePriceRange = ref(priceRanges[0])
const searchQuery = ref('')

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

async function fetchFurniture() {
  loading.value = true
  error.value = ''
  try {
    const params = new URLSearchParams()
    if (activeCategory.value) params.set('category', activeCategory.value)
    if (activePriceRange.value.min != null) params.set('min_price', activePriceRange.value.min)
    if (activePriceRange.value.max != null) params.set('max_price', activePriceRange.value.max)
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

function selectPriceRange(range) {
  activePriceRange.value = range
}

watch([activeCategory, activePriceRange], fetchFurniture)

let searchTimer = null
watch(searchQuery, () => {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(fetchFurniture, 300)
})

onMounted(async () => {
  await fetchCategories()
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

    <div class="price-tabs">
      <button
        v-for="range in priceRanges"
        :key="range.label"
        :class="['price-tab', { active: activePriceRange.label === range.label }]"
        @click="selectPriceRange(range)"
      >
        {{ range.label }}
      </button>
    </div>

    <div v-if="loading" class="state-msg">載入中…</div>
    <div v-else-if="error" class="state-msg error">{{ error }}</div>
    <div v-else-if="furniture.length === 0" class="state-msg">此分類尚無家具</div>

    <div v-else class="grid">
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

.search-bar { position: relative; margin-bottom: 1rem; max-width: 420px; }
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

.category-tabs, .price-tabs { display: flex; gap: 0.5rem; flex-wrap: wrap; margin-bottom: 0.85rem; }
.cat-tab, .price-tab {
  padding: 0.35rem 1rem; border: 1px solid #d8d4cb; border-radius: var(--db-radius-pill);
  background: #fff; color: var(--db-text); font-size: 0.88rem; cursor: pointer;
}
.price-tab { padding: 0.25rem 0.8rem; font-size: 0.82rem; color: var(--db-text-soft); }
.cat-tab:hover:not(.active), .price-tab:hover:not(.active) { background: var(--db-chip-soft); }
.cat-tab.active, .price-tab.active { background: var(--db-accent); border-color: var(--db-accent); color: var(--db-on-accent); }

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
