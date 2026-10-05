<script setup>
import { computed, ref } from 'vue'
import { Icon } from '@iconify/vue'
import { cleanDescription } from '@/utils/text'

const props = defineProps({
  // [{ style_id, style_name, image_url, similarity, description, tags, colors, materials, space_info }]
  candidates:  { type: Array,  default: () => [] },
  confirmed:   { type: Object, default: null },       // 使用者選中的那筆
  loading:     { type: Boolean, default: false },
  error:       { type: String, default: '' },
  apiBase: { type: String, default: 'http://localhost:8000' },
})

const emit = defineEmits(['confirm', 'clear', 'next-round', 'similar', 'retry'])

// 每個風格一張卡，數量交給後端（diverse 模式 = 風格總數），前端不再砍到固定 6 張。
const topCandidates = computed(() => {
  const list = Array.isArray(props.candidates) ? props.candidates : []
  return [...list]
    .filter((c) => c && typeof c.image_url === 'string')
    .sort((a, b) => (Number(b.similarity ?? 0) - Number(a.similarity ?? 0)))
})

const railRef = ref(null)
function scrollRail(dir) {
  const el = railRef.value
  if (!el) return
  // 卡片寬度現在是「可視寬度/5」算出來的，不是寫死的值，捲動量跟著量測，不用另外維護一個數字
  const card = el.querySelector('.card-slot')
  const gap = parseFloat(getComputedStyle(el).columnGap || '0') || 0
  const step = card ? card.getBoundingClientRect().width + gap : el.clientWidth / 5
  el.scrollBy({ left: dir * step, behavior: 'smooth' })
}

function toggleConfirm(c) {
  if (props.confirmed?.image_url === c.image_url) emit('clear')
  else emit('confirm', c)
}

function normalizeImageUrl(rawUrl) {
  if (typeof rawUrl !== 'string') return ''
  const url = rawUrl.trim()
  if (!url) return ''
  if (url.startsWith('http://') || url.startsWith('https://')) return url
  if (url.startsWith('/')) return `${props.apiBase}${url}`
  return url
}

// ── 資訊卡片（hover/鍵盤聚焦卡片本身就會開）── 用 Teleport 貼到 body，避免被 .rail 的橫向捲動裁掉
const POPOVER_W = 280   // 要跟 .style-popover 的 width 一致
const openInfoId = ref(null)
const popoverPos = ref({ top: 0, left: 0 })
let closeTimer = null

const activeInfoCandidate = computed(
  () => topCandidates.value.find((c) => c.image_url === openInfoId.value) || null
)

let openTimer = null
// 滑鼠移過去停 200ms 才開，快速掃過整排卡片不會一直跳浮卡；觸控沒有 hover，點 ⓘ 就開
function hoverOpen(c, evt) {
  clearTimeout(openTimer)
  const btn = evt.currentTarget
  openTimer = setTimeout(() => openPopover(c, btn), 200)
}
function hoverLeave() {
  clearTimeout(openTimer)
  scheduleClosePopover()
}
function toggleInfo(c, evt) {
  if (openInfoId.value === c.image_url) openInfoId.value = null
  else openPopover(c, evt.currentTarget)
}
function openPopover(c, btn) {
  clearTimeout(closeTimer)
  // 浮在卡片右上角旁邊；右邊放不下（捲到最右那幾張）就翻到卡片左側
  const rect = btn.closest('.card-slot').getBoundingClientRect()
  const gap = 8
  const fitsRight = rect.right + gap + POPOVER_W <= window.innerWidth - gap
  popoverPos.value = {
    top: Math.max(gap, rect.top),
    left: fitsRight ? rect.right + gap : Math.max(gap, rect.left - gap - POPOVER_W),
  }
  openInfoId.value = c.image_url
}
function scheduleClosePopover() {
  clearTimeout(closeTimer)
  closeTimer = setTimeout(() => { openInfoId.value = null }, 150)
}
function cancelClosePopover() { clearTimeout(closeTimer) }
</script>

<template>
  <div class="suggestions">
    <div class="header">
      <div class="header-top">
        <h2>智慧風格推薦</h2>
        <div class="header-btns">
          <button type="button" class="search-btn" :disabled="loading" @click="emit('next-round')">
            <Icon icon="mdi:refresh" width="15" />換一批
          </button>
          <button v-if="confirmed" type="button" class="search-btn" :disabled="loading" @click="emit('similar')">
            <Icon icon="mdi:magnify" width="15" />找相似風格
          </button>
        </div>
      </div>
      <p class="subtitle">根據你的文字描述，找到以下相似風格圖片，選擇一張套用其風格參數；點卡片右下角的 ⓘ 看詳情</p>
    </div>

    <!-- 骨架載入 -->
    <div v-if="loading" class="rail" role="status" aria-label="搜尋風格中">
      <div v-for="i in 5" :key="i" class="card skeleton">
        <div class="card-img-wrap skeleton-img"></div>
      </div>
    </div>

    <!-- 無結果 -->
    <div v-else-if="!topCandidates.length" class="empty-state">
      <template v-if="error">
        <p class="empty-error">⚠ {{ error }}</p>
        <button type="button" class="search-btn" @click="emit('retry')"><Icon icon="mdi:refresh" width="15" />重試</button>
      </template>
      <template v-else>找不到相符的風格參考，請嘗試更換關鍵字或選擇特定風格</template>
    </div>

    <!-- 候選卡片：單列橫向捲動 + 左右箭頭 -->
    <div v-else-if="topCandidates.length" class="rail-wrap">
      <button type="button" class="rail-arrow left" aria-label="往左捲動" @click="scrollRail(-1)">‹</button>
      <div ref="railRef" class="rail" role="listbox" aria-label="風格參考圖候選清單">
        <div v-for="(c, i) in topCandidates" :key="c.image_url" class="card-slot" :style="{ '--i': i }">
          <div
            class="card"
            :class="{ selected: confirmed?.image_url === c.image_url }"
            role="option"
            :aria-selected="confirmed?.image_url === c.image_url"
            tabindex="0"
            @keydown.enter.prevent="toggleConfirm(c)"
            @keydown.space.prevent="toggleConfirm(c)"
            @click="toggleConfirm(c)"
          >
            <div class="card-img-wrap">
              <img :src="normalizeImageUrl(c.image_url)" :alt="c.style_name" loading="lazy" @error="$event.target.style.display='none'" />
              <div class="card-overlay">
                <div class="overlay-name">{{ c.style_name }}</div>
                <div v-if="c.tags?.length" class="overlay-tags">
                  <span v-for="t in c.tags.slice(0, 3)" :key="t" class="overlay-tag">{{ t }}</span>
                </div>
              </div>
              <!-- 選中打勾：邊框變色在一排圖片裡不夠明顯 -->
              <span v-if="confirmed?.image_url === c.image_url" class="check-badge" aria-hidden="true">
                <Icon icon="mdi:check" width="16" />已選
              </span>
              <!-- 主要色彩放卡片右上角，不跟底部的名稱／標籤擠在一起 -->
              <div v-if="Object.keys(c.colors || {}).length" class="overlay-swatches" aria-label="主要色彩">
                <span v-for="(hex, k) in c.colors" :key="k" class="swatch" :style="{ background: hex }"></span>
              </div>
            </div>
          </div>
          <!-- 看詳情 ≠ 選取：獨立按鈕，觸控也點得到（原本只靠 hover/focus） -->
          <button
            type="button"
            class="info-btn"
            :aria-label="`${c.style_name} 風格詳情`"
            :aria-expanded="openInfoId === c.image_url"
            @click.stop="toggleInfo(c, $event)"
            @mouseenter="hoverOpen(c, $event)" @mouseleave="hoverLeave"
          >
            <Icon icon="mdi:information-outline" width="18" />
          </button>
        </div>
      </div>
      <button type="button" class="rail-arrow right" aria-label="往右捲動" @click="scrollRail(1)">›</button>
    </div>

    <!-- 已選提示 + 清除 -->
    <div v-if="confirmed" class="confirmed-bar">
      <span>已選：<strong>{{ confirmed.style_name }}</strong></span>
      <button class="clear-btn" @click="emit('clear')">取消套用</button>
    </div>
  </div>

  <!-- 風格詳情浮卡：Teleport 到 body，避免被 .rail 的橫向捲動裁掉 -->
  <Teleport to="body">
    <div
      v-if="activeInfoCandidate"
      class="style-popover"
      :style="{ top: popoverPos.top + 'px', left: popoverPos.left + 'px' }"
      role="dialog" :aria-label="`${activeInfoCandidate.style_name} 詳情`"
      @mouseenter="cancelClosePopover" @mouseleave="scheduleClosePopover"
      @keydown.esc="openInfoId = null"
    >
      <div class="popover-header">
        <strong>{{ activeInfoCandidate.style_name }}</strong>
        <button type="button" class="popover-close" aria-label="關閉" @click="openInfoId = null">
          <Icon icon="mdi:close" width="14" />
        </button>
      </div>
      <p v-if="activeInfoCandidate.description" class="popover-desc">{{ cleanDescription(activeInfoCandidate.description) }}</p>
      <div v-if="activeInfoCandidate.tags?.length" class="popover-row">
        <div class="chip-row">
          <span v-for="t in activeInfoCandidate.tags" :key="t" class="chip">{{ t }}</span>
        </div>
      </div>
      <div v-if="Object.keys(activeInfoCandidate.colors || {}).length" class="popover-row">
        <span class="popover-label">主要色彩</span>
        <div class="swatches">
          <span
            v-for="(hex, k) in activeInfoCandidate.colors" :key="k"
            class="swatch" :style="{ background: hex }" :title="hex"
          ></span>
        </div>
      </div>
      <div v-if="activeInfoCandidate.materials?.length" class="popover-row">
        <span class="popover-label">常用材質</span>
        <div class="chip-row">
          <span v-for="m in activeInfoCandidate.materials" :key="m" class="chip">{{ m }}</span>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.suggestions {
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
  width: 100%;
}

.header h2 {
  font-size: 1.4rem;
  font-weight: 800;
  color: #5c3d24;
  margin-bottom: 0.1rem;
}
.subtitle {
  font-size: 0.875rem;
  color: #7d746c;
  margin-bottom: 0.2rem;
}

.header-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  margin-bottom: 0.3rem;
}
.header-btns { display: flex; gap: 0.5rem; flex-shrink: 0; }
.search-btn {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  gap: 0.3rem;
  border: 1.5px solid #756d66;
  background: #fff;
  color: #756d66;
  border-radius: 8px;
  padding: 0.4rem 0.85rem;
  font-size: 0.8rem;
  font-family: inherit;
  font-weight: 700;
  cursor: pointer;
  transition: all 0.15s;
}
.search-btn:hover:not(:disabled) { background: #756d66; color: #fff; }
.search-btn:disabled { opacity: 0.55; cursor: default; }

/* 單列橫向捲動 + 左右箭頭 */
.rail-wrap {
  position: relative;
  display: flex;
  align-items: center;
  gap: 0.4rem;
}
.rail {
  display: flex;
  gap: 1.05rem;
  /* 上下留夠空間給選中卡片的 scale + 陰影，不然會被 overflow-x:auto 連帶產生的 overflow-y 裁掉 */
  padding: 1rem 0.3rem 1.15rem;
  overflow-x: auto;
  scroll-snap-type: x proximity;
  scroll-behavior: smooth;
  scrollbar-width: none;
}
.rail::-webkit-scrollbar { display: none; }

.rail-arrow {
  flex: none;
  width: 2.1rem;
  height: 2.1rem;
  border-radius: 50%;
  border: 1.5px solid #c9c4bb;
  background: rgba(255, 250, 243, 0.95);
  color: #756d66;
  font-size: 1.3rem;
  line-height: 1;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.15s;
}
.rail-arrow:hover { background: #756d66; color: white; border-color: #756d66; }

/* slot 負責 rail 裡的寬度與吸附；ⓘ 按鈕是 .card 的兄弟節點，不放在 role=option 裡面 */
.card-slot {
  animation: card-in 0.35s both;
  animation-delay: calc(var(--i, 0) * 35ms);   /* 換一批／搜尋完成時依序浮現，看得出內容換了 */
  position: relative;
  flex: 0 0 clamp(210px, 26%, 320px);
  scroll-snap-align: start;
}
.info-btn {
  position: absolute;
  right: 0.55rem;
  bottom: 0.55rem;
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: none;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.92);
  color: #5c3d24;
  cursor: pointer;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.3);
  transition: transform 0.15s, background 0.15s;
}
.info-btn:hover { background: #fff; transform: scale(1.1); }
.info-btn:focus-visible { outline: 2px solid #5c3d24; outline-offset: 2px; }
.check-badge {
  position: absolute;
  top: 0.55rem;
  left: 0.55rem;
  display: flex;
  align-items: center;
  gap: 0.15rem;
  padding: 0.2rem 0.55rem 0.2rem 0.35rem;
  border-radius: 99px;
  background: #5c3d24;
  color: #fff;
  font-size: 0.75rem;
  font-weight: 700;
}

/* Card：整張是圖，文字疊在圖片底部（漸層），不再另外留白色 card-body */
.card {
  position: relative;
  border-radius: 14px;
  overflow: visible;
  cursor: pointer;
  transition: all 0.2s;
}
.card:hover { transform: translateY(-2px); }
.card:focus-visible {
  outline: none;
  border-radius: 14px;
  box-shadow: 0 0 0 3px rgba(117, 109, 102, 0.25), 0 0 0 6px rgba(117, 109, 102, 0.14);
}

/* Image */
.card-img-wrap {
  position: relative;
  width: 100%;
  aspect-ratio: 10 / 11;
  overflow: hidden;
  border-radius: 14px;
  border: 1.5px solid #c9c4bb;
  background: #f5e8d8;
  transition: border-color 0.15s, box-shadow 0.15s, transform 0.15s;
}
.card:hover .card-img-wrap { border-color: #b07845; box-shadow: 0 8px 24px rgba(117, 109, 102, 0.2); }
/* 選中：邊框變色 + 微放大 + 陰影，不用太誇張的粗框/外圈光暈 */
.card.selected .card-img-wrap {
  border-color: #756d66;
  box-shadow: 0 6px 16px rgba(92, 61, 36, 0.28);
  transform: scale(1.03);
}
.card-img-wrap img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
  transition: transform 0.3s;
}
.card:hover .card-img-wrap img { transform: scale(1.04); }

/* 名稱常駐在圖片底部；沒有 hover/選取時漸層也夠深、文字雙層陰影，避免亮色照片把白字洗掉。 */
.card-overlay {
  position: absolute;
  inset: auto 0 0 0;
  padding: 2.2rem 0.85rem 0.7rem;
  background: linear-gradient(to top, rgba(15, 9, 3, 0.92) 35%, rgba(15, 9, 3, 0));
  color: #fff;
  pointer-events: none;
}
.overlay-name {
  font-size: 1rem;
  font-weight: 800;
  text-shadow: 0 1px 2px rgba(0,0,0,0.85), 0 1px 8px rgba(0,0,0,0.5);
}
/* 卡片只露標籤 + 主要用色；描述文字留在 hover 浮卡（information） */
.overlay-tags { display: flex; flex-wrap: wrap; gap: 0.25rem; margin-top: 0.35rem; }
.overlay-tag {
  font-size: 0.75rem;
  color: #fff;
  background: rgba(255, 255, 255, 0.2);
  border-radius: 99px;
  padding: 0.1rem 0.5rem;
}
.overlay-swatches {
  position: absolute;
  top: 0.55rem;
  right: 0.55rem;
  display: flex;
  gap: 0.3rem;
  padding: 0.25rem 0.4rem;
  border-radius: 99px;
  background: rgba(15, 9, 3, 0.35);   /* 淺色照片上色塊也看得清楚 */
  pointer-events: none;
}
.overlay-swatches .swatch { width: 16px; height: 16px; border-color: rgba(255,255,255,0.8); }

.empty-state {
  padding: 2rem;
  text-align: center;
  color: #a39b94;
  font-size: 0.9rem;
  background: rgba(255,250,243,0.6);
  border: 1px dashed #c9c4bb;
  border-radius: 12px;
}

/* 風格詳情浮卡（Teleport 到 body，position: fixed 用 JS 算好的座標定位） */
.style-popover {
  position: fixed;
  z-index: 200;
  width: 280px;
  background: #fffaf3;
  border: 1.5px solid #c9c4bb;
  border-radius: 12px;
  box-shadow: 0 12px 32px rgba(92, 61, 36, 0.22);
  padding: 0.9rem 1rem;
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
}
.popover-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 0.92rem;
  color: #5c3d24;
  padding-bottom: 0.4rem;
  border-bottom: 1px solid #ecdcc4;
}
.popover-close {
  border: none;
  background: none;
  color: #a39b94;
  cursor: pointer;
  display: flex;
  padding: 0;
}
.popover-close:hover { color: #5c3d24; }
.popover-desc {
  font-size: 0.8rem;
  color: #6b5a45;
  line-height: 1.6;
  margin: 0;
}
.popover-row { display: flex; flex-direction: column; gap: 0.35rem; }
.popover-label { font-size: 0.75rem; font-weight: 700; color: #7d746c; }
.swatches { display: flex; gap: 0.4rem; }
.swatch {
  width: 22px; height: 22px; border-radius: 50%;
  border: 1.5px solid rgba(0,0,0,0.12);
}
.chip-row { display: flex; flex-wrap: wrap; gap: 0.35rem; }
.chip-row .chip {
  font-size: 0.72rem;
  color: #5c3d24;
  background: rgba(117, 109, 102, 0.1);
  border-radius: 99px;
  padding: 0.18rem 0.55rem;
}

/* 手機：浮卡改成貼底的 bottom sheet，不用算座標、也不會被螢幕邊緣切掉 */
@media (max-width: 640px) {
  .style-popover {
    top: auto !important;
    left: 0 !important;
    right: 0;
    bottom: 0;
    width: auto;
    max-height: 60vh;
    overflow-y: auto;
    border-radius: 16px 16px 0 0;
  }
}

/* Confirmed bar */
.confirmed-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: rgba(117, 109, 102, 0.08);
  border: 1px solid #c9c4bb;
  border-radius: 10px;
  padding: 0.65rem 1rem;
  font-size: 0.875rem;
  color: #5c3d24;
}
.clear-btn {
  background: none;
  border: none;
  color: #8a5a2b;
  cursor: pointer;
  font-size: 0.82rem;
  font-weight: 600;
  padding: 0.3rem 0.6rem;
  border-radius: 6px;
}
.clear-btn:hover { background: rgba(117, 109, 102, 0.12); color: #5c3d24; }

/* Skeleton */
.skeleton { pointer-events: none; flex: 0 0 clamp(210px, 26%, 320px); }   /* 寬度原本在 .card 上，搬到 .card-slot 後骨架要自己帶 */
.skeleton-img {
  background: linear-gradient(90deg, #f5e8d8 25%, #e8d4b8 50%, #f5e8d8 75%);
  background-size: 200% 100%;
  animation: shimmer 1.4s infinite;
}
@keyframes card-in {
  from { opacity: 0; transform: translateY(8px); }
  to   { opacity: 1; transform: none; }
}
.empty-error { margin: 0 0 0.75rem; color: var(--db-danger, #a03030); }
@media (prefers-reduced-motion: reduce) { .card-slot { animation: none; } }
@keyframes shimmer {
  0%   { background-position: 200% 0; }
  100% { background-position: -200% 0; }
}
</style>
