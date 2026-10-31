<script setup>
/**
 * 在渲染圖上直接拖曳家具：一進來就把後端自動切出的每件家具框出來，
 * 點選（Shift 多選）後拖曳，即時預覽透視縮放、擋重疊；按「套用」才請 AI 修接縫與光影。
 */
import { ref, reactive, computed, watch, onMounted, onBeforeUnmount } from 'vue'
import { fetchFurnitureInstances, applyFurnitureMove, applyFurnitureMoveOn, applyingMove, undoMove, canUndoMove } from '@/composables/design-flow/move'

const props = defineProps({
  imageUrl: { type: String, required: true },
  // 照片工作台傳 { generated_image_path }：在那張圖上移，套用後 emit('applied', 新圖) 由它收成新版本
  plan: { type: Object, default: null },
})
const emit = defineEmits(['close', 'applied'])

// 語意分割的英文類別 → 提示文字
const LABEL_ZH = {
  sofa: '沙發', chair: '椅子', armchair: '扶手椅', 'swivel chair': '椅子', stool: '凳子', ottoman: '腳凳',
  bench: '長凳', table: '桌子', 'coffee table': '茶几', desk: '書桌', bed: '床', cabinet: '櫃子',
  wardrobe: '衣櫃', shelf: '層架', bookcase: '書櫃', 'chest of drawers': '斗櫃', plant: '盆栽',
  pot: '盆栽', vase: '花瓶', lamp: '燈', 'television receiver': '電視', counter: '檯面',
}
const labelOf = (inst) => LABEL_ZH[inst.label] || '家具'

const imgRef = ref(null)
const data = ref(null)          // /api/move-furniture/instances 的回應
const loading = ref(false)
const errorMsg = ref('')
const offsets = reactive({})    // index → 碰地點的拖曳位移（0–1）
const selected = ref(new Set())
const hovered = ref(null)
const dragging = ref(false)
let lastValid = {}
let alphaMaps = {}              // index → 圖層的 alpha（點選判斷用，透明處不算點到）

const instances = computed(() => data.value?.instances || [])

async function load() {
  loading.value = true
  errorMsg.value = ''
  data.value = null
  selected.value = new Set()
  for (const k of Object.keys(offsets)) delete offsets[k]
  lastValid = {}
  alphaMaps = {}
  try {
    data.value = await fetchFurnitureInstances(props.plan)
    if (!instances.value.length) errorMsg.value = '這張圖沒有辨識到可以移動的家具。'
    instances.value.forEach(loadAlpha)
  } catch (e) {
    errorMsg.value = `辨識家具失敗：${e.message}`
  } finally {
    loading.value = false
  }
}
onMounted(load)
// 套用完成、復原都會換圖，重新切
watch(() => props.imageUrl, load)

function loadAlpha(inst) {
  const img = new Image()
  img.crossOrigin = 'anonymous'
  img.onload = () => {
    const c = document.createElement('canvas')
    c.width = img.naturalWidth
    c.height = img.naturalHeight
    const ctx = c.getContext('2d')
    ctx.drawImage(img, 0, 0)
    try {
      alphaMaps[inst.index] = { w: c.width, h: c.height, a: ctx.getImageData(0, 0, c.width, c.height).data }
    } catch { /* 跨網域讀不到像素就退回用外框判斷 */ }
  }
  img.src = inst.layer_url
}

// ── 幾何：跟後端 move_furniture 同一套相機換算（像素 ↔ 地板公尺座標）────────
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
const EPS = 1e-3
const overlaps = (a, b) => a.x < b.x + b.w - EPS && a.x + a.w > b.x + EPS && a.y < b.y + b.h - EPS && a.y + a.h > b.y + EPS

// 每件家具拖曳後的狀態：新的平面圖位置（夾在房間內）、畫面上的碰地點、透視縮放
const placed = computed(() => {
  const d = data.value
  if (!d) return {}
  const cam = d.camera, W = cam.width, H = cam.height, room = d.room
  const out = {}
  for (const inst of instances.value) {
    const off = offsets[inst.index] || { x: 0, y: 0 }
    const a = { u: inst.anchor.x * W, v: inst.anchor.y * H }
    const p0 = pixelToFloor(cam, a.u, a.v)
    const p1 = pixelToFloor(cam, a.u + off.x * W, Math.max(a.v + off.y * H, (d.horizon_y + 0.01) * H))
    const f = inst.footprint
    // bounded=false：沒排家具就生的圖，房間大小是猜的，不夾在房間內（跟後端一樣）
    const lim = (v, hi) => (d.bounded ? clamp(v, 0, hi) : v)
    const fp = {
      w: f.w, h: f.h,
      x: lim(f.x + (p1.x - p0.x) / room.w, 1 - f.w),
      y: lim(f.y - (p1.z - p0.z) / room.d, 1 - f.h),
    }
    const b = floorToPixel(cam, p0.x + (fp.x - f.x) * room.w, p0.z - (fp.y - f.y) * room.d)
    const s = clamp((b.v / H - d.horizon_y) / Math.max(inst.anchor.y - d.horizon_y, 1e-3), 0.2, 4)
    out[inst.index] = {
      fp, anchor: { x: b.u / W, y: b.v / H }, scale: s,
      moved: Math.abs(fp.x - f.x) + Math.abs(fp.y - f.y) > 2e-3,
    }
  }
  return out
})
// 拖到會跟別的家具重疊的位置（原本就重疊的不算，後端給的 blockers 已經排除）
const blockedSet = computed(() => {
  const p = placed.value
  const out = new Set()
  for (const inst of instances.value) {
    if (!p[inst.index]?.moved) continue
    if (inst.blockers.some(o => p[o] && overlaps(p[inst.index].fp, p[o].fp))) out.add(inst.index)
  }
  return out
})
const movedList = computed(() => instances.value.filter(i => placed.value[i.index]?.moved))

const pct = (v) => `${v * 100}%`
function layerStyle(inst) {
  const p = placed.value[inst.index]
  const a = inst.anchor, n = p?.anchor || a, s = p?.scale || 1, b = inst.bbox
  return {
    left: pct(n.x + (b.x0 - a.x) * s), top: pct(n.y + (b.y0 - a.y) * s),
    width: pct((b.x1 - b.x0) * s), height: pct((b.y1 - b.y0) * s),
    zIndex: Math.round(n.y * 1000),   // 越靠鏡頭（碰地點越低）疊越上面
  }
}
const boxStyle = (b) => ({ left: pct(b.x0), top: pct(b.y0), width: pct(b.x1 - b.x0), height: pct(b.y1 - b.y0) })

function relPoint(e) {
  const r = imgRef.value.getBoundingClientRect()
  return { x: (e.clientX - r.left) / r.width, y: (e.clientY - r.top) / r.height }
}
// 點到哪一件：從最靠鏡頭的開始找，點在外框內而且那個像素不透明才算
function hitTest(pt) {
  const order = [...instances.value].sort((a, b) => (placed.value[b.index]?.anchor.y || 0) - (placed.value[a.index]?.anchor.y || 0))
  for (const inst of order) {
    const st = layerStyle(inst)
    const x0 = parseFloat(st.left) / 100, y0 = parseFloat(st.top) / 100
    const w = parseFloat(st.width) / 100, h = parseFloat(st.height) / 100
    const fx = (pt.x - x0) / w, fy = (pt.y - y0) / h
    if (fx < 0 || fx > 1 || fy < 0 || fy > 1) continue
    const m = alphaMaps[inst.index]
    if (!m) return inst.index
    const ax = Math.min(m.w - 1, Math.floor(fx * m.w)), ay = Math.min(m.h - 1, Math.floor(fy * m.h))
    if (m.a[(ay * m.w + ax) * 4 + 3] > 128) return inst.index
  }
  return null
}

let start = null
function onDown(e) {
  if (applyingMove.value || loading.value || !data.value) return
  const pt = relPoint(e)
  const hit = hitTest(pt)
  if (hit === null) {
    if (!e.shiftKey) selected.value = new Set()
    return
  }
  const next = new Set(selected.value)
  if (e.shiftKey) {
    next.has(hit) ? next.delete(hit) : next.add(hit)
    selected.value = next
    return
  }
  if (!next.has(hit)) selected.value = new Set([hit])
  e.currentTarget.setPointerCapture(e.pointerId)
  start = { pt, offsets: Object.fromEntries([...selected.value].map(k => [k, { ...(offsets[k] || { x: 0, y: 0 }) }])) }
  dragging.value = true
}
function onMove(e) {
  if (!data.value) return
  const pt = relPoint(e)
  if (!dragging.value) {
    hovered.value = hitTest(pt)
    return
  }
  const dx = pt.x - start.pt.x, dy = pt.y - start.pt.y
  for (const [k, o] of Object.entries(start.offsets)) offsets[k] = { x: o.x + dx, y: o.y + dy }
  for (const k of Object.keys(start.offsets)) {
    if (!blockedSet.value.has(Number(k))) lastValid[k] = { ...offsets[k] }
  }
}
function onUp() {
  if (!dragging.value) return
  dragging.value = false
  // 放開時壓到別的家具：彈回最後一個沒重疊的位置
  for (const k of Object.keys(start.offsets)) {
    if (blockedSet.value.has(Number(k))) offsets[k] = { ...(lastValid[k] || { x: 0, y: 0 }) }
  }
}

function resetAll() {
  for (const k of Object.keys(offsets)) delete offsets[k]
  lastValid = {}
  errorMsg.value = ''
}

async function onApply() {
  if (!movedList.value.length || blockedSet.value.size || applyingMove.value) return
  errorMsg.value = ''
  try {
    const moves = movedList.value.map(i => ({
      index: i.index,
      x: clamp(placed.value[i.index].anchor.x, 0, 1),
      y: clamp(placed.value[i.index].anchor.y, 0, 1),
    }))
    if (props.plan) emit('applied', await applyFurnitureMoveOn(props.plan, moves))
    else await applyFurnitureMove(moves)
    // 套用完回到單純的渲染圖；要再搬就再按一次「移動家具」
    emit('close')
  } catch (e) {
    errorMsg.value = `移動失敗：${e.message}`
  }
}

const blockedNames = computed(() => [...blockedSet.value].map(k => labelOf(instances.value.find(i => i.index === k))).join('、'))
const selectedNames = computed(() => [...selected.value].map(k => labelOf(instances.value.find(i => i.index === k))).join('、'))

function onKey(e) {
  if (e.key !== 'Escape' || applyingMove.value) return
  if (selected.value.size) selected.value = new Set()
  else emit('close')
}
window.addEventListener('keydown', onKey)
onBeforeUnmount(() => window.removeEventListener('keydown', onKey))
</script>

<template>
  <div class="fm">
    <div
      class="fm-stage" :class="{ busy: applyingMove || loading, dragging, hovering: hovered !== null }"
      @pointerdown="onDown" @pointermove="onMove" @pointerup="onUp" @pointercancel="onUp"
      @pointerleave="hovered = null"
    >
      <img ref="imgRef" :src="imageUrl" alt="生成的 3D 渲染圖" class="fm-img" draggable="false" />

      <!-- 移走的家具，原位置先蓋上粗補的貼片，看起來才像真的搬走了 -->
      <img
        v-for="inst in movedList" :key="`p${inst.index}`" :src="inst.patch_url"
        class="fm-patch" :style="boxStyle(inst.patch_bbox)" alt="" draggable="false"
      />
      <img
        v-for="inst in instances" :key="inst.index" :src="inst.layer_url" alt="" draggable="false"
        class="fm-layer" :style="layerStyle(inst)"
        :class="{
          hover: hovered === inst.index, selected: selected.has(inst.index),
          blocked: blockedSet.has(inst.index),
        }"
      />

      <div class="fm-corner">
        <button type="button" title="結束移動家具（Esc）" @pointerdown.stop @click="emit('close')">✕</button>
      </div>

      <div v-if="loading" class="fm-busy" role="status">
        <div class="fm-spinner"></div>
        <p>辨識圖上的家具中…每張圖第一次約 40 秒</p>
      </div>
      <div v-else-if="applyingMove" class="fm-busy" role="status">
        <div class="fm-spinner"></div>
        <p>AI 正在把家具融入新位置…</p>
      </div>
    </div>

    <div class="fm-bar">
      <p class="fm-hint">
        <span v-if="blockedSet.size" class="fm-warn">「{{ blockedNames }}」會跟其他家具重疊，放開會回到上一個可以放的位置</span>
        <template v-else-if="loading">辨識中…</template>
        <template v-else-if="!selected.size && !movedList.length">點一下要移動的家具，Shift＋點可以多選</template>
        <template v-else-if="selected.size && !movedList.length">拖曳「{{ selectedNames }}」到新位置</template>
        <template v-else>已移動 {{ movedList.length }} 件，放好了就按「套用」，AI 會重新補光影與接縫</template>
      </p>
      <div class="fm-actions">
        <button v-if="canUndoMove && !plan" type="button" class="fm-link" :disabled="applyingMove" @click="undoMove">↶ 復原上一次移動</button>
        <button v-if="movedList.length" type="button" class="db-btn db-btn--ghost db-btn--sm" :disabled="applyingMove" @click="resetAll">全部還原</button>
        <button type="button" class="db-btn db-btn--sm" :disabled="!movedList.length || blockedSet.size > 0 || applyingMove" @click="onApply">套用</button>
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
  touch-action: none;
  user-select: none;
}
.fm-stage.hovering { cursor: grab; }
.fm-stage.dragging { cursor: grabbing; }
.fm-img { display: block; max-width: 100%; max-height: 75vh; }

.fm-patch, .fm-layer { position: absolute; pointer-events: none; }
/* 每件家具都框出細白邊；滑過加亮、選取用主色、壓到別的家具變紅 */
.fm-layer { filter: drop-shadow(0 0 0.6px rgba(255, 255, 255, 0.95)) drop-shadow(0 0 0.6px rgba(255, 255, 255, 0.95)); transition: filter 0.12s; }
.fm-layer.hover { filter: drop-shadow(0 0 1.2px #fff) drop-shadow(0 0 1.5px var(--db-accent)) drop-shadow(0 0 1.5px var(--db-accent)); }
.fm-layer.selected { filter: drop-shadow(0 0 1.5px #fff) drop-shadow(0 0 2px var(--db-accent)) drop-shadow(0 0 2px var(--db-accent)) drop-shadow(0 6px 10px rgba(0, 0, 0, 0.3)); }
.fm-layer.blocked { opacity: 0.75; filter: drop-shadow(0 0 1.5px #fff) drop-shadow(0 0 2px #d93025) drop-shadow(0 0 6px rgba(217, 48, 37, 0.6)); }

.fm-corner { position: absolute; top: 0.75rem; right: 0.75rem; z-index: 2000; }
.fm-corner button {
  padding: 0.4rem 0.7rem;
  border: none;
  border-radius: var(--db-radius-pill);
  background: rgba(20, 18, 14, 0.78);
  color: #fff;
  line-height: 1;
  cursor: pointer;
}

.fm-stage.busy { pointer-events: none; }
.fm-stage.busy .fm-img, .fm-stage.busy .fm-layer, .fm-stage.busy .fm-patch { filter: blur(6px); transition: filter 0.2s; }
.fm-busy {
  position: absolute;
  inset: 0;
  z-index: 2001;
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
.fm-warn { color: #b3261e; }
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
