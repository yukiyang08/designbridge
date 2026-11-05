<script setup>
import { Icon } from '@iconify/vue'
import { ref, computed, onBeforeUnmount } from 'vue'
import { useFurnitureSelection } from '@/composables/useFurnitureSelection'
import AppNav from '@/components/shell/AppNav.vue'
import sceneBg from '@/assets/figma/room-bg.png'

const { selectedFurniture, selectedCount, toggle, remove, clear } = useFurnitureSelection()

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

const price = item => Number(item.price || 0)

// 依分類分組並算小計，取代逐件勾「計入總價」
const groups = computed(() => {
  const map = new Map()
  for (const item of selectedFurniture.value) {
    const cat = item.category || 'other'
    if (!map.has(cat)) map.set(cat, { cat, label: categoryLabels[cat] || item.category || '其他', items: [], subtotal: 0 })
    const g = map.get(cat)
    g.items.push(item)
    g.subtotal += price(item)
  }
  return [...map.values()]
})
const total = computed(() => selectedFurniture.value.reduce((sum, item) => sum + price(item), 0))

// 移除後留幾秒「復原」：收藏刪掉會同步到雲端，按錯就找不回來
const undo = ref(null)   // { items, text }
let undoTimer
function offerUndo(items, text) {
  undo.value = { items, text }
  clearTimeout(undoTimer)
  undoTimer = setTimeout(() => { undo.value = null }, 6000)
}
function removeItem(item) {
  remove(item)
  offerUndo([item], `已移除「${item.name}」`)
}
function clearAll() {
  if (!confirm(`確定清空全部 ${selectedCount.value} 件收藏？`)) return
  const items = [...selectedFurniture.value]
  clear()
  offerUndo(items, `已清空 ${items.length} 件收藏`)
}
function restore() {
  for (const item of undo.value.items) toggle(item)
  undo.value = null
}
onBeforeUnmount(() => clearTimeout(undoTimer))
</script>

<template>
  <div class="db-scene" :style="{ '--db-scene-image': `url(${sceneBg})` }">
    <AppNav />
    <div class="db-card cart-page">
      <header class="cart-header">
        <h1>我的收藏 <span v-if="selectedCount" class="count">{{ selectedCount }} 件</span></h1>
        <div class="header-actions">
          <button v-if="selectedCount" type="button" class="clear-btn" @click="clearAll">清空</button>
          <RouterLink to="/furniture" class="db-btn db-btn--ghost db-btn--sm">繼續查詢</RouterLink>
        </div>
      </header>

      <p class="local-note">登入後收藏會同步到你的帳號；未登入時只存在這台裝置的瀏覽器。</p>

      <div v-if="selectedCount === 0" class="empty-state">
        <p>收藏清單是空的</p>
        <RouterLink to="/furniture" class="db-btn">前往家具查詢挑選</RouterLink>
      </div>

      <template v-else>
        <section v-for="g in groups" :key="g.cat" class="group">
          <h2 class="group-head">
            <span>{{ g.label }} · {{ g.items.length }} 件</span>
            <span class="subtotal">NT$ {{ g.subtotal.toLocaleString() }}</span>
          </h2>
          <div class="grid">
            <article v-for="item in g.items" :key="itemKey(item)" class="card">
              <div class="card-img-wrap">
                <img
                  v-if="item.image_url" :src="item.image_url" :alt="item.name" class="card-img" loading="lazy"
                  @error="$event.target.style.display='none'"
                />
                <div v-else class="card-no-img">無圖</div>
                <button type="button" class="remove-btn" :aria-label="`移除 ${item.name}`" title="移除" @click="removeItem(item)">
                  <Icon icon="mdi:close" aria-hidden="true" />
                </button>
              </div>
              <div class="card-body">
                <span v-if="item.brand" class="card-brand">{{ item.brand }}</span>
                <p class="card-name">{{ item.name }}</p>
                <p class="card-price">{{ item.currency || 'TWD' }} {{ price(item).toLocaleString() }}</p>
                <a v-if="item.url" :href="item.url" target="_blank" rel="noopener" class="detail-link">查看詳情</a>
              </div>
            </article>
          </div>
        </section>

        <div class="cart-summary">
          <span>共 {{ selectedCount }} 件</span>
          <strong>總計 NT$ {{ total.toLocaleString() }}</strong>
        </div>
      </template>
    </div>

    <div v-if="undo" class="undo-toast" role="status">
      <span>{{ undo.text }}</span>
      <button type="button" class="undo-btn" @click="restore">復原</button>
    </div>
  </div>
</template>

<style scoped>
.cart-page { margin: 1.25rem auto 3rem; padding: 1.75rem 1.5rem 3rem; }

.cart-header { display: flex; align-items: center; justify-content: space-between; gap: 1rem; margin-bottom: 0.75rem; }
.cart-header h1 {
  display: flex; align-items: center; gap: 0.6rem; margin: 0;
  font-family: var(--db-font-display); font-style: italic; font-weight: 500;
  font-size: 1.6rem; color: var(--db-text);
}
.count { font-size: 0.85rem; color: var(--db-text-soft); font-style: normal; }
.header-actions { display: flex; align-items: center; gap: 0.6rem; }
.header-actions .db-btn { text-decoration: none; }
.clear-btn { border: 0; background: none; padding: 0.4rem; font-size: 0.82rem; color: var(--db-text-soft); cursor: pointer; text-decoration: underline; }
.clear-btn:hover { color: var(--db-danger); }
.local-note { margin: 0 0 1.25rem; font-size: 0.85rem; color: var(--db-text-soft); }

.empty-state { display: flex; flex-direction: column; align-items: center; gap: 1rem; padding: 4rem 1rem; color: var(--db-text-soft); }
.empty-state .db-btn { text-decoration: none; }

.group + .group { margin-top: 1.75rem; }
.group-head {
  display: flex; justify-content: space-between; align-items: baseline; margin: 0 0 0.75rem;
  padding-bottom: 0.4rem; border-bottom: 1px solid var(--db-line);
  font-size: 0.95rem; font-weight: 600; color: var(--db-text);
}
.subtotal { font-variant-numeric: tabular-nums; }

.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(min(200px, 100%), 1fr)); gap: 1rem; }
.card { background: #fff; border: 1px solid var(--db-line); border-radius: var(--db-radius-chip); overflow: hidden; }

.card-img-wrap { position: relative; aspect-ratio: 1 / 1; background: var(--db-chip-soft); overflow: hidden; }
.card-img { width: 100%; height: 100%; object-fit: cover; display: block; }
.card-no-img { display: grid; place-items: center; width: 100%; height: 100%; color: var(--db-placeholder); font-size: 0.8rem; }

/* 44px 點擊範圍，手機才按得到 */
.remove-btn {
  position: absolute; top: 4px; right: 4px; display: grid; place-items: center; width: 44px; height: 44px;
  border: none; background: none; cursor: pointer; color: #fff;
}
.remove-btn svg { width: 28px; height: 28px; padding: 5px; box-sizing: border-box; border-radius: 50%; background: rgba(0, 0, 0, 0.55); }
.remove-btn:hover svg { background: var(--db-danger); }
.remove-btn:focus-visible { outline: 2px solid var(--db-accent-deep); outline-offset: -4px; border-radius: 50%; }

.card-body { padding: 0.8rem 1rem 1rem; display: flex; flex-direction: column; gap: 0.3rem; }
.card-brand { align-self: flex-start; padding: 0.05rem 0.5rem; border-radius: var(--db-radius-pill); background: var(--db-chip-soft); font-size: 0.7rem; color: var(--db-text-soft); }
.card-name {
  font-size: 0.88rem; color: var(--db-text); margin: 0; line-height: 1.4;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;
}
.card-price { font-size: 0.92rem; color: var(--db-text); font-weight: 600; margin: 0; font-variant-numeric: tabular-nums; }
.detail-link { align-self: flex-start; font-size: 0.78rem; color: var(--db-accent-ink); text-decoration: underline; }
.detail-link:hover { color: var(--db-text); }

.cart-summary {
  display: flex; justify-content: space-between; align-items: center; margin-top: 1.75rem; padding: 0.9rem 1.1rem;
  border-radius: var(--db-radius-chip); background: var(--db-accent-soft); color: var(--db-text);
  font-size: 0.9rem; font-variant-numeric: tabular-nums;
}
.cart-summary strong { font-size: 1.05rem; }

.undo-toast {
  position: fixed; left: 50%; bottom: 1.5rem; transform: translateX(-50%); z-index: 50;
  display: flex; align-items: center; gap: 1rem; max-width: calc(100% - 2rem); padding: 0.6rem 0.75rem 0.6rem 1.1rem;
  border-radius: var(--db-radius-pill); background: var(--db-text); color: #fff; font-size: 0.85rem;
  box-shadow: var(--db-shadow-soft);
}
.undo-btn { min-height: 36px; padding: 0 0.9rem; border: none; border-radius: var(--db-radius-pill); background: #fff; color: var(--db-text); font-size: 0.82rem; font-weight: 600; cursor: pointer; }
</style>
