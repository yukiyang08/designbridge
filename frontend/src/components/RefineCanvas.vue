<script setup>
import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue'

const props = defineProps({
  imageUrl:  { type: String,  required: true },
  brushSize: { type: Number,  default: 32 },     // 螢幕上的直徑（px），縮放後視覺大小不變
  drawMode:  { type: String,  default: 'draw' }, // 'draw' | 'erase' | 'pan'
  fill:      { type: Boolean, default: false },  // true：撐滿父層（全螢幕）；false：高度依圖片比例
})

const MAX_ZOOM = 4
const MASK_LONG_EDGE = 1536   // 遮罩解析度上限，不必跟原圖一樣大

const rootRef = ref(null)
const drawRef = ref(null)
const nat = ref({ w: 16, h: 9 })     // 圖片原始尺寸
const box = ref({ w: 0, h: 0 })      // 容器尺寸
const zoom = ref(1)
const pan = ref({ x: 0, y: 0 })
const hasMask = ref(false)
const ring = ref(null)               // 游標位置（容器座標），畫筆預覽圈用
const spaceDown = ref(false)
let stroke = null
let ro = null

// 圖片在容器內「contain」後的實際位置
const fit = computed(() => {
  const { w, h } = box.value
  if (!w || !h) return { w: 0, h: 0, left: 0, top: 0 }
  const s = Math.min(w / nat.value.w, h / nat.value.h)
  const dw = nat.value.w * s
  const dh = nat.value.h * s
  return { w: dw, h: dh, left: (w - dw) / 2, top: (h - dh) / 2 }
})

const panning = computed(() => props.drawMode === 'pan' || spaceDown.value)
const rootStyle = computed(() => props.fill ? {} : {
  aspectRatio: `${nat.value.w} / ${nat.value.h}`,
  maxHeight: '72vh',
})
const stageStyle = computed(() => ({
  left: `${fit.value.left}px`, top: `${fit.value.top}px`,
  width: `${fit.value.w}px`, height: `${fit.value.h}px`,
  transform: `translate(${pan.value.x}px, ${pan.value.y}px) scale(${zoom.value})`,
}))
const ringStyle = computed(() => ({
  left: `${ring.value.x}px`, top: `${ring.value.y}px`,
  width: `${props.brushSize}px`, height: `${props.brushSize}px`,
}))

// ── 縮放／平移 ────────────────────────────────────────────
// 放大後圖片一定蓋滿視窗；沒放大就置中
function clampAxis(p, view, size, off) {
  const full = size * zoom.value
  return full <= view ? (view - full) / 2 - off : Math.min(-off, Math.max(view - off - full, p))
}
function clampPan(x, y) {
  return {
    x: clampAxis(x, box.value.w, fit.value.w, fit.value.left),
    y: clampAxis(y, box.value.h, fit.value.h, fit.value.top),
  }
}
// 以 (cx, cy)（容器座標）為中心縮放，游標下的那一點不動
function setZoom(next, cx = box.value.w / 2, cy = box.value.h / 2) {
  const z2 = Math.min(MAX_ZOOM, Math.max(1, next))
  const z = zoom.value
  const sx = (cx - fit.value.left - pan.value.x) / z
  const sy = (cy - fit.value.top - pan.value.y) / z
  zoom.value = z2
  pan.value = clampPan(cx - fit.value.left - sx * z2, cy - fit.value.top - sy * z2)
}
function resetView() { setZoom(1) }

function onWheel(e) {
  // 內嵌時一般滾輪留給頁面捲動，要 Ctrl＋滾輪才縮放；全螢幕沒有頁面可捲，直接縮放
  if (!props.fill && !e.ctrlKey) return
  e.preventDefault()
  const r = rootRef.value.getBoundingClientRect()
  setZoom(zoom.value * (e.deltaY < 0 ? 1.15 : 1 / 1.15), e.clientX - r.left, e.clientY - r.top)
}

// ── 初始化／換圖 ──────────────────────────────────────────
function onImgLoad(e) {
  const { naturalWidth: w, naturalHeight: h } = e.target
  nat.value = { w, h }
  const k = Math.min(1, MASK_LONG_EDGE / Math.max(w, h))
  const mw = Math.round(w * k)
  const mh = Math.round(h * k)
  const c = drawRef.value
  if (c.width !== mw || c.height !== mh) { c.width = mw; c.height = mh }   // 改尺寸會一併清空
  else c.getContext('2d').clearRect(0, 0, mw, mh)
  hasMask.value = false
  pan.value = clampPan(pan.value.x, pan.value.y)
}

function measure() {
  const r = rootRef.value
  if (!r) return
  box.value = { w: r.clientWidth, h: r.clientHeight }
  pan.value = clampPan(pan.value.x, pan.value.y)
}

function onKey(e) {
  if (e.code !== 'Space') return
  if (/^(INPUT|TEXTAREA)$/.test(e.target?.tagName)) return
  spaceDown.value = e.type === 'keydown'
  e.preventDefault()   // 免得空白鍵把頁面捲走
}

onMounted(() => {
  ro = new ResizeObserver(measure)
  ro.observe(rootRef.value)
  measure()
  window.addEventListener('keydown', onKey)
  window.addEventListener('keyup', onKey)
})
onBeforeUnmount(() => {
  ro?.disconnect()
  window.removeEventListener('keydown', onKey)
  window.removeEventListener('keyup', onKey)
})
watch(() => props.fill, () => { zoom.value = 1; pan.value = { x: 0, y: 0 } })

// ── 繪圖 ──────────────────────────────────────────────────
// 螢幕座標 → 遮罩座標；k = 遮罩像素 / 螢幕像素（已含縮放），筆刷寬度據此換算
function toMask(e) {
  const c = drawRef.value
  const r = c.getBoundingClientRect()
  const k = c.width / r.width
  return { x: (e.clientX - r.left) * k, y: (e.clientY - r.top) * k, k }
}

function paintSeg(a, b) {
  const ctx = drawRef.value.getContext('2d')
  ctx.globalCompositeOperation = props.drawMode === 'erase' ? 'destination-out' : 'source-over'
  ctx.strokeStyle = '#ff3c3c'   // 不透明，顯示時再用 CSS 降透明度，筆劃重疊才不會變深
  ctx.lineCap = 'round'
  ctx.lineWidth = props.brushSize * b.k
  ctx.beginPath()
  ctx.moveTo(a.x, a.y)
  ctx.lineTo(b.x, b.y)
  ctx.stroke()
}

function onDown(e) {
  if (e.button === 2) return
  rootRef.value.setPointerCapture(e.pointerId)
  if (panning.value || e.button === 1) {
    stroke = { pan: true, x: e.clientX, y: e.clientY }
    return
  }
  const p = toMask(e)
  stroke = { pan: false, last: p }
  paintSeg(p, p)
}

function onMove(e) {
  const r = rootRef.value.getBoundingClientRect()
  ring.value = { x: e.clientX - r.left, y: e.clientY - r.top }
  if (!stroke) return
  if (stroke.pan) {
    pan.value = clampPan(pan.value.x + e.clientX - stroke.x, pan.value.y + e.clientY - stroke.y)
    stroke.x = e.clientX; stroke.y = e.clientY
    return
  }
  const p = toMask(e)
  paintSeg(stroke.last, p)
  stroke.last = p
}

function onUp() {
  if (stroke && !stroke.pan) refreshHasMask()
  stroke = null
}

// 縮成 128px 再掃，比掃整張遮罩便宜
function refreshHasMask() {
  const t = document.createElement('canvas')
  t.width = t.height = 128
  const ctx = t.getContext('2d')
  ctx.drawImage(drawRef.value, 0, 0, 128, 128)
  const d = ctx.getImageData(0, 0, 128, 128).data
  let any = false
  for (let i = 3; i < d.length; i += 4) if (d[i] > 0) { any = true; break }
  hasMask.value = any
}

// 正規化框 [x0, y0, x1, y1] 整塊塗進遮罩（快速圈選偵測到的家具）
function paintBox(box) {
  const c = drawRef.value
  const [x0, y0, x1, y1] = box
  const ctx = c.getContext('2d')
  ctx.globalCompositeOperation = 'source-over'
  ctx.fillStyle = '#ff3c3c'
  ctx.fillRect(x0 * c.width, y0 * c.height, (x1 - x0) * c.width, (y1 - y0) * c.height)
  hasMask.value = true
}

function clearMask() {
  const c = drawRef.value
  c.getContext('2d').clearRect(0, 0, c.width, c.height)
  hasMask.value = false
}

// ── 匯出黑白遮罩 Blob ─────────────────────────────────────
function getMaskBlob() {
  return new Promise(resolve => {
    const draw = drawRef.value
    const { width: w, height: h } = draw
    const pixels = draw.getContext('2d').getImageData(0, 0, w, h)
    // 沒有塗抹任何區域 → 回傳 null，整張重繪
    let hasDrawing = false
    for (let i = 3; i < pixels.data.length; i += 4) {
      if (pixels.data[i] > 10) { hasDrawing = true; break }
    }
    if (!hasDrawing) { resolve(null); return }

    const mc = document.createElement('canvas')
    mc.width = w; mc.height = h
    const mCtx = mc.getContext('2d')
    const mData = mCtx.createImageData(w, h)
    for (let i = 0; i < pixels.data.length; i += 4) {
      const v = pixels.data[i + 3] > 10 ? 255 : 0
      mData.data[i] = mData.data[i+1] = mData.data[i+2] = v
      mData.data[i + 3] = 255
    }
    mCtx.putImageData(mData, 0, 0)
    mc.toBlob(resolve, 'image/png')
  })
}

defineExpose({ getMaskBlob, clearMask, paintBox, hasMask, resetView })
</script>

<template>
  <div
    ref="rootRef"
    class="canvas-root"
    :class="{ fill, 'is-pan': panning }"
    :style="rootStyle"
    @wheel="onWheel"
    @pointerdown="onDown"
    @pointermove="onMove"
    @pointerup="onUp"
    @pointercancel="onUp"
    @pointerleave="ring = null"
    @contextmenu.prevent
  >
    <div class="stage" :style="stageStyle">
      <img :src="imageUrl" class="layer" alt="" draggable="false" @load="onImgLoad" />
      <canvas ref="drawRef" class="layer mask" />
    </div>

    <span v-if="ring && !panning" class="ring" :class="{ 'is-erase': drawMode === 'erase' }" :style="ringStyle" />

    <!-- 右上角：父層的按鈕（全螢幕、關閉）＋縮放 -->
    <div class="corner" @pointerdown.stop @pointermove.stop>
      <slot name="corner" />
      <div class="zoom">
        <button type="button" :disabled="zoom <= 1" aria-label="縮小" @click="setZoom(zoom / 1.25)">−</button>
        <button type="button" class="zoom-val" title="重設為 100%" @click="resetView">{{ Math.round(zoom * 100) }}%</button>
        <button type="button" :disabled="zoom >= MAX_ZOOM" aria-label="放大" @click="setZoom(zoom * 1.25)">＋</button>
      </div>
    </div>

    <div class="hint">
      紅色 = 要修改的區域 · {{ fill ? '滾輪' : 'Ctrl＋滾輪' }}縮放 · 空白鍵拖曳平移
    </div>
  </div>
</template>

<style scoped>
.canvas-root {
  position: relative;
  width: 100%;
  background: #1a0d08;
  overflow: hidden;
  touch-action: none;
  user-select: none;
  cursor: none;   /* 用 .ring 取代游標，筆刷大小所見即所得 */
}
.canvas-root.fill { height: 100%; }
.canvas-root.is-pan { cursor: grab; }
.canvas-root.is-pan:active { cursor: grabbing; }

.stage {
  position: absolute;
  transform-origin: 0 0;
  will-change: transform;
}
.layer {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  pointer-events: none;
}
/* 遮罩加一圈白＋深色的描邊：暖色調的圖上半透明紅色幾乎融進去，有沒有擦掉、邊界在哪都看不清楚 */
.mask {
  opacity: 0.55;
  filter: drop-shadow(0 0 1.5px rgba(255, 255, 255, 0.95)) drop-shadow(0 0 1px rgba(0, 0, 0, 0.7));
}

.ring {
  position: absolute;
  transform: translate(-50%, -50%);
  border: 1.5px solid #fff;
  border-radius: 50%;
  box-shadow: 0 0 0 1px rgba(0, 0, 0, 0.55);
  pointer-events: none;
}
/* 橡皮擦：虛線圈＋淡白底＋斜線，跟畫筆的實線圈一眼分得出來 */
.ring.is-erase {
  border: 2px dashed #fff;
  background:
    linear-gradient(135deg, transparent calc(50% - 1px), rgba(255, 255, 255, 0.85) calc(50% - 1px), rgba(255, 255, 255, 0.85) calc(50% + 1px), transparent calc(50% + 1px)),
    rgba(255, 255, 255, 0.18);
}

.corner {
  position: absolute;
  top: 0.6rem;
  right: 0.6rem;
  display: flex;
  align-items: center;
  gap: 0.4rem;
  cursor: default;
}
.corner :deep(button), .zoom button {
  min-width: 2rem;
  height: 2rem;
  padding: 0 0.55rem;
  border: none;
  border-radius: 6px;
  background: rgba(20, 18, 14, 0.7);
  color: #fff;
  font-size: 0.95rem;
  line-height: 1;
  cursor: pointer;
}
.corner :deep(button:hover:not(:disabled)), .zoom button:hover:not(:disabled) { background: rgba(20, 18, 14, 0.9); }
.zoom button:disabled { opacity: 0.4; cursor: not-allowed; }
.zoom { display: flex; gap: 1px; }
.zoom button:first-child { border-radius: 6px 0 0 6px; }
.zoom button:last-child { border-radius: 0 6px 6px 0; }
.zoom button { border-radius: 0; }
.zoom-val { min-width: 3.4rem; font-size: 0.8rem !important; font-variant-numeric: tabular-nums; }

.hint {
  position: absolute;
  bottom: 0.6rem;
  left: 50%;
  transform: translateX(-50%);
  font-size: 0.72rem;
  color: rgba(255, 255, 255, 0.55);
  pointer-events: none;
  white-space: nowrap;
}
</style>
