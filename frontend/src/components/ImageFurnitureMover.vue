<script setup>
/**
 * 在任何一張圖上直接拖曳家具（照片入口、直接描述的結果）。外觀跟 FurnitureMover 一樣，
 * 但不需要相機或家具配置：點家具 → SAM 2 切出整件 → 依地平線透視縮放拖曳 → 套用時一次 inpaint 補洞融邊。
 */
import { ref, computed, watch, onBeforeUnmount } from 'vue'
import { pickImageFurniture, moveImageFurniture, applyingImageMove } from '@/composables/design-flow/imageMove'

const props = defineProps({
  imageUrl: { type: String, required: true },
  imagePath: { type: String, required: true },
  canUndo: { type: Boolean, default: false },
})
const emit = defineEmits(['close', 'applied', 'undo'])

const imgRef = ref(null)
const picked = ref(null)         // pick 回傳：mask_path / layer_url / bbox / anchor / horizon_y
const offset = ref({ x: 0, y: 0 })
const picking = ref(false)
const dragging = ref(false)
const errorMsg = ref('')

watch(() => props.imageUrl, () => resetPick())

const anchorNow = computed(() => {
  const p = picked.value
  if (!p) return null
  // 錨點拖到地平線以上就沒有地板可放，壓在地平線下一點
  return { x: p.anchor.x + offset.value.x, y: Math.max(p.anchor.y + offset.value.y, p.horizon_y + 0.02) }
})
const moved = computed(() => !!picked.value && Math.abs(offset.value.x) + Math.abs(offset.value.y) > 2e-3)
// 地板上的東西大小跟離地平線的距離成正比（跟後端 image_move.perspective_scale 一樣）
const scale = computed(() => {
  const p = picked.value
  if (!p) return 1
  return Math.min(4, Math.max(0.2, (anchorNow.value.y - p.horizon_y) / Math.max(p.anchor.y - p.horizon_y, 0.01)))
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
  if (applyingImageMove.value || picking.value) return
  const pt = relPoint(e)
  if (pt.x < 0 || pt.x > 1 || pt.y < 0 || pt.y > 1) return
  errorMsg.value = ''
  picking.value = true
  try {
    const hit = await pickImageFurniture(props.imagePath, pt.x, pt.y)
    picked.value = hit
    offset.value = { x: 0, y: 0 }
    if (!hit) errorMsg.value = '這裡沒有可以移動的家具，請點家具本身。'
  } catch (err) {
    errorMsg.value = `選取失敗：${err.message}`
  } finally {
    picking.value = false
  }
}

let start = null
function onLayerDown(e) {
  if (applyingImageMove.value) return
  e.currentTarget.setPointerCapture(e.pointerId)
  start = { pt: relPoint(e), offset: { ...offset.value } }
  dragging.value = true
}
function onLayerMove(e) {
  if (!dragging.value) return
  const pt = relPoint(e)
  offset.value = { x: start.offset.x + pt.x - start.pt.x, y: start.offset.y + pt.y - start.pt.y }
}
function onLayerUp() { dragging.value = false }

function resetPick() {
  picked.value = null
  offset.value = { x: 0, y: 0 }
  errorMsg.value = ''
}

async function onApply() {
  if (!picked.value || !moved.value || applyingImageMove.value) return
  errorMsg.value = ''
  const a = anchorNow.value
  try {
    const data = await moveImageFurniture(props.imagePath, picked.value, {
      x: Math.min(1, Math.max(0, a.x)), y: Math.min(1, Math.max(0, a.y)),
    })
    resetPick()
    emit('applied', data)
  } catch (err) {
    errorMsg.value = `移動失敗：${err.message}`
  }
}

function onKey(e) {
  if (e.key !== 'Escape' || applyingImageMove.value) return
  if (picked.value) resetPick()
  else emit('close')
}
window.addEventListener('keydown', onKey)
onBeforeUnmount(() => window.removeEventListener('keydown', onKey))
</script>

<template>
  <div class="fm">
    <div class="fm-stage" :class="{ busy: applyingImageMove, picking }" @pointerdown="onStageDown">
      <img ref="imgRef" :src="imageUrl" alt="要移動家具的圖" class="fm-img" draggable="false" />

      <template v-if="picked">
        <!-- 原位置先框出來，拖走後看得出是從哪裡搬的 -->
        <div v-if="moved" class="fm-origin" :style="boxStyle(picked.bbox)"></div>
        <img
          :src="picked.layer_url" class="fm-layer" :class="{ dragging }" :style="layerStyle" alt="" draggable="false"
          @pointerdown.stop="onLayerDown" @pointermove="onLayerMove" @pointerup="onLayerUp" @pointercancel="onLayerUp"
        />
      </template>

      <div class="fm-corner">
        <button type="button" title="結束移動家具（Esc）" @pointerdown.stop @click="emit('close')">✕</button>
      </div>

      <div v-if="applyingImageMove" class="fm-busy" role="status">
        <div class="fm-spinner"></div>
        <p>AI 正在補上原位置、融合新位置…</p>
      </div>
    </div>

    <div class="fm-bar">
      <p class="fm-hint">
        <template v-if="picking">選取中…（每張圖第一次要先辨識家具輪廓，約 10 秒）</template>
        <template v-else-if="!picked">點一下圖上要移動的家具</template>
        <template v-else-if="!moved">拖曳選到的家具到新位置（往後變小、往前變大）</template>
        <template v-else>放好了就按「套用」，AI 會補上原位置並融合光影</template>
      </p>
      <div class="fm-actions">
        <button v-if="canUndo" type="button" class="fm-link" :disabled="applyingImageMove" @click="emit('undo')">↶ 復原上一次</button>
        <button v-if="picked" type="button" class="db-btn db-btn--ghost db-btn--sm" :disabled="applyingImageMove" @click="resetPick">換一件</button>
        <button type="button" class="db-btn db-btn--sm" :disabled="!picked || !moved || applyingImageMove" @click="onApply">套用</button>
      </div>
      <p v-if="errorMsg" class="fm-error" role="alert">{{ errorMsg }}</p>
    </div>
  </div>
</template>

<style scoped>
.fm { display: flex; flex-direction: column; gap: 0.9rem; width: 100%; }
.fm-stage {
  position: relative; align-self: center; max-width: 100%; line-height: 0;
  border-radius: 8px; overflow: hidden; cursor: crosshair; touch-action: none; user-select: none;
}
.fm-stage.picking { cursor: progress; }
.fm-img { display: block; max-width: 100%; max-height: 75vh; }

.fm-origin {
  position: absolute; pointer-events: none;
  border: 2px dashed rgba(255, 255, 255, 0.9); border-radius: 4px;
  background: rgba(20, 18, 14, 0.35);
}
.fm-layer {
  position: absolute; cursor: grab;
  filter: drop-shadow(0 0 1.5px #fff) drop-shadow(0 0 1px var(--db-accent)) drop-shadow(0 6px 10px rgba(0, 0, 0, 0.35));
}
.fm-layer.dragging { cursor: grabbing; opacity: 0.92; }

.fm-corner { position: absolute; top: 0.75rem; right: 0.75rem; }
.fm-corner button {
  padding: 0.4rem 0.7rem; border: none; border-radius: var(--db-radius-pill);
  background: rgba(20, 18, 14, 0.78); color: #fff; line-height: 1; cursor: pointer;
}

.fm-stage.busy .fm-img, .fm-stage.busy .fm-layer { filter: blur(6px); transition: filter 0.2s; }
.fm-stage.busy { pointer-events: none; }
.fm-busy {
  position: absolute; inset: 0; display: flex; flex-direction: column; align-items: center; justify-content: center;
  gap: 0.6rem; background: rgba(20, 18, 14, 0.25); color: #fff; font-size: 0.9rem; line-height: 1.4;
  text-shadow: 0 1px 3px rgba(0, 0, 0, 0.6);
}
.fm-spinner {
  width: 32px; height: 32px; border: 3px solid rgba(255, 255, 255, 0.3); border-top-color: #fff;
  border-radius: 50%; animation: fm-spin 0.8s linear infinite;
}
@keyframes fm-spin { to { transform: rotate(360deg); } }

.fm-bar { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 0.6rem; }
.fm-hint { margin: 0; font-size: 0.88rem; color: var(--db-text-soft); }
.fm-actions { display: flex; align-items: center; gap: 0.6rem; }
.fm-link {
  border: none; background: none; padding: 0; color: var(--db-accent-deep); font-size: 0.85rem;
  text-decoration: underline; text-underline-offset: 3px; cursor: pointer;
}
.fm-link:disabled { opacity: 0.4; cursor: not-allowed; }
.fm-error { flex-basis: 100%; margin: 0; font-size: 0.82rem; color: #b3261e; }
</style>
