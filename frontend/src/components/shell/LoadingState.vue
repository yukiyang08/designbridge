<script setup>
/**
 * 設計稿沒有畫載入狀態，但每個生成步驟都要等 10–60 秒，沒有它畫面會像當掉。
 *
 * 畫面是一張自己畫自己的平面圖草稿（純裝飾，不代表實際進度——後端目前沒有回報階段）。
 * 真實資訊只有兩個：已等待秒數，以及超過 SLOW_AFTER 秒後的久候說明
 * （實測 fal 閒置後的第一次呼叫會冷啟動，可能要數分鐘）。
 */
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'

defineProps({
  title: { type: String, default: 'AI 生成中' },
  sub:   { type: String, default: '' },
})

const SLOW_AFTER = 40
const sec = ref(0)
let timer
onMounted(() => { timer = setInterval(() => { sec.value++ }, 1000) })
onBeforeUnmount(() => clearInterval(timer))

const elapsed = computed(() => {
  const m = Math.floor(sec.value / 60)
  return m ? `${m} 分 ${sec.value % 60} 秒` : `${sec.value} 秒`
})
const slow = computed(() => sec.value >= SLOW_AFTER)
</script>

<template>
  <div class="loading-state" role="status" aria-live="polite" aria-atomic="false" aria-busy="true">
    <svg class="plan" viewBox="0 0 260 170" aria-hidden="true" focusable="false">
      <!-- 圖紙格線 -->
      <defs>
        <pattern id="ls-grid" width="10" height="10" patternUnits="userSpaceOnUse">
          <path d="M10 0H0V10" fill="none" stroke="var(--db-accent-soft)" stroke-width="0.6" />
        </pattern>
      </defs>
      <rect x="0" y="0" width="260" height="170" fill="url(#ls-grid)" class="grid" />

      <!-- 地毯（虛線，先出現） -->
      <rect class="rug" x="92" y="88" width="84" height="42" rx="2" />

      <!-- 牆：一筆畫完 -->
      <path class="wall" pathLength="1" d="M30 24H230V146H30Z" />
      <!-- 門弧與窗 -->
      <path class="wall door" pathLength="1" d="M30 118V96M30 118A22 22 0 0 1 52 118" />
      <path class="wall win" pathLength="1" d="M92 24H168" />

      <!-- 家具：依序浮現 -->
      <g class="furn f1"><rect x="70" y="124" width="96" height="16" rx="4" /><rect x="70" y="116" width="96" height="8" rx="3" /></g>
      <g class="furn f2"><ellipse cx="134" cy="106" rx="20" ry="11" /></g>
      <g class="furn f3"><rect x="196" y="40" width="22" height="46" rx="2" /></g>
      <g class="furn f4"><circle cx="58" cy="50" r="11" /><circle cx="58" cy="50" r="5" /></g>

      <!-- 尺寸標註 -->
      <g class="dim">
        <path pathLength="1" d="M30 158H230M30 154V162M230 154V162" />
        <text x="130" y="167" text-anchor="middle">4.0 m</text>
      </g>
    </svg>

    <p class="title">{{ title }}</p>
    <p v-if="sub" class="sub">{{ sub }}</p>
    <p class="elapsed" aria-hidden="true">已等待 {{ elapsed }}</p>
    <p v-if="slow" class="slow">
      久未使用時，第一次生成需要先喚醒雲端運算，可能多花數分鐘，請先不要關閉頁面。
    </p>
  </div>
</template>

<style scoped>
.loading-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 0.4rem;
  min-height: 380px;
  padding: 2.5rem 1.5rem;
  text-align: center;
}

.plan {
  width: min(300px, 72vw);
  height: auto;
  margin-bottom: 1rem;
  overflow: visible;
}
.grid { opacity: 0.8; }

/* 線稿共用：墨色細線 */
.wall, .dim path {
  fill: none;
  stroke: var(--db-accent-ink);
  stroke-width: 2;
  stroke-linecap: round;
  stroke-linejoin: round;
  stroke-dasharray: 1;
  stroke-dashoffset: 1;
  animation: draw 7s ease-in-out infinite;
}
.wall.door, .wall.win { stroke-width: 1.4; animation-name: draw-late; }
.dim path { stroke-width: 1; animation-name: draw-late; }
.dim text {
  fill: var(--db-accent-ink);
  font: 9px var(--db-font-num);
  opacity: 0;
  animation: fade-late 7s ease-in-out infinite;
}

.rug {
  fill: none;
  stroke: var(--db-accent-deep);
  stroke-width: 1.2;
  stroke-dasharray: 4 3;
  opacity: 0;
  animation: pop-a 7s ease-in-out infinite;
}
.furn {
  fill: var(--db-accent-soft);
  stroke: var(--db-accent-ink);
  stroke-width: 1.4;
  opacity: 0;
  transform-box: fill-box;
  transform-origin: center;
}
.f1 { animation: pop-a 7s ease-in-out infinite; }
.f2 { animation: pop-b 7s ease-in-out infinite; }
.f3 { animation: pop-c 7s ease-in-out infinite; }
.f4 { animation: pop-d 7s ease-in-out infinite; }

/* 0–35% 畫牆，之後家具陸續出現，停一下，92% 後淡出重來（淡出時線稿已看不見，不會閃） */
@keyframes draw {
  0%   { stroke-dashoffset: 1; opacity: 1; }
  32%  { stroke-dashoffset: 0; opacity: 1; }
  90%  { stroke-dashoffset: 0; opacity: 1; }
  100% { stroke-dashoffset: 0; opacity: 0; }
}
@keyframes draw-late {
  0%, 30% { stroke-dashoffset: 1; opacity: 1; }
  45%     { stroke-dashoffset: 0; opacity: 1; }
  90%     { stroke-dashoffset: 0; opacity: 1; }
  100%    { stroke-dashoffset: 0; opacity: 0; }
}
@keyframes fade-late {
  0%, 45% { opacity: 0; }
  55%, 90% { opacity: 1; }
  100% { opacity: 0; }
}
@keyframes pop-a { 0%, 36% { opacity: 0; transform: scale(0.94); } 44%, 90% { opacity: 1; transform: scale(1); } 100% { opacity: 0; } }
@keyframes pop-b { 0%, 46% { opacity: 0; transform: scale(0.94); } 54%, 90% { opacity: 1; transform: scale(1); } 100% { opacity: 0; } }
@keyframes pop-c { 0%, 56% { opacity: 0; transform: scale(0.94); } 64%, 90% { opacity: 1; transform: scale(1); } 100% { opacity: 0; } }
@keyframes pop-d { 0%, 66% { opacity: 0; transform: scale(0.94); } 74%, 90% { opacity: 1; transform: scale(1); } 100% { opacity: 0; } }

.title {
  margin: 0;
  font-family: var(--db-font-display);
  font-style: italic;
  font-size: 1.4rem;
  color: var(--db-text);
}
.sub {
  margin: 0;
  color: var(--db-text-soft);
  font-size: 0.95rem;
}
.elapsed {
  margin: 0.35rem 0 0;
  color: var(--db-text-soft);   /* 不用 placeholder 色：白底對比度不足 */
  font-family: var(--db-font-num);
  font-size: 0.82rem;
  letter-spacing: 0.04em;
  font-variant-numeric: tabular-nums;
}
.slow {
  max-width: 28rem;
  margin: 0.6rem 0 0;
  padding: 0.6rem 0.9rem;
  border-radius: var(--db-radius-chip);
  background: var(--db-paper);
  color: var(--db-text-soft);
  font-size: 0.86rem;
  line-height: 1.7;
}

/* 減少動態：直接顯示畫好的平面圖，不跑動畫 */
@media (prefers-reduced-motion: reduce) {
  .wall, .dim path, .dim text, .rug, .furn {
    animation: none;
    stroke-dashoffset: 0;
    opacity: 1;
    transform: none;
  }
}
</style>
