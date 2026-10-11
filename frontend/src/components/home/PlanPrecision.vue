<script setup>
/**
 * 格局精準：拉好平面圖（2D）→ 3D 同步 → 渲染成品，三者是同一份家具座標。
 *
 * 2D 與 3D 都可以拖曳家具，另一邊即時跟著動（3D 用真的 LayoutPreview3D，相機與生圖的投影相機相同）；
 * 滑過任一邊的家具，其他兩邊也會標出同一件。
 *
 * 資料取自同一次真實排版與生成（客廳 4.5 × 5.0 m，相機站在下方牆邊往上看）：
 * 座標是 scene_graph 轉成相機視角後的結果；`box` 是我逐件對照成品圖量出的位置（佔畫面 %）。
 * 收納櫃在鏡頭外，沒有 box。拖動之後家具位置就和成品圖不同了，成品圖會標示「需重新渲染」，示範不會真的重生。
 */
import { ref, computed, onMounted, onBeforeUnmount, defineAsyncComponent } from 'vue'
import { prefersReducedMotion } from '@/composables/useScrollProgress'
import renderImg from '@/assets/home/plan-render.jpg'

// three.js 很大，捲到附近才下載
const LayoutPreview3D = defineAsyncComponent(() => import('@/components/LayoutPreview3D.vue'))

const ROOM = { w: 450, d: 500 }   // cm
// x、y、w、h 為佔房間的比例；box = [左, 上, 寬, 高]，佔成品圖的 %
const BASE = [
  { id: 'tv_unit_1', type: 'tv_unit', name: '電視櫃', x: 0.627, y: 0.58, w: 0.1, h: 0.4, box: [74, 52, 26, 38] },
  { id: 'sofa_1', type: 'sofa', name: '三人座沙發', x: 0.186, y: 0.237, w: 0.18, h: 0.5, box: [7, 45, 35, 50] },
  { id: 'coffee_table_1', type: 'coffee_table', name: '茶几', x: 0.532, y: 0.232, w: 0.2, h: 0.24, box: [44, 61, 17, 17] },
  { id: 'armchair_1', type: 'armchair', name: '單人椅', x: 0.8, y: 0.02, w: 0.18, h: 0.18, box: [61, 40, 14, 22] },
  { id: 'side_table_1', type: 'side_table', name: '邊桌', x: 0.02, y: 0.88, w: 0.1, h: 0.11, box: [5, 72, 23, 28] },
  { id: 'cabinet_6', type: 'cabinet', name: '收納櫃', x: 0.329, y: 0.84, w: 0.07, h: 0.14, box: null },
]
const META = Object.fromEntries(BASE.map((f) => [f.id, f]))
const LINKED = BASE.filter((f) => f.box)
const clone = () => BASE.map(({ id, type, x, y, w, h }) => ({ id, type, x, y, w, h, rotation: 0 }))

const CHECKS = ['家具互不重疊', '家具間距符合規範', '人體工學尺寸', '視覺焦點明確']
const SCORE = 88

const placements = ref(clone())
const drag = ref(null)      // 2D 拖曳中的即時位置 { id, x, y }
const edited = ref(false)

const shapes = computed(() => placements.value.map((p) => {
  const q = drag.value?.id === p.id ? { ...p, x: drag.value.x, y: drag.value.y } : p
  return { ...q, name: META[p.id].name,
    px: Math.round(q.x * ROOM.w), py: Math.round(q.y * ROOM.d), pw: Math.round(q.w * ROOM.w), ph: Math.round(q.h * ROOM.d) }
}))
const sizeOf = (id) => { const s = shapes.value.find((q) => q.id === id); return `${s.pw}×${s.ph}` }

// 給 3D 的資料：和後端 /api/generate 回傳的格式相同
const sceneGraph = computed(() => ({ furniture_placements: placements.value.map((p) => ({ ...p })) }))
const renderConfig = { camera: { hfov_deg: 65, eye_height: 1.4, setback: 1.2, pitch_deg: -8 } }
const spaceInfo = { estimated_size: { width: ROOM.w / 100, depth: ROOM.d / 100 } }

const shown = ref(0)     // 已落位的家具數
const ticked = ref(0)    // 已打勾的檢查數
const active = ref('')   // 目前對應中的家具 id
const show3d = ref(false)
const root = ref(null)
const svg = ref(null)
const reduced = prefersReducedMotion()
let io, io3d
let hovering = false
let cycling = false
const timers = []
const wait = (ms) => new Promise((r) => timers.push(setTimeout(r, ms)))

async function cycle() {
  cycling = true
  for (let i = 0; cycling; i = (i + 1) % LINKED.length) {
    if (!hovering) active.value = LINKED[i].id
    await wait(2200)
  }
}
async function play() {
  for (let i = 1; i <= BASE.length; i++) { await wait(380); shown.value = i }
  await wait(400)
  for (let i = 1; i <= CHECKS.length; i++) { await wait(340); ticked.value = i }
  await wait(400)
  cycle()
}
const enter = (id) => { hovering = true; active.value = id }
const leave = () => { hovering = false }

/* ── 2D 拖曳 ── */
let dragInfo = null
function toNorm(e) {
  const pt = svg.value.createSVGPoint()
  pt.x = e.clientX; pt.y = e.clientY
  const q = pt.matrixTransform(svg.value.getScreenCTM().inverse())
  return { x: q.x / ROOM.w, y: q.y / ROOM.d }
}
function down(e, s) {
  const n = toNorm(e)
  dragInfo = { id: s.id, dx: n.x - s.x, dy: n.y - s.y, w: s.w, h: s.h }
  drag.value = { id: s.id, x: s.x, y: s.y }
  hovering = true
  e.currentTarget.setPointerCapture(e.pointerId)
}
function move(e) {
  if (!dragInfo) return
  const n = toNorm(e)
  const clamp = (v, max) => Math.min(max, Math.max(0, v))
  drag.value = { id: dragInfo.id, x: clamp(n.x - dragInfo.dx, 1 - dragInfo.w), y: clamp(n.y - dragInfo.dy, 1 - dragInfo.h) }
}
function up() {
  if (!dragInfo) return
  const { id, x, y } = drag.value
  placements.value = placements.value.map((p) => (p.id === id ? { ...p, x: Number(x.toFixed(4)), y: Number(y.toFixed(4)) } : p))
  edited.value = true
  dragInfo = null
  drag.value = null
}

/* ── 3D 拖曳回傳 ── */
function onLayout3d(items) {
  placements.value = items.map(({ id, type, x, y, w, h, rotation }) => ({ id, type, x, y, w, h, rotation: rotation || 0 }))
  edited.value = true
}
function reset() { placements.value = clone(); edited.value = false }

onMounted(() => {
  io3d = new IntersectionObserver(([e]) => { if (e.isIntersecting) { io3d.disconnect(); show3d.value = true } }, { rootMargin: '500px 0px' })
  io3d.observe(root.value)
  if (reduced) { shown.value = BASE.length; ticked.value = CHECKS.length; active.value = 'sofa_1'; return }
  io = new IntersectionObserver(([e]) => { if (e.isIntersecting) { io.disconnect(); play() } }, { threshold: 0.3 })
  io.observe(root.value)
})
onBeforeUnmount(() => { cycling = false; io?.disconnect(); io3d?.disconnect(); timers.forEach(clearTimeout) })
</script>

<template>
  <section ref="root" class="pp" aria-labelledby="pp-h">
    <header class="head">
      <p class="eyebrow">格局精準</p>
      <h2 id="pp-h">拉好平面圖，3D 與成品圖跟著對上</h2>
      <p class="lead">房間以公分為單位建好，家具依尺寸落位。2D 與 3D 是同一份資料，拖動任一邊都會同步，最後一鍵渲染成圖。</p>
    </header>

    <div class="top">
      <figure class="plan">
        <svg ref="svg" :viewBox="`-34 -34 ${ROOM.w + 68} ${ROOM.d + 96}`" role="group" aria-label="客廳平面圖，可拖動家具，標示各家具的公分尺寸">
          <rect x="0" y="0" :width="ROOM.w" :height="ROOM.d" class="room" />
          <g class="dim" aria-hidden="true">
            <line x1="0" y1="-16" :x2="ROOM.w" y2="-16" /><line x1="0" y1="-22" x2="0" y2="-10" /><line :x1="ROOM.w" y1="-22" :x2="ROOM.w" y2="-10" />
            <text :x="ROOM.w / 2" y="-22" text-anchor="middle">{{ ROOM.w }} cm</text>
            <line :x1="-16" y1="0" :x2="-16" :y2="ROOM.d" /><line x1="-22" y1="0" x2="-10" y2="0" /><line x1="-22" :y1="ROOM.d" x2="-10" :y2="ROOM.d" />
            <text :x="-24" :y="ROOM.d / 2" text-anchor="middle" :transform="`rotate(-90 -24 ${ROOM.d / 2})`">{{ ROOM.d }} cm</text>
          </g>
          <g class="cam" aria-hidden="true">
            <path :d="`M ${ROOM.w / 2} ${ROOM.d + 30} L ${ROOM.w / 2 - 150} ${ROOM.d - 150} L ${ROOM.w / 2 + 150} ${ROOM.d - 150} Z`" />
            <circle :cx="ROOM.w / 2" :cy="ROOM.d + 30" r="9" />
            <text :x="ROOM.w / 2 + 16" :y="ROOM.d + 34">拍攝位置</text>
          </g>
          <g
            v-for="(s, i) in shapes" :key="s.id" class="item"
            :class="{ on: shown > i, hot: active === s.id, dragging: drag && drag.id === s.id }"
            @pointerenter="enter(s.id)" @pointerleave="leave"
            @pointerdown="down($event, s)" @pointermove="move" @pointerup="up" @pointercancel="up"
          >
            <rect :x="s.px" :y="s.py" :width="s.pw" :height="s.ph" rx="4" />
            <text :x="s.px + s.pw / 2" :y="s.py + s.ph / 2 - 3" text-anchor="middle" class="nm">{{ s.name }}</text>
            <text :x="s.px + s.pw / 2" :y="s.py + s.ph / 2 + 13" text-anchor="middle" class="sz">{{ s.pw }}×{{ s.ph }}</text>
          </g>
        </svg>
        <figcaption><b>① 2D 平面圖</b>　拖動家具試試看</figcaption>
      </figure>

      <div class="sync" aria-hidden="true"><span>⇄</span><em>即時同步</em></div>

      <figure class="three">
        <div class="stage3d">
          <LayoutPreview3D
            v-if="show3d"
            :scene-graph="sceneGraph" :render-config="renderConfig" :space-info="spaceInfo"
            :highlight-id="active" editable
            @layout-changed="onLayout3d" @hover-item="(id) => (id ? enter(id) : leave())"
          />
        </div>
        <figcaption><b>② 3D 預覽</b>　同一份資料，視角與生圖相同</figcaption>
      </figure>
    </div>

    <div class="down" aria-hidden="true"><span>↓</span> 一鍵渲染</div>

    <figure class="shot">
      <div class="frame" :class="{ stale: edited }">
        <img :src="renderImg" alt="依這份平面圖生成的客廳成品圖" draggable="false" />
        <template v-if="!edited">
          <span
            v-for="f in LINKED" :key="f.id" class="hit" :class="{ hot: active === f.id, edge: f.box[0] + f.box[2] >= 98 }"
            :style="{ left: f.box[0] + '%', top: f.box[1] + '%', width: f.box[2] + '%', height: f.box[3] + '%' }"
            @pointerenter="enter(f.id)" @pointerleave="leave"
          ><i>{{ f.name }}　{{ sizeOf(f.id) }} cm</i></span>
        </template>
        <p v-else class="stale-tip" role="status">你調整了家具位置，重新渲染後成品圖才會更新（示範不會重新生成）</p>
      </div>
      <figcaption><b>③ 渲染成品</b>　依同一份平面圖生成（收納櫃在鏡頭外）
        <button v-if="edited" type="button" class="reset" @click="reset">還原範例</button>
      </figcaption>
    </figure>

    <div class="verdict" :class="{ stale: edited }">
      <ul class="checks" aria-label="排版檢查（範例結果）">
        <li v-for="(c, i) in CHECKS" :key="c" :class="{ on: ticked > i }">
          <svg viewBox="0 0 20 20" aria-hidden="true"><circle cx="10" cy="10" r="9" /><path d="M5.5 10.5l3 3 6-7" /></svg>
          {{ c }}
        </li>
      </ul>
      <p class="score" :class="{ on: ticked >= CHECKS.length }">排版評分 <b>{{ SCORE }}</b> / 100</p>
    </div>
    <p class="note">示範：取自一次實際排版與生成的結果{{ edited ? '；你調整過位置，檢查與評分要重新排版才會更新' : '' }}。</p>
  </section>
</template>

<style scoped>
.pp { width: min(1100px, calc(100vw - 3rem)); margin: 0 auto; padding: clamp(2rem, 5vw, 4rem) 0; }
.head { text-align: center; margin-bottom: clamp(1.5rem, 3vw, 2.2rem); }
.eyebrow { margin: 0 0 0.6rem; font-size: 0.82rem; letter-spacing: 0.14em; color: var(--db-accent-ink); }
h2 { margin: 0 0 0.9rem; font-family: var(--db-font-display); font-style: italic; font-weight: 500; font-size: clamp(1.7rem, 3.2vw, 2.5rem); line-height: 1.35; text-wrap: balance; color: var(--db-text); }
.lead { max-width: 36rem; margin: 0 auto; line-height: 1.85; color: var(--db-text-soft); }

/* 2D 與 3D 等高：平面圖 viewBox 比例約 0.87，3D 為 4:3，所以 2D : 3D ≈ 1 : 1.5 */
.top { display: grid; grid-template-columns: minmax(0, 1fr) auto minmax(0, 1.5fr); gap: 0.6rem; align-items: start; }
.plan, .three, .shot { margin: 0; display: flex; flex-direction: column; gap: 0.6rem; min-width: 0; }
.plan svg { display: block; width: 100%; height: auto; background: #fff; padding: 0.4rem; box-sizing: border-box; border-radius: var(--db-radius-card); box-shadow: var(--db-shadow-card); touch-action: none; user-select: none; }
.stage3d { min-height: 12rem; border-radius: var(--db-radius-card); box-shadow: var(--db-shadow-card); overflow: hidden; background: #f1f0ee; }
figcaption { font-size: 0.82rem; color: var(--db-text-soft); text-align: center; }
figcaption b { color: var(--db-text); font-weight: 600; }

.sync { align-self: center; display: flex; flex-direction: column; align-items: center; gap: 0.3rem; color: var(--db-accent-ink); }
.sync span { font-size: 1.6rem; line-height: 1; }
.sync em { font-style: normal; font-size: 0.72rem; letter-spacing: 0.1em; writing-mode: vertical-rl; }
.down { margin: 0.9rem 0; text-align: center; font-size: 0.9rem; color: var(--db-accent-ink); letter-spacing: 0.08em; }
.down span { font-size: 1.2rem; margin-right: 0.3rem; }

.room { fill: #fbfaf6; stroke: var(--db-text); stroke-width: 6; }
.dim line { stroke: var(--db-placeholder); stroke-width: 1.2; }
.dim text { fill: var(--db-text-soft); font-size: 12px; }
.cam path { fill: rgba(28, 24, 18, 0.05); stroke: var(--db-placeholder); stroke-width: 1; stroke-dasharray: 4 4; }
.cam circle { fill: var(--db-text); }
.cam text { fill: var(--db-text-soft); font-size: 12px; }
.item { opacity: 0; transition: opacity 0.4s; cursor: grab; }
.item.on { opacity: 1; }
.item.dragging { cursor: grabbing; }
.item rect { fill: var(--db-accent-soft); stroke: var(--db-text); stroke-width: 1.2; transition: fill 0.2s, stroke-width 0.2s; }
.item.hot rect, .item.dragging rect { fill: #fff; stroke-width: 3; }
.nm { font-size: 13px; fill: var(--db-text); font-weight: 600; pointer-events: none; }
.sz { font-size: 11px; fill: var(--db-text-soft); font-variant-numeric: tabular-nums; pointer-events: none; }

.shot { max-width: 760px; margin: 0 auto; }
.frame { position: relative; overflow: hidden; aspect-ratio: 16 / 9; background: var(--db-accent-soft); border-radius: var(--db-radius-card); box-shadow: var(--db-shadow-card); }
.frame img { display: block; width: 100%; height: 100%; object-fit: cover; transition: filter 0.3s, opacity 0.3s; }
.frame.stale img { filter: grayscale(0.7) blur(1px); opacity: 0.6; }
.stale-tip { position: absolute; inset: 0; display: grid; place-items: center; margin: 0; padding: 1rem; text-align: center; font-size: 0.95rem; line-height: 1.7; color: var(--db-text); }
.hit { position: absolute; border: 2px solid transparent; border-radius: 8px; transition: border-color 0.2s, background 0.2s; cursor: pointer; }
.hit i { position: absolute; left: 4px; top: 4px; padding: 0.15rem 0.5rem; border-radius: 999px; background: var(--db-text); color: #fff; font-size: 0.72rem; font-style: normal; white-space: nowrap; opacity: 0; transform: translateY(-3px); transition: opacity 0.2s, transform 0.2s; pointer-events: none; }
.hit.edge i { left: auto; right: 4px; }
.hit.hot { border-color: #fff; background: rgba(255, 255, 255, 0.14); box-shadow: 0 0 0 2px var(--db-text); }
.hit.hot i { opacity: 1; transform: none; }
.reset { margin-left: 0.6rem; padding: 0.1rem 0.7rem; border: 1px solid var(--db-text-soft); border-radius: 999px; background: none; font: inherit; font-size: 0.78rem; color: var(--db-text); cursor: pointer; }

.verdict { display: flex; flex-wrap: wrap; align-items: center; justify-content: center; gap: 0.6rem 2rem; margin-top: 1.4rem; transition: opacity 0.3s; }
.verdict.stale { opacity: 0.45; }
.checks { list-style: none; margin: 0; padding: 0; display: flex; flex-wrap: wrap; justify-content: center; gap: 0.5rem 1.5rem; }
.checks li { display: flex; align-items: center; gap: 0.5rem; color: var(--db-text-soft); transition: color 0.3s; }
.checks svg { width: 20px; height: 20px; fill: none; stroke: var(--db-placeholder); stroke-width: 1.5; stroke-linecap: round; stroke-linejoin: round; transition: stroke 0.3s, fill 0.3s; }
.checks svg path { stroke-dasharray: 16; stroke-dashoffset: 16; transition: stroke-dashoffset 0.4s 0.1s; }
.checks li.on { color: var(--db-text); }
.checks li.on svg circle { fill: var(--db-text); stroke: var(--db-text); }
.checks li.on svg path { stroke: #fff; stroke-dashoffset: 0; }
.score { margin: 0; color: var(--db-text-soft); opacity: 0; transform: translateY(4px); transition: opacity 0.4s, transform 0.4s; }
.score.on { opacity: 1; transform: none; }
.score b { font-family: var(--db-font-num); font-size: 1.6rem; font-weight: 500; color: var(--db-accent-ink); }
.note { margin: 0.8rem 0 0; text-align: center; font-size: 0.8rem; color: var(--db-text-soft); }

@media (max-width: 760px) {
  .top { grid-template-columns: 1fr; }
  .sync { flex-direction: row; }
  .sync em { writing-mode: horizontal-tb; }
  .sync span { transform: rotate(90deg); }
  .plan svg { max-width: 420px; margin: 0 auto; }
}
@media (prefers-reduced-motion: reduce) {
  .item, .score, .checks svg path, .checks li, .hit, .hit i, .frame img { transition: none; }
}
</style>
