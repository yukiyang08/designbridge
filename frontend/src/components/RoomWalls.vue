<script setup>
/**
 * 單間房的牆體、門（含開門弧）、窗，畫在編輯器畫布內側。
 * SVG 的 viewBox 直接用房間公尺數，所以牆厚、門寬都是真實尺寸；
 * 牆沿房間矩形（= 牆中心線）往內畫一半厚度，另一半屬於隔壁房間。
 */
import { computed } from 'vue'

const props = defineProps({
  roomW: { type: Number, required: true },
  roomD: { type: Number, required: true },
  geometry: { type: Object, required: true },   // { wallT, openings }（見 utils/roomGeometry）
})

// 沿牆的局部座標 (u 沿牆, v 往房間內) → 畫布座標
function map(side, u, v) {
  const W = props.roomW, D = props.roomD
  if (side === 'top') return [u, v]
  if (side === 'bottom') return [u, D - v]
  if (side === 'left') return [v, u]
  return [W - v, u]   // right
}
const SWEEP = { top: 0, bottom: 1, left: 1, right: 0 }   // 鏡射一次翻轉弧線方向
const len = (side) => (side === 'top' || side === 'bottom' ? props.roomW : props.roomD)
const pt = (side, u, v) => map(side, u, v).join(',')

// 每一邊的牆：扣掉門窗開口後剩下的實心段
const wallRects = computed(() => {
  const out = []
  for (const side of ['top', 'bottom', 'left', 'right']) {
    const t = props.geometry.wallT[side] / 2
    const L = len(side)
    const ops = props.geometry.openings
      .filter(o => o.side === side && o.type === 'door')
      .map(o => [Math.max(0, o.frac * L - o.width / 2), Math.min(L, o.frac * L + o.width / 2)])
      .sort((a, b) => a[0] - b[0])
    let cur = 0
    const solid = (a, b) => {
      if (b - a < 1e-6) return
      const [x1, y1] = map(side, a, 0), [x2, y2] = map(side, b, t)
      out.push({ k: `${side}${a}`, x: Math.min(x1, x2), y: Math.min(y1, y2), w: Math.abs(x2 - x1), h: Math.abs(y2 - y1) })
    }
    for (const [a, b] of ops) { solid(cur, a); cur = Math.max(cur, b) }
    solid(cur, L)
  }
  return out
})

const doors = computed(() => props.geometry.openings.filter(o => o.type === 'door').map(o => {
  const L = len(o.side), c = o.frac * L, w = o.width, u0 = c - w / 2
  return {
    id: o.id,
    swingIn: o.swingIn,
    leaf: `M ${pt(o.side, u0, 0)} L ${pt(o.side, u0, w)}`,
    arc: `M ${pt(o.side, u0, w)} A ${w} ${w} 0 0 ${SWEEP[o.side]} ${pt(o.side, u0 + w, 0)}`,
    sill: `M ${pt(o.side, u0, 0)} L ${pt(o.side, u0 + w, 0)}`,
  }
}))

const windows = computed(() => props.geometry.openings.filter(o => o.type === 'window').map(o => {
  const L = len(o.side), c = o.frac * L, t = props.geometry.wallT[o.side] / 2
  const [x1, y1] = map(o.side, c - o.width / 2, 0), [x2, y2] = map(o.side, c + o.width / 2, t)
  const [mx1, my1] = map(o.side, c - o.width / 2, t / 2), [mx2, my2] = map(o.side, c + o.width / 2, t / 2)
  return { id: o.id, x: Math.min(x1, x2), y: Math.min(y1, y2), w: Math.abs(x2 - x1), h: Math.abs(y2 - y1), mid: `M ${mx1} ${my1} L ${mx2} ${my2}` }
}))
</script>

<template>
  <svg class="walls" :viewBox="`0 0 ${roomW} ${roomD}`" preserveAspectRatio="none" aria-hidden="true">
    <rect v-for="r in wallRects" :key="r.k" :x="r.x" :y="r.y" :width="r.w" :height="r.h" class="wall" />
    <rect v-for="w in windows" :key="w.id" :x="w.x" :y="w.y" :width="w.w" :height="w.h" class="win" />
    <path v-for="w in windows" :key="`${w.id}m`" :d="w.mid" class="win-mid" />
    <g v-for="d in doors" :key="d.id">
      <path :d="d.sill" class="sill" />
      <template v-if="d.swingIn">
        <path :d="d.leaf" class="leaf" />
        <path :d="d.arc" class="arc" />
      </template>
    </g>
  </svg>
</template>

<style scoped>
.walls { position: absolute; inset: 0; width: 100%; height: 100%; pointer-events: none; }
.wall { fill: #2b2b2b; }
.win { fill: #c0daf8; stroke: #2e6ab5; stroke-width: 1.5; vector-effect: non-scaling-stroke; }
.win-mid { stroke: #2e6ab5; stroke-width: 1; vector-effect: non-scaling-stroke; fill: none; }
.sill { stroke: #bfae95; stroke-width: 2; vector-effect: non-scaling-stroke; }
.leaf { stroke: #444; stroke-width: 1.6; vector-effect: non-scaling-stroke; fill: none; }
.arc { stroke: #777; stroke-width: 1.2; stroke-dasharray: 4 3; vector-effect: non-scaling-stroke; fill: none; }
</style>
