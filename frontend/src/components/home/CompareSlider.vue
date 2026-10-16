<script setup>
/**
 * 改造前後對比：左邊現況照片、右邊 AI 生成的效果圖，使用者自己拖曳分隔線。
 * 滑鼠／觸控用 Pointer Events（觸控只攔橫向拖曳，直向仍可捲頁）；
 * 把手是 role="slider"，可用方向鍵、Home／End 操作。進入畫面時示意性來回滑一次，碰到就停，減少動態時不播。
 */
import { ref, onMounted, onBeforeUnmount } from 'vue'
import { prefersReducedMotion } from '@/composables/useScrollProgress'
import before from '@/assets/home/before-living.jpg'
import industrial from '@/assets/home/after-industrial.jpg'
import luxury from '@/assets/home/after-luxury.jpg'

const AFTERS = [
  { id: 'industrial', name: '工業風', img: industrial },
  { id: 'luxury', name: '奢華風', img: luxury },
]

const clamp = (v) => Math.min(100, Math.max(0, v))
const pos = ref(50)            // 分隔線位置 %，左邊看到改造前、右邊看到改造後
const active = ref(0)
const dragging = ref(false)
const frame = ref(null)
let raf = 0
let io

function stopHint() { cancelAnimationFrame(raf) }
function setFromX(x) {
  const r = frame.value.getBoundingClientRect()
  pos.value = clamp(((x - r.left) / r.width) * 100)
}
function down(e) {
  stopHint()
  dragging.value = true
  frame.value.setPointerCapture(e.pointerId)
  setFromX(e.clientX)
}
function move(e) { if (dragging.value) setFromX(e.clientX) }
function up() { dragging.value = false }

function key(e) {
  const step = e.shiftKey ? 20 : 5
  const map = { ArrowLeft: -step, ArrowDown: -step, ArrowRight: step, ArrowUp: step }
  if (e.key in map) pos.value = clamp(pos.value + map[e.key])
  else if (e.key === 'Home') pos.value = 0
  else if (e.key === 'End') pos.value = 100
  else return
  stopHint()
  e.preventDefault()
}

// 示意：50 → 28 → 72 → 50
function hint() {
  const t0 = performance.now()
  const DUR = 2600
  const path = [50, 28, 72, 50]
  const step = (now) => {
    const k = Math.min(1, (now - t0) / DUR)
    const seg = k * (path.length - 1)
    const i = Math.min(path.length - 2, Math.floor(seg))
    const f = seg - i
    const ease = f < 0.5 ? 2 * f * f : 1 - Math.pow(-2 * f + 2, 2) / 2
    pos.value = path[i] + (path[i + 1] - path[i]) * ease
    if (k < 1) raf = requestAnimationFrame(step)
  }
  raf = requestAnimationFrame(step)
}

onMounted(() => {
  if (prefersReducedMotion()) return
  io = new IntersectionObserver(([e]) => {
    if (e.isIntersecting) { hint(); io.disconnect() }
  }, { threshold: 0.6 })
  io.observe(frame.value)
})
onBeforeUnmount(() => { stopHint(); io?.disconnect() })
</script>

<template>
  <section class="compare" aria-labelledby="compare-h">
    <div class="head">
      <p class="eyebrow">改造前後</p>
      <h2 id="compare-h">拖一拖，看看你的房間<br />會變成什麼樣</h2>
      <p class="lead">左邊是現況照片，右邊是 AI 依風格生成的效果圖。拖曳中間的把手比較，也可以用方向鍵。</p>
    </div>

    <div
      ref="frame"
      class="frame"
      :class="{ dragging }"
      @pointerdown="down"
      @pointermove="move"
      @pointerup="up"
      @pointercancel="up"
    >
      <img class="layer" :src="before" alt="" draggable="false" />
      <div class="after" :style="{ clipPath: `inset(0 0 0 ${pos}%)` }">
        <img
          v-for="(a, i) in AFTERS"
          :key="a.id"
          class="layer"
          :class="{ on: i === active }"
          :src="a.img"
          alt=""
          draggable="false"
        />
      </div>

      <span class="tag tag-l" aria-hidden="true">改造前</span>
      <span class="tag tag-r" aria-hidden="true">改造後・{{ AFTERS[active].name }}</span>

      <div
        class="handle"
        :style="{ left: pos + '%' }"
        role="slider"
        tabindex="0"
        aria-label="改造前後比較"
        aria-valuemin="0"
        aria-valuemax="100"
        :aria-valuenow="Math.round(pos)"
        :aria-valuetext="`改造後的畫面顯示 ${Math.round(100 - pos)}%`"
        @keydown="key"
      >
        <span class="knob" aria-hidden="true">
          <svg viewBox="0 0 24 24"><path d="M9 7l-5 5 5 5M15 7l5 5-5 5" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" /></svg>
        </span>
      </div>
    </div>

    <div class="chips" role="group" aria-label="選擇改造後的風格">
      <button
        v-for="(a, i) in AFTERS"
        :key="a.id"
        type="button"
        class="chip"
        :aria-pressed="i === active"
        @click="active = i"
      >{{ a.name }}</button>
    </div>
    <p class="note">示範：以內建的示範房間照片生成，風格為工業與奢華；實際結果會依你的空間與描述而不同。</p>
  </section>
</template>

<style scoped>
.compare {
  width: min(1040px, calc(100vw - 3rem));
  margin: 0 auto;
  padding: clamp(3rem, 7vw, 6rem) 0;
  text-align: center;
}
.eyebrow { margin: 0 0 0.6rem; font-size: 0.82rem; letter-spacing: 0.18em; color: var(--db-accent-ink); }
h2 {
  margin: 0 0 0.9rem;
  font-family: var(--db-font-display);
  font-style: italic;
  font-weight: 500;
  font-size: clamp(1.8rem, 3.4vw, 2.7rem);
  line-height: 1.3;
  text-wrap: balance;
  color: var(--db-text);
}
.lead { max-width: 34rem; margin: 0 auto 2rem; line-height: 1.85; color: var(--db-text-soft); }

.frame {
  position: relative;
  aspect-ratio: 16 / 9;
  border-radius: var(--db-radius-card);
  overflow: hidden;
  background: var(--db-accent-soft);
  box-shadow: var(--db-shadow-card);
  touch-action: pan-y;
  user-select: none;
  -webkit-user-select: none;
  cursor: var(--cur-drag, ew-resize);
}
.layer { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: fill; pointer-events: none; }
.after { position: absolute; inset: 0; }
.after .layer { object-fit: cover; opacity: 0; transition: opacity 0.5s ease; }
.after .layer.on { opacity: 1; }

.tag {
  position: absolute;
  bottom: 1rem;
  padding: 0.3rem 0.9rem;
  border-radius: var(--db-radius-pill);
  background: rgba(20, 18, 14, 0.62);
  color: #fff;
  font-family: var(--db-font-display);
  font-size: 0.95rem;
  backdrop-filter: blur(6px);
  pointer-events: none;
}
.tag-l { left: 1rem; }
.tag-r { right: 1rem; }

.handle {
  position: absolute;
  top: 0;
  bottom: 0;
  width: 44px;
  margin-left: -22px;
  display: grid;
  place-items: center;
  outline: none;
}
.handle::before {
  content: '';
  position: absolute;
  top: 0;
  bottom: 0;
  left: 50%;
  width: 2px;
  margin-left: -1px;
  background: #fff;
  box-shadow: 0 0 0 1px rgba(20, 18, 14, 0.25), 0 0 14px rgba(0, 0, 0, 0.3);
}
.knob {
  position: relative;
  display: grid;
  place-items: center;
  width: 44px;
  height: 44px;
  border-radius: 50%;
  background: #fff;
  color: var(--db-text);
  box-shadow: 0 4px 14px rgba(20, 18, 14, 0.35);
  transition: transform 0.15s;
}
.knob svg { width: 22px; height: 22px; }
.frame.dragging .knob { transform: scale(1.1); }
.handle:focus-visible .knob { outline: 3px solid var(--db-accent-ink); outline-offset: 3px; }

.chips { display: flex; justify-content: center; gap: 0.5rem; margin-top: 1.1rem; }
.chip {
  min-height: 44px;
  padding: 0 1.3rem;
  border: 1.5px solid var(--db-accent);
  border-radius: var(--db-radius-pill);
  background: transparent;
  color: var(--db-text);
  font-family: var(--db-font-display);
  font-size: 1rem;
  transition: background 0.18s, color 0.18s;
}
.chip:hover { background: var(--db-accent-soft); }
.chip[aria-pressed='true'] { background: var(--db-accent); color: var(--db-on-accent); }
.chip:focus-visible { outline: 3px solid var(--db-accent-ink); outline-offset: 2px; }
.note { margin: 0.9rem 0 0; font-size: 0.82rem; line-height: 1.7; color: var(--db-text-soft); }

@media (prefers-reduced-motion: reduce) {
  .after .layer, .knob { transition: none; }
}
</style>
