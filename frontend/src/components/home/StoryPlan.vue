<script setup>
/**
 * 捲動敘事：說出想法 → 畫出尺寸精準的平面圖 → 風水與動線檢查 → 渲染成圖。
 * 平面圖用的是系統實際產出的 CAD 平面圖（SVG，assets/home/cad-plan.svg）：
 * 隨捲動依序顯示外牆、各房間、門窗，最後才標出尺寸與面積。
 * 進度 p 由 useScrollProgress 提供；減少動態時 p 固定為 1（直接顯示最終畫面，區塊也不再撐高）。
 */
import { ref, computed, watch, onMounted } from 'vue'
import { useScrollProgress, seg } from '@/composables/useScrollProgress'
import renderImg from '@/assets/home/modern.jpg'
import cadSvg from '@/assets/home/cad-plan.svg?raw'

const STEPS = [
  { t: '說出你的想法', d: '用一段描述，或一張現況照片開始，例如「木質感、採光充足的客廳」。' },
  { t: '畫出尺寸精準的平面圖', d: '填房型與坪數，自動生成標好牆體、門窗、尺寸與面積的平面圖，家具也依空間大小擺好。' },
  { t: '風水與動線檢查', d: '開門見灶、鏡子照床這類常見禁忌，會在排版時自動避開。' },
  { t: '渲染成圖', d: '依版面生成寫實的效果圖，再挑風格、微調細節。' },
]
const PROMPT = '木質感、採光充足的客廳'

const root = ref(null)
const p = useScrollProgress(root)

const active = computed(() => (p.value < 0.2 ? 0 : p.value < 0.52 ? 1 : p.value < 0.72 ? 2 : 3))

// 第 1 幕：輸入描述
const typed = computed(() => PROMPT.slice(0, Math.round(seg(p.value, 0.01, 0.15) * PROMPT.length)))
const promptStyle = computed(() => ({ opacity: 1 - seg(p.value, 0.18, 0.24) }))
const chipStyle = computed(() => ({ opacity: seg(p.value, 0.12, 0.17) }))

// 第 2 幕：CAD 平面圖（逐一顯示 SVG 內的元素）
const cad = ref(null)
let parts = null
const setOp = (els, v) => { for (const e of els) e.style.opacity = v }
function applyCad() {
  if (!parts) return
  const k = (a, b) => seg(p.value, a, b)
  setOp([parts.wall], k(0.2, 0.25))
  parts.wall.style.fillOpacity = k(0.3, 0.48)
  parts.rooms.forEach((r, i) => setOp([r], k(0.24 + i * 0.025, 0.285 + i * 0.025)))
  setOp(parts.openings, k(0.42, 0.47))
  setOp(parts.dims, k(0.46, 0.52))
}
onMounted(() => {
  const svg = cad.value?.querySelector('svg')
  if (!svg) return
  const c = [...svg.children]
  // 結構：0 defs、1 背景、2 外牆、3–9 房間、10–40 門窗、41–53 尺寸標註／指北針／比例尺／總面積
  parts = { wall: c[2], rooms: c.slice(3, 10), openings: c.slice(10, 41), dims: c.slice(41) }
  applyCad()
})
watch(p, applyCad)
const cadStyle = computed(() => ({ opacity: seg(p.value, 0.18, 0.22) * (1 - seg(p.value, 0.7, 0.78)) }))

// 第 2、3 幕的標籤
const sizeTags = computed(() => ({ opacity: seg(p.value, 0.46, 0.5) * (1 - seg(p.value, 0.56, 0.6)) }))
const checkTags = computed(() => ({ opacity: seg(p.value, 0.6, 0.66) * (1 - seg(p.value, 0.7, 0.74)) }))
const flowStyle = computed(() => ({ opacity: seg(p.value, 0.58, 0.64) * (1 - seg(p.value, 0.7, 0.76)) }))

// 第 4 幕：效果圖
const renderStyle = computed(() => {
  const k = seg(p.value, 0.72, 0.92)
  return { opacity: k, transform: `scale(${1.04 - 0.04 * k})` }
})
</script>

<template>
  <section ref="root" class="story" aria-labelledby="story-h">
    <div class="sticky">
      <div class="copy">
        <p class="eyebrow">從一句話到一張圖</p>
        <h2 id="story-h">你說想法，<br />我們幫你做設計</h2>
        <ol class="steps">
          <li v-for="(s, i) in STEPS" :key="s.t" :class="{ active: i === active, done: i < active }">
            <span class="num">0{{ i + 1 }}</span>
            <div>
              <strong>{{ s.t }}</strong>
              <p>{{ s.d }}</p>
            </div>
          </li>
        </ol>
      </div>

      <div class="stage" aria-hidden="true">
        <div class="prompt" :style="promptStyle">
          <span class="label">描述你理想中的空間…</span>
          <span class="typed">{{ typed }}<i class="caret"></i></span>
          <span class="chips" :style="chipStyle"><b>客廳</b><b>32 坪</b><b>避開風水禁忌</b></span>
        </div>

        <div ref="cad" class="cad" :style="cadStyle" v-html="cadSvg"></div>

        <svg class="flow" viewBox="0 0 765 650" preserveAspectRatio="xMidYMid meet" :style="flowStyle" focusable="false">
          <path d="M297 100C297 170 300 240 340 310S352 420 342 520" />
          <circle cx="297" cy="100" r="6" />
          <circle cx="342" cy="520" r="6" />
        </svg>

        <div class="tags" :style="sizeTags"><b>牆體隔間</b><b>門窗位置</b><b>尺寸與面積標註</b></div>
        <div class="tags" :style="checkTags"><b>動線順暢</b><b>門不對鏡</b><b>開門不見床</b></div>

        <img class="render" :src="renderImg" alt="" loading="lazy" :style="renderStyle" />
      </div>
    </div>
  </section>
</template>

<style scoped>
.story { height: 360vh; background: var(--db-paper); }
.sticky {
  position: sticky;
  top: 0;
  height: 100vh;
  display: grid;
  grid-template-columns: minmax(0, 5fr) minmax(0, 7fr);
  align-items: center;
  gap: clamp(1.5rem, 5vw, 4rem);
  width: min(1180px, calc(100vw - 3rem));
  margin: 0 auto;
}

.eyebrow { margin: 0 0 0.6rem; font-size: 0.82rem; letter-spacing: 0.18em; color: var(--db-accent-ink); }
h2 {
  margin: 0 0 1.75rem;
  font-family: var(--db-font-display);
  font-style: italic;
  font-weight: 500;
  font-size: clamp(1.9rem, 3.6vw, 2.9rem);
  line-height: 1.3;
  text-wrap: balance;
  color: var(--db-text);
}

.steps { list-style: none; margin: 0; padding: 0; display: grid; gap: 0.35rem; }
.steps li {
  display: flex;
  gap: 1rem;
  padding: 0.7rem 0.9rem;
  border-left: 2px solid var(--db-accent-soft);
  opacity: 0.5;
  transition: opacity 0.35s, border-color 0.35s, background 0.35s;
}
.steps li.done { opacity: 0.7; }
.steps li.active { opacity: 1; border-color: var(--db-accent-ink); background: rgba(255, 255, 255, 0.55); }
.num { font-family: var(--db-font-num); font-size: 0.85rem; color: var(--db-accent-ink); padding-top: 0.15rem; }
.steps strong { font-family: var(--db-font-display); font-weight: 500; font-size: 1.1rem; color: var(--db-text); }
.steps p { margin: 0.2rem 0 0; font-size: 0.9rem; line-height: 1.7; color: var(--db-text-soft); }

.stage {
  position: relative;
  aspect-ratio: 16 / 10;
  border-radius: var(--db-radius-card);
  background: #fff;
  box-shadow: var(--db-shadow-card);
  overflow: hidden;
}
.stage > * { position: absolute; }

.prompt {
  left: 8%;
  right: 8%;
  top: 50%;
  display: grid;
  gap: 0.5rem;
  padding: 1.1rem 1.3rem;
  border: 1px solid var(--db-accent);
  border-radius: var(--db-radius-chip);
  background: var(--db-paper);
  transform: translateY(-50%);
}
.label { font-size: 0.78rem; letter-spacing: 0.1em; color: var(--db-accent-ink); }
.typed { min-height: 1.7em; font-size: clamp(1rem, 2vw, 1.35rem); color: var(--db-text); }
.caret { display: inline-block; width: 2px; height: 1.1em; margin-left: 2px; background: var(--db-text); vertical-align: -0.15em; }
.chips { display: flex; flex-wrap: wrap; gap: 0.4rem; margin-top: 0.2rem; }
.chips b, .tags b {
  padding: 0.25rem 0.8rem;
  border-radius: var(--db-radius-pill);
  background: var(--db-accent-soft);
  color: var(--db-accent-ink);
  font-size: 0.82rem;
  font-weight: 500;
}

.cad { inset: 0; }
.cad :deep(svg) { display: block; width: 100%; height: 100%; }

.flow { inset: 0; width: 100%; height: 100%; pointer-events: none; }
.flow path { fill: none; stroke: #2e8b57; stroke-width: 4; stroke-dasharray: 10 8; stroke-linecap: round; }
.flow circle { fill: #2e8b57; }

.tags { left: 0; right: 0; bottom: 0.9rem; display: flex; justify-content: center; flex-wrap: wrap; gap: 0.5rem; }
.tags b { background: rgba(255, 255, 255, 0.95); box-shadow: var(--db-shadow-soft); color: var(--db-text); }

.render { inset: 0; width: 100%; height: 100%; object-fit: cover; will-change: opacity, transform; }

@media (max-width: 860px) {
  .sticky { grid-template-columns: 1fr; align-content: center; gap: 1rem; }
  h2 { margin-bottom: 0.9rem; font-size: 1.7rem; }
  .steps li:not(.active) p { display: none; }
  .steps li { padding: 0.45rem 0.7rem; }
  .stage { aspect-ratio: 4 / 3; }
  .tags b { font-size: 0.72rem; padding: 0.2rem 0.6rem; }
}

/* 減少動態：不黏住、不捲動演出，直接顯示最終畫面 */
@media (prefers-reduced-motion: reduce) {
  .story { height: auto; padding: 4rem 0; }
  .sticky { position: static; height: auto; }
  .steps li { opacity: 1; transition: none; }
  .steps li p { display: block; }
}
</style>
