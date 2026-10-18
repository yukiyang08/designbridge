<script setup>
/**
 * 向量版的「選擇房間」——RoomPicker.vue 疊在上傳的點陣圖上用歸一化座標畫框，
 * 這裡的底圖是 CAD 生成的 SVG（designbridge/roomplan），房間本身已經是 SVG 裡的
 * <g class="room-rect" data-room-id="..."> 元素，所以不用重算像素座標，直接在
 * v-html 注入後的 DOM 上掛點擊事件即可（見 svg_render.py 的 room-rect 分組）。
 */
import { ref, watch, nextTick, onBeforeUnmount } from 'vue'

const props = defineProps({
  svgMarkup: { type: String, required: true },
  rooms:     { type: Array,  required: true }, // RoomInstance.to_dict() 陣列
  showHint:  { type: Boolean, default: true },     // 外層已經有標題與說明時可以關掉
})
const emit = defineEmits(['select-room'])

const boardRef = ref(null)
let cleanupFns = []

function clearHandlers() {
  cleanupFns.forEach(fn => fn())
  cleanupFns = []
}

function attachHandlers() {
  clearHandlers()
  const svg = boardRef.value?.querySelector('svg')
  if (!svg) return
  svg.querySelectorAll('.room-rect').forEach((el) => {
    const roomId = el.getAttribute('data-room-id')
    const room = props.rooms.find(r => r.id === roomId)
    if (!room) return
    const onClick = () => emit('select-room', room)
    el.addEventListener('click', onClick)
    cleanupFns.push(() => el.removeEventListener('click', onClick))
  })
}

watch(() => props.svgMarkup, () => nextTick(attachHandlers), { immediate: true })
onBeforeUnmount(clearHandlers)
</script>

<template>
  <div class="room-picker-cad">
    <p v-if="showHint" class="hint">點選要編輯的房間</p>
    <div ref="boardRef" class="board" v-html="svgMarkup"></div>
  </div>
</template>

<style scoped>
.room-picker-cad { display: flex; flex-direction: column; gap: 0.6rem; }

.hint { font-size: 0.85rem; color: var(--db-text-soft, #5a5a5a); margin: 0; }

.board {
  overflow-x: auto;
  border-radius: var(--db-radius-card, 20px);
  background: var(--db-card, #fff);
  padding: 1rem;
}
.board :deep(svg) {
  /* 平面圖 SVG 自帶固定的 width/height 屬性，不設的話只會畫成原始尺寸、旁邊留一大片空白；
     它有 viewBox，所以撐滿欄寬會等比放大。高度設上限，避免在高度不夠的畫面上要捲動才看得到整張。 */
  width: 100%;
  height: auto;
  max-height: min(72vh, 820px);
  display: block;
  margin: 0 auto;
}

.board :deep(.room-rect) { cursor: pointer; }
/* Scoped to the room's own floor plate (.room-floor, see svg_render.py) rather than
   every <rect> under .room-rect — the group also contains furniture symbol rects, and
   an unscoped selector would recolor those too on hover instead of just the floor. */
.board :deep(.room-rect .room-floor) { transition: fill 0.15s, stroke 0.15s; }
.board :deep(.room-rect:hover .room-floor) { fill: var(--db-accent-soft, #e6e3dd); stroke: var(--db-accent-deep, #a39b94); }
</style>
