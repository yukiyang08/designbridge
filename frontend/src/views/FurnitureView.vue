<script setup>
import { ref, onMounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { apiUrl } from '@/config/api'
import { useFurnitureSelection } from '@/composables/useFurnitureSelection'

const router = useRouter()
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

function goHome() {
  router.push('/')
}
</script>

<template>
  <div class="furniture-page">
    <header class="furniture-header">
      <button class="back-btn" @click="goHome">← 返回</button>
      <h1>家具查詢</h1>
      <div class="selected-summary">
        <RouterLink to="/cart" class="cart-link">
          ❤ 我的收藏（{{ selectedCount }}）
        </RouterLink>
        <button v-if="selectedCount" class="clear-btn" @click="clear">清除</button>
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
</template>

<style scoped>
.furniture-page { max-width: 1400px; margin: 0 auto; padding: 1.5rem; font-family: sans-serif; }

.furniture-header { display: flex; align-items: center; gap: 1rem; margin-bottom: 1rem; }
.furniture-header h1 { font-size: 1.3rem; margin: 0; }
.back-btn { background: none; border: 1px solid #999; border-radius: 6px; padding: 0.3rem 0.8rem; cursor: pointer; font-size: 0.88rem; color: #333; font-weight: 600; }
.back-btn:hover { background: #eee; border-color: #666; }

.selected-summary { margin-left: auto; display: flex; align-items: center; gap: 0.6rem; font-size: 0.85rem; color: #5c3d24; font-weight: 600; }
.cart-link {
  color: #fff;
  text-decoration: none;
  padding: 0.3rem 0.8rem;
  border-radius: 999px;
  background: linear-gradient(135deg, #756d66 0%, #b07845 100%);
  font-weight: 700;
}
.cart-link:hover { opacity: 0.9; }
.clear-btn { background: none; border: 1px solid #ccc; border-radius: 6px; padding: 0.25rem 0.7rem; font-size: 0.78rem; cursor: pointer; color: #555; }
.clear-btn:hover { background: #f0f0f0; }

.category-tabs { display: flex; gap: 0.5rem; flex-wrap: wrap; margin-bottom: 0.85rem; }
.cat-tab { padding: 0.35rem 0.9rem; border: 1.5px solid #d8d8d8; border-radius: 999px; background: transparent; color: #444; font-size: 0.82rem; font-weight: 600; cursor: pointer; }
.cat-tab:hover:not(.active) { background: #f5f5f5; }
.cat-tab.active { background: linear-gradient(135deg, #756d66 0%, #b07845 100%); border-color: transparent; color: #fff; }

.price-tabs { display: flex; gap: 0.5rem; flex-wrap: wrap; margin-bottom: 0.85rem; }
.price-tab { padding: 0.3rem 0.8rem; border: 1.5px solid #d8c8b8; border-radius: 999px; background: #fffaf5; color: #6b4a28; font-size: 0.78rem; font-weight: 600; cursor: pointer; }
.price-tab:hover:not(.active) { background: #fff0d8; }
.price-tab.active { background: #5c3d24; border-color: transparent; color: #fff; }

.search-bar { position: relative; margin-bottom: 1rem; max-width: 420px; }
.search-icon {
  position: absolute;
  top: 50%;
  left: 0.85rem;
  transform: translateY(-50%);
  color: #a88a6a;
  pointer-events: none;
}
.search-input {
  width: 100%;
  box-sizing: border-box;
  padding: 0.5rem 2.2rem 0.5rem 2.4rem;
  border: 1.5px solid #d8c8b8;
  border-radius: 999px;
  background: #fffaf5;
  color: #5c3d24;
  font-size: 0.85rem;
  font-family: inherit;
  outline: none;
  transition: border-color 0.15s, box-shadow 0.15s;
}
.search-input::placeholder { color: #b39a80; }
.search-input:focus { border-color: #756d66; box-shadow: 0 0 0 2px rgba(117, 109, 102,0.15); }
.search-clear {
  position: absolute;
  top: 50%;
  right: 0.7rem;
  transform: translateY(-50%);
  background: none;
  border: none;
  color: #a88a6a;
  cursor: pointer;
  font-size: 0.75rem;
  padding: 0.2rem;
  line-height: 1;
}
.search-clear:hover { color: #c00; }

.state-msg { text-align: center; color: #888; padding: 3rem; }
.state-msg.error { color: #c00; }

.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 0.75rem; }

.card { border: 1px solid #e8ddd0; border-radius: 10px; overflow: hidden; cursor: pointer; background: #fffaf5; transition: box-shadow 0.15s, border-color 0.15s; }
.card:hover { box-shadow: 0 4px 18px rgba(117, 109, 102,0.18); border-color: #c9c4bb; }
.card.checked { border-color: #756d66; box-shadow: 0 0 0 2px #c9c4bb; }

.card-img-wrap { position: relative; aspect-ratio: 1/1; background: #f5f5f5; overflow: hidden; }
.card-img { width: 100%; height: 100%; object-fit: cover; display: block; }
.card-no-img { display: flex; align-items: center; justify-content: center; width: 100%; height: 100%; color: #bbb; font-size: 0.78rem; }

.check-icon { position: absolute; top: 6px; right: 6px; display: flex; align-items: center; justify-content: center; width: 22px; height: 22px; border-radius: 50%; border: 2px solid #fff; background: rgba(255,255,255,0.7); font-size: 0.75rem; font-weight: 700; color: #fff; box-shadow: 0 1px 4px rgba(0,0,0,0.2); }
.check-icon.checked { background: #756d66; border-color: #756d66; }

.card-body { padding: 0.5rem 0.6rem; }
.card-name { font-size: 0.76rem; color: #222; margin: 0 0 0.2rem; line-height: 1.35;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.card-price { font-size: 0.78rem; color: #8a5500; font-weight: 700; margin: 0; }

.card-actions { display: flex; flex-direction: column; gap: 0.3rem; margin-top: 0.4rem; }
.detail-link {
  text-align: center;
  font-size: 0.7rem;
  font-weight: 600;
  color: #0058a3;
  text-decoration: none;
}
.detail-link:hover { text-decoration: underline; }

.favorite-btn {
  width: 100%;
  padding: 0.32rem 0;
  border: 1.5px solid #c9c4bb;
  border-radius: 999px;
  background: #fff;
  color: #756d66;
  font-size: 0.72rem;
  font-weight: 700;
  cursor: pointer;
  transition: background 0.15s, color 0.15s, border-color 0.15s;
}
.favorite-btn:hover { background: #fff0d8; }
.favorite-btn.favorited {
  background: linear-gradient(135deg, #756d66 0%, #b07845 100%);
  border-color: transparent;
  color: #fff;
}
</style>
