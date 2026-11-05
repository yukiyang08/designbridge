<script setup>
import { Icon } from '@iconify/vue'
import { ref, computed, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useFurnitureSelection } from '@/composables/useFurnitureSelection'

const router = useRouter()
const { selectedFurniture, selectedCount, remove, clear } = useFurnitureSelection()

const categoryLabels = {
  sofa: '沙發',
  table: '桌子',
  chair: '椅子',
  lamp: '燈具',
  rug: '地毯',
  storage: '收納',
  bed: '床',
  curtain: '窗簾',
  decor: '軟裝',
}

function itemKey(item) {
  return item.id || item.url || `${item.name}__${item.category}`
}

const checkedKeys = ref(new Set())
const knownKeys = ref(new Set())

function isChecked(item) {
  return checkedKeys.value.has(itemKey(item))
}

function toggleCheck(item) {
  const key = itemKey(item)
  const next = new Set(checkedKeys.value)
  if (next.has(key)) next.delete(key)
  else next.add(key)
  checkedKeys.value = next
}

watch(
  selectedFurniture,
  (items) => {
    const nextChecked = new Set()
    const nextKnown = new Set()
    for (const item of items) {
      const k = itemKey(item)
      nextKnown.add(k)
      if (knownKeys.value.has(k)) {
        if (checkedKeys.value.has(k)) nextChecked.add(k)
      } else {
        nextChecked.add(k)
      }
    }
    checkedKeys.value = nextChecked
    knownKeys.value = nextKnown
  },
  { immediate: true, deep: true }
)

const checkedCount = computed(() => checkedKeys.value.size)
const total = computed(() =>
  selectedFurniture.value
    .filter(isChecked)
    .reduce((sum, item) => sum + Number(item.price || 0), 0)
)

function goFurniture() {
  router.push('/furniture')
}

function goHome() {
  router.push('/')
}
</script>

<template>
  <div class="cart-page">
    <header class="cart-header">
      <button class="back-btn" @click="goFurniture">← 繼續查詢</button>
      <h1>我的收藏</h1>
      <div class="header-actions">
        <button v-if="selectedCount" class="clear-btn" @click="clear">清空</button>
        <button class="done-btn" @click="goHome">完成</button>
      </div>
    </header>

    <p class="local-note">登入後收藏會同步到你的帳號；未登入時只存在這台裝置的瀏覽器。</p>

    <div v-if="selectedCount === 0" class="empty-state">
      <p>收藏清單是空的</p>
      <button class="browse-btn" @click="goFurniture">前往家具查詢挑選</button>
    </div>

    <div v-else class="cart-body">
      <div class="grid">
        <div
          v-for="item in selectedFurniture"
          :key="itemKey(item)"
          :class="['card', { checked: isChecked(item) }]"
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
            <button class="remove-badge" title="移除" aria-label="移除" @click.stop="remove(item)"><Icon icon="mdi:close" aria-hidden="true" /></button>
          </div>
          <div class="card-body">
            <p class="card-name">{{ item.name }}</p>
            <span class="card-category">{{ categoryLabels[item.category] || item.category }}</span>
            <p class="card-price">{{ item.currency || 'TWD' }} {{ Number(item.price || 0).toLocaleString() }}</p>
            <div class="card-actions">
              <a
                v-if="item.url"
                :href="item.url"
                target="_blank"
                rel="noopener"
                class="detail-link"
              >查看詳情</a>
              <label class="check-total">
                <input
                  type="checkbox"
                  :checked="isChecked(item)"
                  @change="toggleCheck(item)"
                />
                計入總價
              </label>
            </div>
          </div>
        </div>
      </div>

      <div class="cart-summary">
        <span class="summary-label">共 {{ selectedCount }} 件（已勾選 {{ checkedCount }} 件計價）</span>
        <span class="summary-total">總計 NT$ {{ total.toLocaleString() }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.cart-page { max-width: 1400px; margin: 0 auto; padding: 1.5rem; font-family: sans-serif; }

.cart-header { display: flex; align-items: center; gap: 1rem; margin-bottom: 1.25rem; }
.cart-header h1 { font-size: 1.3rem; margin: 0; }
.local-note { margin: 0 0 1rem; font-size: 0.85rem; color: var(--db-text-soft); }
.back-btn { background: none; border: 1px solid var(--db-line-strong); border-radius: 6px; padding: 0.3rem 0.8rem; cursor: pointer; font-size: 0.88rem; color: #333; font-weight: 600; }
.back-btn:hover { background: var(--db-accent-soft); border-color: var(--db-accent-ink); }

.header-actions { margin-left: auto; display: flex; align-items: center; gap: 0.6rem; }
.clear-btn { background: none; border: 1px solid var(--db-line-strong); border-radius: 6px; padding: 0.3rem 0.8rem; font-size: 0.8rem; cursor: pointer; color: #555; }
.clear-btn:hover { background: var(--db-accent-soft); }
.done-btn { background: linear-gradient(135deg, var(--db-accent-ink) 0%, #b07845 100%); color: #fff; border: none; border-radius: 6px; padding: 0.4rem 1rem; font-size: 0.85rem; font-weight: 700; cursor: pointer; }
.done-btn:hover { opacity: 0.9; }

.empty-state { text-align: center; padding: 4rem 1rem; color: var(--db-text-soft); }
.browse-btn {
  margin-top: 1rem;
  background: linear-gradient(135deg, var(--db-accent-ink) 0%, #b07845 100%);
  color: #fff; border: none; border-radius: 8px;
  padding: 0.55rem 1.4rem; font-size: 0.85rem; font-weight: 700; cursor: pointer;
}
.browse-btn:hover { opacity: 0.9; }

.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 0.75rem; }

.card { border: 1px solid #e8ddd0; border-radius: 10px; overflow: hidden; background: #fffaf5; transition: box-shadow 0.15s, border-color 0.15s; }
.card:hover { box-shadow: 0 4px 18px rgba(117, 109, 102,0.18); border-color: var(--db-accent); }
.card.checked { border-color: var(--db-accent-ink); box-shadow: 0 0 0 2px var(--db-accent); }

.card-img-wrap { position: relative; aspect-ratio: 1/1; background: var(--db-chip-soft); overflow: hidden; }
.card-img { width: 100%; height: 100%; object-fit: cover; display: block; }
.card-no-img { display: flex; align-items: center; justify-content: center; width: 100%; height: 100%; color: var(--db-placeholder); font-size: 0.78rem; }

.remove-badge {
  position: absolute; top: 6px; right: 6px;
  width: 22px; height: 22px; border-radius: 50%;
  border: none; background: rgba(0,0,0,0.55); color: #fff;
  font-size: 0.7rem; font-weight: 700; cursor: pointer;
  display: flex; align-items: center; justify-content: center;
}
.remove-badge:hover { background: var(--db-danger); }

.card-body { padding: 0.5rem 0.6rem; display: flex; flex-direction: column; gap: 0.2rem; }
.card-name { font-size: 0.76rem; color: var(--db-text); margin: 0; line-height: 1.35;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.card-category {
  font-size: 0.65rem; color: #8a5a00; background: #fff0d8;
  padding: 0.05rem 0.45rem; border-radius: 999px; font-weight: 600;
  width: fit-content;
}
.card-price { font-size: 0.78rem; color: #8a5500; font-weight: 700; margin: 0; }

.card-actions { display: flex; flex-direction: column; gap: 0.35rem; margin-top: 0.3rem; }
.detail-link {
  text-align: center;
  font-size: 0.7rem;
  font-weight: 600;
  color: #0058a3;
  text-decoration: none;
}
.detail-link:hover { text-decoration: underline; }

.check-total {
  display: flex; align-items: center; gap: 0.35rem;
  font-size: 0.7rem; color: #6b4a28; font-weight: 600; cursor: pointer;
}
.check-total input { accent-color: var(--db-accent-ink); cursor: pointer; }

.cart-summary {
  display: flex; justify-content: space-between; align-items: center;
  margin-top: 1.25rem; padding: 0.9rem 1.1rem;
  background: #fff0d8; border-radius: 10px;
}
.summary-label { font-size: 0.85rem; color: #6b4a28; font-weight: 600; }
.summary-total { font-size: 1.05rem; color: #5c3d24; font-weight: 800; }
</style>
