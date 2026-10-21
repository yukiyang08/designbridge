<script setup>
/**
 * 風水健檢用的俯視小平面圖：家具、門、窗，違規的家具標紅、被調整的家具標綠，
 * 被調整家具的原位置畫成虛線框＋移動軌跡。
 * 座標同後端：x 左→右、y 遠牆（0，上方）→近牆（1，下方）。
 */
import { computed } from 'vue'
import { furnitureLabel } from '@/config/furniture'

const props = defineProps({
  plan: { type: Object, required: true },   // { room_w, room_d, placements, doors, windows }
  offenders: { type: Array, default: () => [] },
  moved: { type: Array, default: () => [] },     // 被調整過的家具 id
  ghosts: { type: Array, default: () => [] },    // 被調整家具的原位置（placements 格式）
  title: { type: String, default: '' },
  /** 照片健檢：下方那面牆是拍照的位置 */
  photo: { type: Boolean, default: false },
})

const W = computed(() => props.plan.room_w * 100)
const D = computed(() => props.plan.room_d * 100)
const bad = computed(() => new Set(props.offenders))
const movedSet = computed(() => new Set(props.moved))
const doorBad = computed(() => bad.value.has('door'))
const byId = computed(() => Object.fromEntries(props.plan.placements.map(p => [p.id, p])))
// 地毯畫在最底下，不蓋住其他家具
const ordered = computed(() => [...props.plan.placements].sort((a, b) => (b.type === 'rug') - (a.type === 'rug')))

const rect = o => ({ x: o.x * W.value, y: o.y * D.value, w: o.w * W.value, h: o.h * D.value })
const centre = o => ({ x: (o.x + o.w / 2) * W.value, y: (o.y + o.h / 2) * D.value })
const fontSize = computed(() => Math.max(12, Math.min(W.value, D.value) / 22))

// 開口畫成貼在牆上的一段粗線
function openingLine(o) {
  const r = rect(o)
  if (o.wall === 'far' || o.wall === 'near') {
    const y = o.wall === 'far' ? 0 : D.value
    return { x1: r.x, y1: y, x2: r.x + r.w, y2: y }
  }
  const x = o.wall === 'left' ? 0 : W.value
  return { x1: x, y1: r.y, x2: x, y2: r.y + r.h }
}
</script>

<template>
  <figure class="mini-plan">
    <figcaption v-if="title" class="mp-title">{{ title }}</figcaption>
    <svg :viewBox="`-14 -14 ${W + 28} ${D + 28}`" role="img" :aria-label="title || '俯視平面圖'">
      <defs>
        <marker id="mp-arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
          <path d="M0 0L10 5L0 10z" class="mp-arrow-head" />
        </marker>
      </defs>
      <rect :width="W" :height="D" class="mp-room" />

      <rect v-for="g in ghosts" :key="'g' + g.id"
            :x="rect(g).x" :y="rect(g).y" :width="rect(g).w" :height="rect(g).h" rx="3" class="mp-ghost" />

      <g v-for="p in ordered" :key="p.id">
        <rect :x="rect(p).x" :y="rect(p).y" :width="rect(p).w" :height="rect(p).h" rx="3"
              class="mp-item" :class="{ 'is-bad': bad.has(p.id), 'is-moved': movedSet.has(p.id), 'is-floor': p.type === 'rug' }" />
        <text :x="centre(p).x" :y="centre(p).y" class="mp-label" :font-size="fontSize"
              :class="{ 'is-bad': bad.has(p.id), 'is-moved': movedSet.has(p.id) }">{{ furnitureLabel(p.type) }}</text>
      </g>

      <template v-for="g in ghosts" :key="'a' + g.id">
        <line v-if="byId[g.id]"
              :x1="centre(g).x" :y1="centre(g).y" :x2="centre(byId[g.id]).x" :y2="centre(byId[g.id]).y"
              class="mp-arrow" marker-end="url(#mp-arrow)" />
      </template>

      <line v-for="(w, i) in plan.windows" :key="'w' + i" v-bind="openingLine(w)" class="mp-window" />
      <line v-for="(d, i) in plan.doors" :key="'d' + i" v-bind="openingLine(d)"
            class="mp-door" :class="{ 'is-assumed': d.assumed, 'is-bad': doorBad }" />
    </svg>
    <div class="mp-legend">
      <span><i class="lg-door" />門<template v-if="plan.doors.some(d => d.assumed)">（虛線 = 推測）</template></span>
      <span><i class="lg-window" />窗</span>
      <span v-if="offenders.length"><i class="lg-bad" />違規</span>
      <span v-if="moved.length"><i class="lg-moved" />已調整（虛線框 = 原位置）</span>
      <span v-if="photo" class="mp-camera">下方 = 拍照位置</span>
    </div>
  </figure>
</template>

<style scoped>
.mini-plan { margin: 0; }
.mp-title { margin-bottom: 0.3rem; font-size: 0.82rem; font-weight: 600; color: var(--db-text-soft); }
svg { display: block; width: 100%; max-height: 300px; }
.mp-room { fill: #faf8f2; stroke: var(--db-text); stroke-width: 4; }
.mp-item { fill: var(--db-chip); stroke: var(--db-text-soft); stroke-width: 1.5; }
.mp-item.is-floor { fill: transparent; stroke-dasharray: 4 4; }
.mp-item.is-bad { fill: var(--db-danger-soft); stroke: var(--db-danger); stroke-width: 3; }
.mp-item.is-moved { fill: #e3efe6; stroke: var(--db-ok); stroke-width: 3; }
.mp-ghost { fill: none; stroke: var(--db-ok); stroke-width: 2; stroke-dasharray: 6 5; opacity: 0.8; }
.mp-arrow { stroke: var(--db-ok); stroke-width: 2.5; }
.mp-arrow-head { fill: var(--db-ok); }
.mp-label { text-anchor: middle; dominant-baseline: middle; fill: var(--db-text-soft); }
.mp-label.is-bad { fill: var(--db-danger); font-weight: 600; }
.mp-label.is-moved { fill: var(--db-ok); font-weight: 600; }
.mp-window { stroke: #6b9bc3; stroke-width: 9; }
.mp-door { stroke: #a0764a; stroke-width: 11; }
.mp-door.is-assumed { stroke-dasharray: 10 6; }
.mp-door.is-bad { stroke: var(--db-danger); }

.mp-legend { display: flex; flex-wrap: wrap; gap: 0.3rem 0.9rem; margin-top: 0.35rem; color: var(--db-text-soft); font-size: 0.72rem; }
.mp-legend i { display: inline-block; width: 14px; height: 6px; margin-right: 0.3rem; vertical-align: middle; }
.lg-door { background: #a0764a; }
.lg-window { background: #6b9bc3; }
.lg-bad { background: var(--db-danger); }
.lg-moved { background: var(--db-ok); }
.mp-camera { margin-left: auto; }
</style>
