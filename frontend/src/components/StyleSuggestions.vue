<script setup>
import { computed, ref } from 'vue'
import { Icon } from '@iconify/vue'
import { cleanDescription } from '@/utils/text'

const props = defineProps({
  // [{ style_id, style_name, image_url, similarity, description, tags, colors, materials, space_info }]
  candidates:  { type: Array,  default: () => [] },
  confirmed:   { type: Object, default: null },       // 使用者選中的那筆
  loading:     { type: Boolean, default: false },
  apiBase: { type: String, default: 'http://localhost:8000' },
})

const emit = defineEmits(['confirm', 'clear', 'search'])

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
  const card = el.querySelector('.card')
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
const openInfoId = ref(null)
const popoverPos = ref({ top: 0, left: 0 })
let closeTimer = null

const activeInfoCandidate = computed(
  () => topCandidates.value.find((c) => c.image_url === openInfoId.value) || null
)

function openPopover(c, evt) {
  clearTimeout(closeTimer)
  const rect = evt.currentTarget.getBoundingClientRect()
  popoverPos.value = {
    top: rect.bottom + 8,
    left: Math.min(rect.left - 220, window.innerWidth - 300),
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
        <h2>AI 推薦風格參考</h2>
        <button type="button" class="search-btn" :disabled="loading" @click="emit('search')">
          <Icon :icon="confirmed ? 'mdi:magnify' : 'mdi:refresh'" width="15" />
          {{ confirmed ? '找相似風格' : '換下一輪' }}
        </button>
      </div>
      <p class="subtitle">根據你的文字描述，找到以下相似風格圖片，選擇一張套用其風格參數</p>
    </div>

    <!-- 骨架載入 -->
    <div v-if="loading" class="rail">
      <div v-for="i in 5" :key="i" class="card skeleton">
        <div class="card-img-wrap skeleton-img"></div>
      </div>
    </div>

    <!-- 無結果 -->
    <div v-else-if="!topCandidates.length" class="empty-state">
      找不到相符的風格參考，請嘗試更換關鍵字或選擇特定風格
    </div>

    <!-- 候選卡片：單列橫向捲動 + 左右箭頭 -->
    <div v-else-if="topCandidates.length" class="rail-wrap">
      <button type="button" class="rail-arrow left" aria-label="往左捲動" @click="scrollRail(-1)">‹</button>
      <div ref="railRef" class="rail" role="list" aria-label="風格參考圖候選清單">
        <div
          v-for="c in topCandidates"
          :key="c.image_url"
          class="card"
          :class="{ selected: confirmed?.image_url === c.image_url }"
          role="listitem"
          tabindex="0"
          @keydown.enter.prevent="toggleConfirm(c)"
          @keydown.space.prevent="toggleConfirm(c)"
          @click="toggleConfirm(c)"
          @mouseenter="openPopover(c, $event)" @mouseleave="scheduleClosePopover"
          @focus="openPopover(c, $event)" @blur="scheduleClosePopover"
        >
          <div class="card-img-wrap">
            <img :src="normalizeImageUrl(c.image_url)" :alt="c.style_name" loading="lazy" @error="$event.target.style.display='none'" />
            <div class="card-overlay">
              <div class="overlay-name">{{ c.style_name }}</div>
            </div>
          </div>
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
      @mouseenter="cancelClosePopover" @mouseleave="scheduleClosePopover"
    >
      <div class="popover-header">
        <strong>{{ activeInfoCandidate.style_name }}</strong>
        <button type="button" class="popover-close" @click="openInfoId = null">
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
  color: #a07850;
  margin-bottom: 0.2rem;
}

.header-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  margin-bottom: 0.3rem;
}
.search-btn {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  gap: 0.3rem;
  border: 1.5px solid #8B5E3C;
  background: #fff;
  color: #8B5E3C;
  border-radius: 8px;
  padding: 0.4rem 0.85rem;
  font-size: 0.8rem;
  font-family: inherit;
  font-weight: 700;
  cursor: pointer;
  transition: all 0.15s;
}
.search-btn:hover:not(:disabled) { background: #8B5E3C; color: #fff; }
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
  border: 1.5px solid #d4b89a;
  background: rgba(255, 250, 243, 0.95);
  color: #8B5E3C;
  font-size: 1.3rem;
  line-height: 1;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.15s;
}
.rail-arrow:hover { background: #8B5E3C; color: white; border-color: #8B5E3C; }

/* Card：整張是圖，文字疊在圖片底部（漸層），不再另外留白色 card-body */
.card {
  position: relative;
  border-radius: 14px;
  overflow: visible;
  cursor: pointer;
  transition: all 0.2s;
  flex: 0 0 clamp(180px, 22%, 280px);
  scroll-snap-align: start;
}
.card:hover { transform: translateY(-2px); }
.card:focus-visible {
  outline: none;
  border-radius: 14px;
  box-shadow: 0 0 0 3px rgba(139, 94, 60, 0.25), 0 0 0 6px rgba(139, 94, 60, 0.14);
}

/* Image */
.card-img-wrap {
  position: relative;
  width: 100%;
  aspect-ratio: 3 / 4;
  overflow: hidden;
  border-radius: 14px;
  border: 1.5px solid #d4b89a;
  background: #f5e8d8;
  transition: border-color 0.15s, box-shadow 0.15s, transform 0.15s;
}
.card:hover .card-img-wrap { border-color: #b07845; box-shadow: 0 8px 24px rgba(139, 94, 60, 0.2); }
/* 選中：邊框變色 + 微放大 + 陰影，不用太誇張的粗框/外圈光暈 */
.card.selected .card-img-wrap {
  border-color: #8B5E3C;
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
  padding: 0.7rem 0.85rem;
  background: linear-gradient(to top, rgba(15, 9, 3, 0.88), rgba(15, 9, 3, 0) 70%);
  color: #fff;
  pointer-events: none;
}
.overlay-name {
  font-size: 1rem;
  font-weight: 800;
  text-shadow: 0 1px 2px rgba(0,0,0,0.85), 0 1px 8px rgba(0,0,0,0.5);
}

.empty-state {
  padding: 2rem;
  text-align: center;
  color: #a07850;
  font-size: 0.9rem;
  background: rgba(255,250,243,0.6);
  border: 1px dashed #d4b89a;
  border-radius: 12px;
}

/* 風格詳情浮卡（Teleport 到 body，position: fixed 用 JS 算好的座標定位） */
.style-popover {
  position: fixed;
  z-index: 200;
  width: 280px;
  background: #fffaf3;
  border: 1.5px solid #d4b89a;
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
  color: #a07850;
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
.popover-label { font-size: 0.72rem; font-weight: 700; color: #a07850; }
.swatches { display: flex; gap: 0.4rem; }
.swatch {
  width: 22px; height: 22px; border-radius: 50%;
  border: 1.5px solid rgba(0,0,0,0.12);
}
.chip-row { display: flex; flex-wrap: wrap; gap: 0.35rem; }
.chip-row .chip {
  font-size: 0.72rem;
  color: #5c3d24;
  background: rgba(139, 94, 60, 0.1);
  border-radius: 99px;
  padding: 0.18rem 0.55rem;
}

/* Confirmed bar */
.confirmed-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: rgba(139, 94, 60, 0.08);
  border: 1px solid #d4b89a;
  border-radius: 10px;
  padding: 0.65rem 1rem;
  font-size: 0.875rem;
  color: #5c3d24;
}
.clear-btn {
  background: none;
  border: none;
  color: #b07845;
  cursor: pointer;
  font-size: 0.82rem;
  font-weight: 600;
  padding: 0;
}
.clear-btn:hover { color: #8B5E3C; }

/* Skeleton */
.skeleton { pointer-events: none; }
.skeleton-img {
  background: linear-gradient(90deg, #f5e8d8 25%, #e8d4b8 50%, #f5e8d8 75%);
  background-size: 200% 100%;
  animation: shimmer 1.4s infinite;
}
@keyframes shimmer {
  0%   { background-position: 200% 0; }
  100% { background-position: -200% 0; }
}
</style>
