<script setup>
/**
 * 在渲染圖上直接拖曳家具：點家具拿到它的圖層，拖到新位置即時預覽（依地平線做透視縮放），
 * 按「套用」才請 AI 把它融進新位置。
 */
import { ref, computed, watch, onBeforeUnmount } from 'vue'
import { furnitureLabel } from '@/config/furniture'
import { pickFurniture, applyFurnitureMove, applyingMove, undoMove, canUndoMove } from '@/composables/design-flow/move'

const props = defineProps({
  imageUrl: { type: String, required: true },
})
const emit = defineEmits(['close'])

const imgRef = ref(null)
const picked = ref(null)         // pick 回傳：layer / bbox / patch / patch_bbox / anchor / horizon_y
const offset = ref({ x: 0, y: 0 })
const picking = ref(false)
const dragging = ref(false)
const errorMsg = ref('')

// 換了一張圖（套用完成、復原）就重新點選
watch(() => props.imageUrl, () => { picked.value = null })


// 跟後端 move_furniture._pixel_to_floor 同一套相機換算（像素 ↔ 地板公尺座標）
function pixelToFloor(cam, u, v) {
  const d = [(u - cam.cx) / cam.f, -(v - cam.cy) / cam.f, 1]
  const ray = [0, 1, 2].map(i => cam.R[0][i] * d[0] + cam.R[1][i] * d[1] + cam.R[2][i] * d[2])
  const t = -cam.eye[1] / ray[1]
  return { x: cam.eye[0] + t * ray[0], z: cam.eye[2] + t * ray[2] }
}
function floorToPixel(cam, x, z) {
  const p = [x - cam.eye[0], -cam.eye[1], z - cam.eye[2]]
  const c = cam.R.map(r => r[0] * p[0] + r[1] * p[1] + r[2] * p[2])
  return { u: cam.cx + cam.f * c[0] / c[2], v: cam.cy - cam.f * c[1] / c[2] }
}
const clamp = (v, lo, hi) => Math.min(Math.max(v, lo), hi)

// 拖到的位置換成平面圖上的新 footprint（夾在房間內，跟後端 drag_to_placements 一樣），
// 錨點再從夾過的 footprint 投影回畫面，預覽才不會跑出牆外
const placement = computed(() => {
  const p = picked.value
  if (!p) return null
  const cam = p.camera, { w: fw, h: fh } = p.footprint
  const v = Math.max(p.anchor.y + offset.value.y, p.horizon_y + 0.01) * cam.height
  const hit = pixelToFloor(cam, (p.anchor.x + offset.value.x) * cam.width, v)
  const x = clamp(hit.x / p.room.w - fw / 2, 0, 1 - fw)
  const y = clamp(1 - hit.z / p.room.d - fh / 2, 0, 1 - fh)
  const a = floorToPixel(cam, (x + fw / 2) * p.room.w, (1 - (y + fh / 2)) * p.room.d)
  return { x, y, w: fw, h: fh, anchor: { x: a.u / cam.width, y: a.v / cam.height } }
})
const anchorNow = computed(() => placement.value?.anchor || null)
// 看平面圖上的位置有沒有變，不看滑鼠位移：頂著牆拖，滑鼠動了家具其實沒動
const moved = computed(() => {
  const q = placement.value, f = picked.value?.footprint
  return !!q && Math.abs(q.x - f.x) + Math.abs(q.y - f.y) > 2e-3
})
const EPS = 1e-3
const blockers = computed(() => {
  const q = placement.value
  if (!q) return []
  return picked.value.obstacles.filter(o =>
    q.x < o.x + o.w - EPS && q.x + q.w > o.x + EPS && q.y < o.y + o.h - EPS && q.y + q.h > o.y + EPS)
})
const blocked = computed(() => blockers.value.length > 0)
const blockerNames = computed(() => [...new Set(blockers.value.map(o => furnitureLabel(o.type)))].join('、'))
// 地板上的東西大小跟離地平線的距離成正比
const scale = computed(() => {
  const p = picked.value
  if (!p) return 1
  return Math.min(4, Math.max(0.2, (anchorNow.value.y - p.horizon_y) / (p.anchor.y - p.horizon_y)))
})

const pct = (v) => `${v * 100}%`
const boxStyle = (b) => ({ left: pct(b.x0), top: pct(b.y0), width: pct(b.x1 - b.x0), height: pct(b.y1 - b.y0) })
const layerStyle = computed(() => {
  const p = picked.value
  const a = p.anchor, n = anchorNow.value, s = scale.value
  return boxStyle({
    x0: n.x + (p.bbox.x0 - a.x) * s, x1: n.x + (p.bbox.x1 - a.x) * s,
    y0: n.y + (p.bbox.y0 - a.y) * s, y1: n.y + (p.bbox.y1 - a.y) * s,
  })
})

function relPoint(e) {
  const r = imgRef.value.getBoundingClientRect()
  return { x: (e.clientX - r.left) / r.width, y: (e.clientY - r.top) / r.height }
}

async function onStageDown(e) {
  if (applyingMove.value || picking.value) return
  const pt = relPoint(e)
  if (pt.x < 0 || pt.x > 1 || pt.y < 0 || pt.y > 1) return
  errorMsg.value = ''
  picking.value = true
  try {
    const hit = await pickFurniture(pt.x, pt.y)
    picked.value = hit
    offset.value = { x: 0, y: 0 }
    lastValid = { x: 0, y: 0 }
    if (!hit) errorMsg.value = '這裡沒有可以移動的家具，請點家具本身。'
  } catch (err) {
    errorMsg.value = `選取失敗：${err.message}`
  } finally {
    picking.value = false
  }
}

let start = null
let lastValid = { x: 0, y: 0 }   // 最後一個不會重疊的位置；放開時壓到別的家具就彈回這裡
function onLayerDown(e) {
  if (applyingMove.value) return
  e.currentTarget.setPointerCapture(e.pointerId)
  start = { pt: relPoint(e), offset: { ...offset.value } }
  dragging.value = true
}
function onLayerMove(e) {
  if (!dragging.value) return
  const pt = relPoint(e)
  offset.value = { x: start.offset.x + pt.x - start.pt.x, y: start.offset.y + pt.y - start.pt.y }
  if (!blocked.value) lastValid = { ...offset.value }
}
function onLayerUp() {
  dragging.value = false
  if (blocked.value) offset.value = { ...lastValid }
}

function resetPick() {
  picked.value = null
  offset.value = { x: 0, y: 0 }
  lastValid = { x: 0, y: 0 }
  errorMsg.value = ''
}

async function onApply() {
  if (!picked.value || !moved.value || blocked.value || applyingMove.value) return
  errorMsg.value = ''
  const a = anchorNow.value
  try {
    await applyFurnitureMove({
      id: picked.value.id,
      x: Math.min(1, Math.max(0, a.x)),
      y: Math.min(1, Math.max(0, a.y)),
    })
    resetPick()
  } catch (err) {
    errorMsg.value = `移動失敗：${err.message}`
  }
}

function onKey(e) {
  if (e.key !== 'Escape' || applyingMove.value) return
  if (picked.value) resetPick()
  else emit('close')
}
window.addEventListener('keydown', onKey)
onBeforeUnmount(() => window.removeEventListener('keydown', onKey))
</script>

<template>
  <div class="fm">
    <div class="fm-stage" :class="{ busy: applyingMove, picking }" @pointerdown="onStageDown">
      <img ref="imgRef" :src="imageUrl" alt="生成的 3D 渲染圖" class="fm-img" draggable="false" />

      <template v-if="picked">
        <!-- 原位置先蓋上補洞貼片，拖走後看起來才像真的搬走了 -->
        <img v-if="moved" :src="picked.patch" class="fm-patch" :style="boxStyle(picked.patch_bbox)" alt="" draggable="false" />
        <img
          :src="picked.layer" class="fm-layer" :class="{ dragging, blocked }" :style="layerStyle" alt="" draggable="false"
          @pointerdown.stop="onLayerDown" @pointermove="onLayerMove" @pointerup="onLayerUp" @pointercancel="onLayerUp"
        />
      </template>

      <div class="fm-corner">
        <button type="button" title="結束移動家具（Esc）" @pointerdown.stop @click="emit('close')">✕</button>
      </div>

      <div v-if="applyingMove" class="fm-busy" role="status">
        <div class="fm-spinner"></div>
        <p>AI 正在把家具融入新位置…約 30–60 秒</p>
      </div>
    </div>

    <div class="fm-bar">
      <p class="fm-hint">
        <template v-if="picking">選取中…（每張圖第一次要先辨識家具輪廓，約 10 秒）</template>
        <template v-else-if="!picked">點一下圖上要移動的家具</template>
        <span v-else-if="blocked" class="fm-warn">會跟「{{ blockerNames }}」重疊，放開會回到上一個可以放的位置</span>
        <template v-else-if="!moved">拖曳「{{ furnitureLabel(picked.type) }}」到新位置</template>
        <template v-else>放好了就按「套用」，AI 會重新補光影與接縫</template>
      </p>
      <div class="fm-actions">
        <button v-if="canUndoMove" type="button" class="fm-link" :disabled="applyingMove" @click="undoMove">↶ 復原上一次移動</button>
        <button v-if="picked" type="button" class="db-btn db-btn--ghost db-btn--sm" :disabled="applyingMove" @click="resetPick">換一件</button>
        <button type="button" class="db-btn db-btn--sm" :disabled="!picked || !moved || blocked || applyingMove" @click="onApply">套用</button>
      </div>
      <p v-if="errorMsg" class="fm-error" role="alert">{{ errorMsg }}</p>
    </div>
  </div>
</template>

<style scoped>
.fm { display: flex; flex-direction: column; gap: 0.9rem; width: 100%; }
.fm-stage {
  position: relative;
  align-self: center;
  max-width: 100%;
  line-height: 0;
  border-radius: 8px;
  overflow: hidden;
  cursor: crosshair;
  touch-action: none;
  user-select: none;
}
.fm-stage.picking { cursor: progress; }
.fm-img { display: block; max-width: 100%; max-height: 75vh; }

.fm-patch, .fm-layer { position: absolute; pointer-events: none; }
.fm-layer {
  pointer-events: auto;
  cursor: grab;
  filter: drop-shadow(0 0 1.5px #fff) drop-shadow(0 0 1px var(--db-accent)) drop-shadow(0 6px 10px rgba(0, 0, 0, 0.35));
}
.fm-layer.dragging { cursor: grabbing; opacity: 0.92; }
.fm-layer.blocked {
  opacity: 0.7;
  filter: drop-shadow(0 0 1.5px #fff) drop-shadow(0 0 2px #d93025) drop-shadow(0 0 6px rgba(217, 48, 37, 0.6));
}
.fm-warn { color: #b3261e; }

.fm-corner { position: absolute; top: 0.75rem; right: 0.75rem; }
.fm-corner button {
  padding: 0.4rem 0.7rem;
  border: none;
  border-radius: var(--db-radius-pill);
  background: rgba(20, 18, 14, 0.78);
  color: #fff;
  line-height: 1;
  cursor: pointer;
}

.fm-stage.busy .fm-img, .fm-stage.busy .fm-layer, .fm-stage.busy .fm-patch { filter: blur(6px); transition: filter 0.2s; }
.fm-stage.busy { pointer-events: none; }
.fm-busy {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 0.6rem;
  background: rgba(20, 18, 14, 0.25);
  color: #fff;
  font-size: 0.9rem;
  line-height: 1.4;
  text-shadow: 0 1px 3px rgba(0, 0, 0, 0.6);
}
.fm-spinner {
  width: 32px; height: 32px;
  border: 3px solid rgba(255, 255, 255, 0.3);
  border-top-color: #fff;
  border-radius: 50%;
  animation: fm-spin 0.8s linear infinite;
}
@keyframes fm-spin { to { transform: rotate(360deg); } }

.fm-bar { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 0.6rem; }
.fm-hint { margin: 0; font-size: 0.88rem; color: var(--db-text-soft); }
.fm-actions { display: flex; align-items: center; gap: 0.6rem; }
.fm-link {
  border: none;
  background: none;
  padding: 0;
  color: var(--db-accent-deep);
  font-size: 0.85rem;
  text-decoration: underline;
  text-underline-offset: 3px;
  cursor: pointer;
}
.fm-link:disabled { opacity: 0.4; cursor: not-allowed; }
.fm-error { flex-basis: 100%; margin: 0; font-size: 0.82rem; color: #b3261e; }
</style>
