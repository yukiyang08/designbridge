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
      <p class="subtitle">依你的描述找到的風格參考，選一張套用它的配色與材質</p>
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
        <p class="empty-error"><Icon icon="mdi:alert-outline" aria-hidden="true" /> {{ error }}</p>
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
                <div v-if="c.tags?.length" class="overlay-tags">{{ c.tags.slice(0, 2).join(' · ') }}</div>
              </div>
              <!-- 選中打勾：邊框變色在一排圖片裡不夠明顯 -->
              <span v-if="confirmed?.image_url === c.image_url" class="check-badge" aria-hidden="true">
                <Icon icon="mdi:check" width="14" />已選
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
            <Icon icon="mdi:information-outline" width="16" />
          </button>
        </div>
      </div>
      <button type="button" class="rail-arrow right" aria-label="往右捲動" @click="scrollRail(1)">›</button>
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

/* 標題跟頁面其他區塊同款：斜體襯線、墨色 */
.header h2 {
  font-family: var(--db-font-display);
  font-style: italic;
  font-size: 1.5rem;
  font-weight: 500;
  color: var(--db-text);
}
.subtitle {
  font-size: 0.85rem;
  color: var(--db-text-soft);
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
  border: 1px solid var(--db-line-strong);
  background: #fff;
  color: var(--db-text);
  border-radius: var(--db-radius-pill);
  padding: 0.4rem 0.95rem;
  font-size: 0.82rem;
  font-family: inherit;
  font-weight: 500;
  cursor: pointer;
  transition: border-color 0.15s, background 0.15s;
}
.search-btn:hover:not(:disabled) { border-color: var(--db-ink); background: var(--db-paper); }
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
  /* 上下留空間給選中外框與 hover 陰影，不然會被 overflow-x:auto 連帶產生的 overflow-y 裁掉 */
  padding: 0.5rem 0.4rem 0.9rem;
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
  border: 1px solid var(--db-line-strong);
  background: #fff;
  color: var(--db-text);
  font-size: 1.3rem;
  line-height: 1;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background 0.15s, color 0.15s, border-color 0.15s;
}
.rail-arrow:hover { background: var(--db-ink); color: #fff; border-color: var(--db-ink); }

/* slot 負責 rail 裡的寬度與吸附；ⓘ 按鈕是 .card 的兄弟節點，不放在 role=option 裡面 */
.card-slot {
  animation: card-in 0.35s both;
  animation-delay: calc(var(--i, 0) * 35ms);   /* 換一批／搜尋完成時依序浮現，看得出內容換了 */
  position: relative;
  /* 直式窄卡，一排約 5 張：原本近正方形、佔 26% 寬，只放得下 3.5 張 */
  flex: 0 0 clamp(150px, 18%, 210px);
  scroll-snap-align: start;
}
.info-btn {
  position: absolute;
  right: 0.5rem;
  bottom: 0.5rem;
  width: 30px;
  height: 30px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: none;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.18);
  color: #fff;
  cursor: pointer;
  backdrop-filter: blur(4px);
  transition: background 0.15s, color 0.15s;
}
.info-btn:hover { background: #fff; color: var(--db-text); }
.info-btn:focus-visible { outline: 2px solid #fff; outline-offset: 2px; }
.check-badge {
  position: absolute;
  top: 0.5rem;
  left: 0.5rem;
  display: flex;
  align-items: center;
  gap: 0.15rem;
  padding: 0.15rem 0.5rem 0.15rem 0.35rem;
  border-radius: 99px;
  background: #fff;
  color: var(--db-text);
  font-size: 0.72rem;
  font-weight: 500;
}

/* Card：整張是圖，文字疊在圖片底部（漸層），不再另外留白色 card-body */
.card {
  position: relative;
  border-radius: 12px;
  cursor: pointer;
}
.card:focus-visible {
  outline: 2px solid var(--db-ink);
  outline-offset: 3px;
}

/* Image */
.card-img-wrap {
  position: relative;
  width: 100%;
  aspect-ratio: 4 / 5;
  overflow: hidden;
  border-radius: 12px;
  background: var(--db-accent-soft);
  transition: box-shadow 0.2s;
}
.card:hover .card-img-wrap { box-shadow: var(--db-shadow-soft); }
/* 選中用外框描邊，不放大：放大會被 rail 裁切、也讓整排高低不齊 */
.card.selected .card-img-wrap { box-shadow: 0 0 0 2px var(--db-paper), 0 0 0 4px var(--db-ink); }
.card-img-wrap img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
  transition: transform 0.5s ease;
}
.card:hover .card-img-wrap img { transform: scale(1.04); }

/* 名稱常駐在底部；漸層只壓下緣 45%，不把整張照片染暗 */
.card-overlay {
  position: absolute;
  inset: auto 0 0 0;
  padding: 2.4rem 2.6rem 0.75rem 0.8rem;
  background: linear-gradient(to top, rgba(20, 18, 16, 0.78), rgba(20, 18, 16, 0));
  color: #fff;
  pointer-events: none;
}
.overlay-name {
  font-family: var(--db-font-display);
  font-style: italic;
  font-size: 1.05rem;
  font-weight: 500;
  letter-spacing: 0.02em;
  text-shadow: 0 1px 6px rgba(0, 0, 0, 0.4);
}
/* 標籤改純文字，不疊 pill：圖片上元素少一層才乾淨 */
.overlay-tags {
  margin-top: 0.15rem;
  font-size: 0.72rem;
  color: rgba(255, 255, 255, 0.82);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.overlay-swatches {
  position: absolute;
  top: 0.55rem;
  right: 0.55rem;
  display: flex;
  padding-left: 4px;
  pointer-events: none;
}
/* 色票疊在一起，白邊分隔，淺色照片上也看得清 */
.overlay-swatches .swatch {
  width: 14px;
  height: 14px;
  margin-left: -4px;
  border: 1.5px solid #fff;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.25);
}

.empty-state {
  padding: 2rem;
  text-align: center;
  color: var(--db-text-soft);
  font-size: 0.9rem;
  background: var(--db-paper);
  border: 1px dashed var(--db-line-strong);
  border-radius: 12px;
}

/* 風格詳情浮卡（Teleport 到 body，position: fixed 用 JS 算好的座標定位） */
.style-popover {
  position: fixed;
  z-index: 200;
  width: 280px;
  background: #fff;
  border: 1px solid var(--db-line);
  border-radius: 12px;
  box-shadow: var(--db-shadow-card);
  padding: 0.9rem 1rem;
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
}
.popover-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-family: var(--db-font-display);
  font-style: italic;
  font-size: 1rem;
  color: var(--db-text);
  padding-bottom: 0.4rem;
  border-bottom: 1px solid var(--db-line);
}
.popover-header strong { font-weight: 500; }
.popover-close {
  border: none;
  background: none;
  color: var(--db-accent-deep);
  cursor: pointer;
  display: flex;
  padding: 0;
}
.popover-close:hover { color: var(--db-text); }
.popover-desc {
  font-size: 0.8rem;
  color: var(--db-text-soft);
  line-height: 1.6;
  margin: 0;
}
.popover-row { display: flex; flex-direction: column; gap: 0.35rem; }
.popover-label { font-size: 0.75rem; font-weight: 500; color: var(--db-accent-ink); }
.swatches { display: flex; gap: 0.4rem; }
.swatch {
  width: 22px; height: 22px; border-radius: 50%;
  border: 1.5px solid rgba(0,0,0,0.12);
}
.chip-row { display: flex; flex-wrap: wrap; gap: 0.35rem; }
.chip-row .chip {
  font-size: 0.72rem;
  color: var(--db-text);
  background: var(--db-chip-soft);
  border-radius: 99px;
  padding: 0.18rem 0.55rem;
}

@media (max-width: 640px) {
  .suggestions { gap: 1rem; }
  .header h2 { font-size: 1.2rem; }
  .subtitle { font-size: 0.8rem; }
  .search-btn { padding: 0.35rem 0.75rem; font-size: 0.78rem; }
  .rail-arrow { display: none; }   /* 手機用手指滑，箭頭只佔寬度 */
  .card-slot, .skeleton { flex-basis: 132px; }
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

/* Skeleton */
.skeleton { pointer-events: none; flex: 0 0 clamp(150px, 18%, 210px); }   /* 跟 .card-slot 同寬 */
.skeleton-img {
  background: linear-gradient(90deg, var(--db-paper) 25%, var(--db-accent-soft) 50%, var(--db-paper) 75%);
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
