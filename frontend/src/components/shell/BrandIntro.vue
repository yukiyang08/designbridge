<script setup>
/**
 * 品牌開場動畫：兩岸的線先畫出來，屋頂從兩端往中間搭起來（橋），窗格亮起，字樣逐字從底線浮上來。
 * 幾何來自 assets/brand/logo-parts.json（跟 logo.svg 同一份產生的），字樣是外框，不依賴字型。
 */
import { onMounted, onBeforeUnmount, useId } from 'vue'
import parts from '@/assets/brand/logo-parts.json'

const emit = defineEmits(['done'])

const uid = useId()
const id = name => `${uid}-${name}`

const viewBox = parts.viewBox.join(' ')
const [ruleL, ruleR, ruleB] = parts.rules
const [feetL, feetR] = parts.roofFeet
// 屋頂畫成一條粗線（不是填色多邊形），才能從兩腳往屋脊畫；腳往下多伸一點，再用裁切切齊上橫線
const ROOF_T = 16.6
const roofPath = `M${feetL - 7 / 0.745} ${225 + 7}L478.3 84.6L${feetR + 7 / 0.745} ${225 + 7}`
const letters = parts.letters.map((d, i) => ({ d, delay: 1.75 + i * 0.055 }))
const DURATION_MS = 3300

let timer
onMounted(() => {
  const reduced = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
  timer = setTimeout(() => emit('done'), reduced ? 0 : DURATION_MS)
})
onBeforeUnmount(() => clearTimeout(timer))
</script>

<template>
  <svg class="brand-intro" :viewBox="viewBox" role="img" aria-label="DesignBridge">
    <defs>
      <clipPath :id="id('roof')"><rect x="0" y="0" width="960" :height="225 + 1.6" /></clipPath>
      <!-- 字母從這條帶子的底邊浮出來 -->
      <clipPath :id="id('band')"><rect x="0" y="262" width="960" height="170" /></clipPath>
    </defs>

    <!-- 上橫線：兩岸，從外往內長 -->
    <rect class="grow from-start" :x="ruleL[0]" :y="ruleL[1]" :width="ruleL[2]" :height="ruleL[3]" />
    <rect class="grow from-end" :x="ruleR[0]" :y="ruleR[1]" :width="ruleR[2]" :height="ruleR[3]" />

    <!-- 屋頂：一條路徑，從兩腳同時往屋脊畫，合攏後輕輕一彈 -->
    <g :clip-path="`url(#${id('roof')})`">
      <g class="roof-bump">
        <path class="roof" pathLength="2" :stroke-width="ROOF_T" :d="roofPath" />
      </g>
    </g>

    <!-- 窗格：一格一格亮起 -->
    <rect
      v-for="(t, i) in parts.tiles" :key="`t${i}`" class="tile" :style="{ animationDelay: `${1.45 + i * 0.09}s` }"
      :x="t[0]" :y="t[1]" :width="t[2]" :height="t[3]" :rx="t[4]"
    />

    <!-- 字樣：逐字往上浮 -->
    <g :clip-path="`url(#${id('band')})`">
      <path v-for="(l, i) in letters" :key="`c${i}`" class="letter" :style="{ animationDelay: `${l.delay}s` }" :d="l.d" />
    </g>

    <!-- 下橫線：從中間往兩側收尾 -->
    <rect class="grow from-center" :x="ruleB[0]" :y="ruleB[1]" :width="ruleB[2]" :height="ruleB[3]" />
  </svg>
</template>

<style scoped>
.brand-intro {
  --brand: #8c7163;   /* logo 原色 */
  display: block;
  width: 100%;
  height: auto;
  overflow: visible;
  fill: var(--brand);
}

.grow {
  transform-box: fill-box;
  transform: scaleX(0);
  animation: grow 0.7s cubic-bezier(0.65, 0, 0.35, 1) 0.15s forwards;
}
.from-start { transform-origin: left center; }
.from-end { transform-origin: right center; }
.from-center { transform-origin: center; animation-delay: 2.35s; animation-duration: 0.75s; }
@keyframes grow { to { transform: scaleX(1); } }

.roof {
  fill: none;
  stroke: var(--brand);
  stroke-linejoin: miter;
  stroke-dasharray: 0 2 0;
  animation: span 0.9s cubic-bezier(0.55, 0, 0.25, 1) 0.6s forwards;
}
/* 兩端各畫一段、中間留空，空隙收到 0 就是兩邊在屋脊合攏；最後拿掉虛線，屋脊才是完整的尖角 */
@keyframes span {
  0%     { stroke-dasharray: 0 2 0; }
  99.9%  { stroke-dasharray: 1 0 1; }
  100%   { stroke-dasharray: none; }
}
.roof-bump {
  transform-box: fill-box;
  transform-origin: 50% 100%;
  animation: bump 0.45s ease-out 1.48s;
}
@keyframes bump { 40% { transform: scale(1.02, 1.06); } }

.tile {
  opacity: 0;
  transform-box: fill-box;
  transform-origin: center;
  animation: pop 0.5s cubic-bezier(0.34, 1.56, 0.64, 1) forwards;
}
@keyframes pop {
  from { opacity: 0; transform: scale(0.2); }
  to   { opacity: 1; transform: scale(1); }
}

.letter {
  opacity: 0;
  transform: translateY(56px);
  animation: rise 0.75s cubic-bezier(0.22, 1, 0.36, 1) forwards;
}
@keyframes rise { to { opacity: 1; transform: none; } }

@media (prefers-reduced-motion: reduce) {
  .grow, .roof, .roof-bump, .tile, .letter { animation: none; }
  .grow, .tile, .letter { opacity: 1; transform: none; }
  .roof { stroke-dasharray: none; }
}
</style>
