<script setup>
/**
 * 尺寸標示（畫布外圍）：上緣、左緣各一條總長；有門窗的邊另有一條「尺寸鏈」，
 * 把牆切成 牆 → 門/窗 → 牆 各段，標出每段公分數（跟建築圖的慣用標法一樣）。
 * 用 HTML 排版而不是 SVG：畫布長寬比被夾住時 SVG 的文字會跟著被拉扁。
 */
import { computed } from 'vue'
import { sideSegments } from '@/utils/roomGeometry'

const props = defineProps({
  roomW: { type: Number, required: true },
  roomD: { type: Number, required: true },
  geometry: { type: Object, default: null },
})

const cm = (m) => Math.round(m * 100)
const chains = computed(() => ['top', 'bottom', 'left', 'right'].map(side => {
  const L = side === 'top' || side === 'bottom' ? props.roomW : props.roomD
  return { side, vertical: side === 'left' || side === 'right', segs: sideSegments(props.geometry, side, L), L }
}).filter(c => c.segs.length))
</script>

<template>
  <div class="dims">
    <!-- 總長 -->
    <div class="row total top">
      <div class="seg" style="flex: 1"><span class="lab">{{ cm(roomW) }} cm</span></div>
    </div>
    <div class="row total left v">
      <div class="seg" style="flex: 1"><span class="lab">{{ cm(roomD) }} cm</span></div>
    </div>

    <!-- 尺寸鏈 -->
    <div v-for="c in chains" :key="c.side" class="row chain" :class="[c.side, { v: c.vertical }]">
      <div
        v-for="(s, i) in c.segs" :key="i"
        class="seg" :class="s.type"
        :style="{ flex: s.len / c.L }"
      ><span v-if="s.len / c.L > 0.045" class="lab">{{ cm(s.len) }}</span></div>
    </div>
  </div>
</template>

<style scoped>
.dims {
  position: absolute; inset: 0; pointer-events: none;
  --pad: 46px; --c: #8a7a66;
  font-size: 11px; color: #5a4a36; font-variant-numeric: tabular-nums;
}
.row { position: absolute; display: flex; }
.row:not(.v) { left: var(--pad); right: var(--pad); height: 16px; flex-direction: row; }
.row.v { top: var(--pad); bottom: var(--pad); width: 16px; flex-direction: column; }

/* 內圈：尺寸鏈；外圈：總長 */
.chain.top    { top: 26px; }
.chain.bottom { bottom: 26px; }
.chain.left   { left: 26px; }
.chain.right  { right: 26px; }
.total.top    { top: 5px; }
.total.left   { left: 5px; }

.seg {
  position: relative; display: flex; align-items: center; justify-content: center;
  min-width: 0; border: 0 solid var(--c);
}
.row:not(.v) .seg { border-left-width: 1px; border-right-width: 1px; }
.row.v .seg { border-top-width: 1px; border-bottom-width: 1px; }
/* 標註線本身 */
.seg::before { content: ''; position: absolute; background: var(--c); }
.row:not(.v) .seg::before { left: 0; right: 0; top: 50%; height: 1px; }
.row.v .seg::before { top: 0; bottom: 0; left: 50%; width: 1px; }
.seg.window::before { background: #2e6ab5; }
.seg.door::before { background: #444; }

.lab {
  position: relative; padding: 0 3px; background: #fff; border-radius: 2px; line-height: 1.2;
  white-space: nowrap;
  transform: scale(calc(1 / var(--z, 1)));
}
.row.v .lab { writing-mode: vertical-rl; transform: rotate(180deg) scale(calc(1 / var(--z, 1))); padding: 3px 0; }
.chain .window .lab { color: #2e6ab5; }
</style>
