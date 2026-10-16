<script setup>
/**
 * 報價小票：進入畫面時品項逐行浮現、總價數字滾動加總。
 * 品項與價格皆為示意，不是真實商品或報價；減少動態時直接顯示結果。
 */
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { prefersReducedMotion } from '@/composables/useScrollProgress'

const ITEMS = [
  { n: '三人座布沙發', p: 12900 },
  { n: '圓形茶几', p: 3490 },
  { n: '電視櫃', p: 5990 },
  { n: '落地立燈', p: 1790 },
  { n: '長毛地毯', p: 2490 },
  { n: '大型盆栽', p: 690 },
]
const TOTAL = ITEMS.reduce((s, i) => s + i.p, 0)
const fmt = (n) => `NT$ ${Math.round(n).toLocaleString('zh-TW')}`

const root = ref(null)
const shown = ref(prefersReducedMotion() ? ITEMS.length : 0)
const total = ref(prefersReducedMotion() ? TOTAL : 0)
const done = computed(() => shown.value >= ITEMS.length)
let io
let raf = 0
const timers = []

function play() {
  ITEMS.forEach((_, i) => timers.push(setTimeout(() => { shown.value = i + 1 }, 320 * (i + 1))))
  timers.push(setTimeout(() => {
    const t0 = performance.now()
    const step = (now) => {
      const k = Math.min(1, (now - t0) / 1000)
      total.value = TOTAL * (1 - Math.pow(1 - k, 3))
      if (k < 1) raf = requestAnimationFrame(step)
    }
    raf = requestAnimationFrame(step)
  }, 320 * ITEMS.length + 200))
}

onMounted(() => {
  if (prefersReducedMotion()) return
  io = new IntersectionObserver(([e]) => {
    if (e.isIntersecting) { play(); io.disconnect() }
  }, { threshold: 0.4 })
  io.observe(root.value)
})
onBeforeUnmount(() => { io?.disconnect(); timers.forEach(clearTimeout); cancelAnimationFrame(raf) })
</script>

<template>
  <div ref="root" class="receipt" role="group" aria-label="範例報價單">
    <p class="tag">範例報價（示意）</p>
    <ul>
      <li v-for="(it, i) in ITEMS" :key="it.n" :class="{ on: i < shown }">
        <span class="n">{{ it.n }}</span>
        <span class="dots" aria-hidden="true"></span>
        <span class="p">{{ fmt(it.p) }}</span>
      </li>
    </ul>
    <div class="sum" :class="{ on: done }">
      <span>合計</span>
      <strong>{{ fmt(total) }}</strong>
    </div>
    <p class="foot">設計完成後，按下「取得家具報價」即可依你的家具清單產生。</p>
  </div>
</template>

<style scoped>
.receipt {
  position: relative;
  width: 100%;
  padding: 1.5rem 1.4rem 1.6rem;
  background: #fffdf8;
  color: var(--db-text);
  box-shadow: 0 10px 28px rgba(28, 24, 18, 0.16);
  /* 鋸齒邊 */
  --z: 8px;
  -webkit-mask: conic-gradient(from -45deg at bottom, #0000, #000 1deg 89deg, #0000 90deg) bottom / calc(2 * var(--z)) var(--z) repeat-x,
                linear-gradient(#000 0 0) top / 100% calc(100% - var(--z)) no-repeat;
  mask: conic-gradient(from -45deg at bottom, #0000, #000 1deg 89deg, #0000 90deg) bottom / calc(2 * var(--z)) var(--z) repeat-x,
        linear-gradient(#000 0 0) top / 100% calc(100% - var(--z)) no-repeat;
}
.tag {
  margin: 0 0 0.9rem;
  font-size: 0.78rem;
  letter-spacing: 0.16em;
  color: var(--db-accent-ink);
}
ul { list-style: none; margin: 0; padding: 0; display: grid; gap: 0.55rem; font-family: var(--db-font-num); }
li {
  display: flex;
  align-items: baseline;
  gap: 0.5rem;
  font-size: 0.92rem;
  opacity: 0;
  transform: translateY(6px);
  transition: opacity 0.3s, transform 0.3s;
}
li.on { opacity: 1; transform: none; }
.n { font-family: var(--db-font-body); }
.dots { flex: 1; border-bottom: 1.5px dotted var(--db-accent); transform: translateY(-3px); }
.p { font-variant-numeric: tabular-nums; }
.sum {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  margin-top: 1rem;
  padding-top: 0.8rem;
  border-top: 2px solid var(--db-text);
}
.sum span { font-family: var(--db-font-display); font-size: 1.05rem; }
.sum strong { font-family: var(--db-font-num); font-size: 1.5rem; font-variant-numeric: tabular-nums; }
.foot { margin: 1rem 0 0; font-size: 0.8rem; line-height: 1.7; color: var(--db-text-soft); }

@media (prefers-reduced-motion: reduce) {
  li { opacity: 1; transform: none; transition: none; }
}
</style>
