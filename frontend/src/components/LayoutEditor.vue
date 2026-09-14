<script setup>
import { ref, computed } from 'vue'
import { Icon } from '@iconify/vue'
import {
  furnitureLabel, furnitureIcon, furnitureDefaultSize,
  ROOM_OPTIONS, FURNITURE_BY_ROOM,
} from '@/config/furniture'

/**
 * Interactive 2D layout editor. Furniture are draggable / resizable / rotatable
 * boxes positioned with normalized [0,1] coordinates inside a square room, matching
 * the coordinate system used by the backend (x=left→right, y=back→front).
 */
const props = defineProps({
  placements: { type: Array, default: () => [] },
  roomType: { type: String, default: 'living_room' },  // 家具面板預設分類
})
const emit = defineEmits(['update:placements', 'room-size-changed'])

// 公尺，點畫布外框可直接調整（雙向綁定回父層，3D 預覽/最終渲染跟著用同一組數字）
const roomW = defineModel('roomW', { default: 5 })
const roomD = defineModel('roomD', { default: 4 })

const FLOOR_TYPES = new Set(['rug', 'carpet'])
const isFloor = (t) => FLOOR_TYPES.has(t)

// ── Collision：一般家具不可疊放，地毯/地墊類（FLOOR_TYPES）例外可疊 ──────
function rectsOverlap(a, b) {
  return a.x < b.x + b.w && a.x + a.w > b.x && a.y < b.y + b.h && a.y + a.h > b.y
}
function collidesWithOthers(rect, type, excludeId) {
  if (isFloor(type)) return false
  return items.value.some((it) => (
    it.id !== excludeId && !isFloor(it.type) && rectsOverlap(rect, it)
  ))
}
const labelOf = (t) => furnitureLabel(t)
const iconOf = (t) => furnitureIcon(t)
const SNAP = 0.03           // wall-snap threshold (normalized)
const MIN = 0.04            // min box size

const boardRef = ref(null)
const selectedId = ref(null)
let drag = null             // active drag/resize state

// Local editable copy that syncs up on every change.
const items = computed(() => props.placements)
const selectedItem = computed(() => items.value.find((it) => it.id === selectedId.value) || null)

function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)) }

// ── History (undo/redo) ─────────────────────────────────────────
// Only discrete actions (add/remove/rotate/panel edits, and a finished drag) push an
// undo point — pushing on every drag frame would make undo useless (one step per pixel).
const historyStack = ref([])
const redoStack = ref([])
function snapshot() { return items.value.map((it) => ({ ...it })) }
function pushHistory() {
  historyStack.value.push(snapshot())
  if (historyStack.value.length > 50) historyStack.value.shift()
  redoStack.value = []
}
function commit(next) {              // live update while dragging — no history point
  emit('update:placements', next)
}
function undo() {
  if (!historyStack.value.length) return
  redoStack.value.push(snapshot())
  const prev = historyStack.value.pop()
  if (selectedId.value && !prev.some((it) => it.id === selectedId.value)) selectedId.value = null
  emit('update:placements', prev)
}
function redo() {
  if (!redoStack.value.length) return
  historyStack.value.push(snapshot())
  emit('update:placements', redoStack.value.pop())
}

function boardSize() {
  const el = boardRef.value
  return el ? Math.min(el.clientWidth, el.clientHeight) : 1
}

// ── Pointer handlers ────────────────────────────────────────────
let dragSnapshot = null
function onDown(e, item, mode) {
  e.preventDefault()
  e.stopPropagation()
  selectedId.value = item.id
  if (item.locked) return   // 鎖定：可選取查看設定，但不能拖曳/縮放
  dragSnapshot = snapshot()
  drag = {
    id: item.id, mode,
    startX: e.clientX, startY: e.clientY,
    ox: item.x, oy: item.y, ow: item.w, oh: item.h,
    size: boardSize(),
  }
  window.addEventListener('pointermove', onMove)
  window.addEventListener('pointerup', onUp)
}

function onMove(e) {
  if (!drag) return
  const dx = (e.clientX - drag.startX) / drag.size
  const dy = (e.clientY - drag.startY) / drag.size
  const next = items.value.map((it) => {
    if (it.id !== drag.id) return it
    if (drag.mode === 'move') {
      const x = clamp(drag.ox + dx, 0, 1 - it.w)
      const y = clamp(drag.oy + dy, 0, 1 - it.h)
      // 撞到別的家具（非地毯類）：卡在目前位置，不繼續往那個方向移動
      if (collidesWithOthers({ x, y, w: it.w, h: it.h }, it.type, it.id)) return it
      return { ...it, x, y }
    }
    // resize from bottom-right corner
    const w = clamp(drag.ow + dx, MIN, 1 - drag.ox)
    const h = clamp(drag.oh + dy, MIN, 1 - drag.oy)
    if (collidesWithOthers({ x: drag.ox, y: drag.oy, w, h }, it.type, it.id)) return it
    return { ...it, w, h }
  })
  commit(next)
}

function onUp() {
  // wall snap on release (move only)
  if (drag && drag.mode === 'move') {
    const next = items.value.map((it) => {
      if (it.id !== drag.id) return it
      const { x: ox, y: oy, w, h } = it
      let x = ox, y = oy
      if (x < SNAP) x = 0
      if (x + w > 1 - SNAP) x = 1 - w
      if (y < SNAP) y = 0
      if (y + h > 1 - SNAP) y = 1 - h
      // 貼牆會撞到別的家具的話，維持原位不貼牆
      if ((x !== ox || y !== oy) && collidesWithOthers({ x, y, w, h }, it.type, it.id)) return it
      return { ...it, x, y }
    })
    commit(next)
  }
  if (dragSnapshot) {
    historyStack.value.push(dragSnapshot)
    if (historyStack.value.length > 50) historyStack.value.shift()
    redoStack.value = []
    dragSnapshot = null
  }
  drag = null
  window.removeEventListener('pointermove', onMove)
  window.removeEventListener('pointerup', onUp)
}

// ── Item ops ────────────────────────────────────────────────────
// 90° 增量旋轉：交換 footprint 的 w/h（保持中心點不變）。後端的碰撞偵測/深度投影只讀
// x/y/w/h 當成永遠是「已經是正的」矩形，不知道 rotation 這件事——所以只支援 90° 倍數，
// 用交換寬深來讓 footprint 本身保持正確，而不是疊加 CSS transform 讓兩邊對不起來。
function rotateNTimes90(item, times) {
  let { x, y, w, h, rotation } = item
  rotation = rotation || 0
  for (let i = 0; i < times; i++) {
    const cx = x + w / 2, cy = y + h / 2
    ;[w, h] = [h, w]
    x = clamp(cx - w / 2, 0, 1 - w)
    y = clamp(cy - h / 2, 0, 1 - h)
    rotation = (rotation + 90) % 360
  }
  return { ...item, x, y, w, h, rotation }
}

function rotate90(item) {
  if (!item) return
  pushHistory()
  const rotated = rotateNTimes90(item, 1)
  commit(items.value.map((it) => (it.id === item.id ? rotated : it)))
}

// 面板輸入任意角度：四捨五入到最近的 90° 倍數（理由同上，footprint 只能用交換寬深表達）。
function setRotationDeg(item, deg) {
  if (!item) return
  const target = (((Math.round(deg / 90) * 90) % 360) + 360) % 360
  const current = item.rotation || 0
  if (target === current) return
  const steps = ((target - current) / 90 + 4) % 4
  pushHistory()
  const rotated = rotateNTimes90(item, steps)
  commit(items.value.map((it) => (it.id === item.id ? rotated : it)))
}

function removeItem(item) {
  if (!item) return
  pushHistory()
  commit(items.value.filter((it) => it.id !== item.id))
  if (selectedId.value === item.id) selectedId.value = null
}

// 從房間正中心開始找，撞到別的家具（非地毯類）就往外一圈圈找空位；實在找不到才疊放。
function findFreeSpot(w, h, type) {
  const cx = clamp(0.5 - w / 2, 0, 1 - w)
  const cy = clamp(0.5 - h / 2, 0, 1 - h)
  if (!collidesWithOthers({ x: cx, y: cy, w, h }, type, null)) return { x: cx, y: cy }
  const step = 0.08
  for (let ring = 1; ring <= 8; ring++) {
    for (const [dx, dy] of [[1,0],[-1,0],[0,1],[0,-1],[1,1],[-1,1],[1,-1],[-1,-1]]) {
      const x = clamp(cx + dx * ring * step, 0, 1 - w)
      const y = clamp(cy + dy * ring * step, 0, 1 - h)
      if (!collidesWithOthers({ x, y, w, h }, type, null)) return { x, y }
    }
  }
  return { x: cx, y: cy }
}

function addItem(type) {
  const [w, h] = furnitureDefaultSize(type)
  const id = `${type}_${Date.now().toString(36)}`
  const { x, y } = findFreeSpot(w, h, type)
  const item = { id, type, w, h, x, y, rotation: 0, locked: false }
  pushHistory()
  commit([...items.value, item])
  selectedId.value = id
}

function updateSelectedField(key, value) {
  if (!selectedItem.value) return
  pushHistory()
  commit(items.value.map((it) => (it.id === selectedItem.value.id ? { ...it, [key]: value } : it)))
}

// ── Properties panel bindings ────────────────────────────────────
const widthCm = computed({
  get: () => (selectedItem.value ? Math.round(selectedItem.value.w * roomW.value * 100) : 0),
  set: (cm) => { if (cm > 0) updateSelectedField('w', clamp(cm / 100 / roomW.value, MIN, 1)) },
})
const depthCm = computed({
  get: () => (selectedItem.value ? Math.round(selectedItem.value.h * roomD.value * 100) : 0),
  set: (cm) => { if (cm > 0) updateSelectedField('h', clamp(cm / 100 / roomD.value, MIN, 1)) },
})

// ── Room frame selection & resize ─────────────────────────────────
// 點畫布外框選取「房間」，右側面板改顯示房間長寬（跟選家具時共用同一個面板位置）。
const ROOM_SEL = '__ROOM__'
function selectRoom() { selectedId.value = ROOM_SEL }
const roomWidthCm = computed({
  get: () => Math.round(roomW.value * 100),
  set: (cm) => { if (cm > 0) { roomW.value = Math.round(cm) / 100; emit('room-size-changed') } },
})
const roomDepthCm = computed({
  get: () => Math.round(roomD.value * 100),
  set: (cm) => { if (cm > 0) { roomD.value = Math.round(cm) / 100; emit('room-size-changed') } },
})
const rotationDeg = computed({
  get: () => selectedItem.value?.rotation || 0,
  set: (deg) => setRotationDeg(selectedItem.value, Number(deg) || 0),
})
const lockedModel = computed({
  get: () => !!selectedItem.value?.locked,
  set: (val) => updateSelectedField('locked', val),
})

// ── Furniture palette ─────────────────────────────────────────────
const paletteRoomType = ref(props.roomType)
const paletteCatalog = computed(() => FURNITURE_BY_ROOM[paletteRoomType.value] || [])

// ── Zoom ───────────────────────────────────────────────────────
const zoom = ref(1)
function zoomIn() { zoom.value = Math.min(2, Math.round((zoom.value + 0.2) * 10) / 10) }
function zoomOut() { zoom.value = Math.max(0.5, Math.round((zoom.value - 0.2) * 10) / 10) }

function pct(v) { return `${v * 100}%` }

// 畫布長寬比跟著實際房間走，但夾在 [0.5, 2] 之間——太狹長的自訂尺寸（例如 2m x 15m）
// 若照真實比例畫，畫布會高到把整個編輯區撐爆；夾住範圍讓它保持在編輯區內，一般房間的
// 比例本來就落在這個區間，不會有感覺。
const boardAspect = computed(() => {
  const ratio = (roomW.value || 5) / (roomD.value || 4)
  return Math.max(0.5, Math.min(2, ratio))
})
</script>

<template>
  <div class="editor">
    <div class="toolbar">
      <button class="tool-btn active" @click="selectedId = null" title="取消選取">
        <Icon icon="mdi:cursor-default-outline" width="16" /><span>選取</span>
      </button>
      <span class="tool-sep" />
      <button class="tool-btn" :disabled="!selectedItem" @click="rotate90(selectedItem)" title="旋轉 90°">
        <Icon icon="mdi:rotate-right" width="16" /><span>旋轉</span>
      </button>
      <button class="tool-btn" @click="zoomIn" title="放大">
        <Icon icon="mdi:magnify-plus-outline" width="16" /><span>放大</span>
      </button>
      <button class="tool-btn" @click="zoomOut" title="縮小">
        <Icon icon="mdi:magnify-minus-outline" width="16" /><span>縮小</span>
      </button>
      <button class="tool-btn" :disabled="!selectedItem" @click="removeItem(selectedItem)" title="刪除">
        <Icon icon="mdi:trash-can-outline" width="16" /><span>刪除</span>
      </button>
      <span class="tool-sep" />
      <button class="tool-btn" :disabled="!historyStack.length" @click="undo" title="復原">
        <Icon icon="mdi:undo" width="16" /><span>復原</span>
      </button>
      <button class="tool-btn" :disabled="!redoStack.length" @click="redo" title="重做">
        <Icon icon="mdi:redo" width="16" /><span>重做</span>
      </button>
    </div>

    <div class="workspace">
      <!-- ── 家具面板 ── -->
      <aside class="palette">
        <div class="palette-title">家具</div>
        <select v-model="paletteRoomType" class="palette-room-select">
          <option v-for="r in ROOM_OPTIONS" :key="r.value" :value="r.value">{{ r.label }}</option>
        </select>
        <div class="palette-list">
          <button v-for="c in paletteCatalog" :key="c.value" class="palette-item" @click="addItem(c.value)">
            <Icon :icon="iconOf(c.value)" class="palette-item-icon" />
            <span class="palette-item-label">{{ c.label }}</span>
            <Icon icon="mdi:plus" class="palette-item-add" />
          </button>
        </div>
        <p class="palette-hint">點擊 + 加入畫布</p>
      </aside>

      <!-- ── 畫布 ── -->
      <div class="board-viewport">
        <div ref="boardRef" class="board"
             :style="{ transform: `scale(${zoom})`, aspectRatio: boardAspect }"
             @pointerdown="selectedId = null">
          <div class="grid"></div>
          <div class="door" title="門"></div>
          <div class="window" title="窗"></div>

          <!-- 點外框可選取「房間」，調整整體長寬（見下方家具設定面板的房間分支） -->
          <div class="frame-hit frame-top"    title="調整房間尺寸" @pointerdown.stop="selectRoom"></div>
          <div class="frame-hit frame-bottom" title="調整房間尺寸" @pointerdown.stop="selectRoom"></div>
          <div class="frame-hit frame-left"   title="調整房間尺寸" @pointerdown.stop="selectRoom"></div>
          <div class="frame-hit frame-right"  title="調整房間尺寸" @pointerdown.stop="selectRoom"></div>

          <div
            v-for="item in items"
            :key="item.id"
            class="node"
            :class="{ floor: isFloor(item.type), selected: selectedId === item.id, locked: item.locked }"
            :style="{ left: pct(item.x), top: pct(item.y), width: pct(item.w), height: pct(item.h) }"
            @pointerdown="onDown($event, item, 'move')"
          >
            <Icon :icon="iconOf(item.type)" class="node-icon" />
            <span class="node-label">{{ labelOf(item.type) }}</span>
            <Icon v-if="item.locked" icon="mdi:lock-outline" class="node-lock" />

            <template v-if="selectedId === item.id && !item.locked">
              <button class="node-btn rotate" title="旋轉 90°"
                      @pointerdown.stop @click.stop="rotate90(item)">
                <Icon icon="mdi:rotate-right" width="11" />
              </button>
              <button class="node-btn del" title="刪除"
                      @pointerdown.stop @click.stop="removeItem(item)">
                <Icon icon="mdi:close" width="11" />
              </button>
              <div class="handle" @pointerdown="onDown($event, item, 'resize')"></div>
            </template>
          </div>
        </div>
      </div>

      <!-- ── 家具設定 ── -->
      <aside class="props-panel" v-if="selectedItem">
        <div class="props-header">
          <Icon :icon="iconOf(selectedItem.type)" width="20" />
          <span>{{ labelOf(selectedItem.type) }}</span>
        </div>
        <label class="props-field">
          <span>寬度 (cm)</span>
          <input type="number" v-model.number="widthCm" min="1" />
        </label>
        <label class="props-field">
          <span>深度 (cm)</span>
          <input type="number" v-model.number="depthCm" min="1" />
        </label>
        <label class="props-field">
          <span>旋轉角度 (°)</span>
          <input type="number" v-model.number="rotationDeg" step="90" />
        </label>
        <label class="props-toggle">
          <span>鎖定位置</span>
          <input type="checkbox" v-model="lockedModel" class="switch-input" />
        </label>
      </aside>
      <aside class="props-panel" v-else-if="selectedId === ROOM_SEL">
        <div class="props-header">
          <Icon icon="mdi:floor-plan" width="20" />
          <span>房間尺寸</span>
        </div>
        <label class="props-field">
          <span>長度 (cm)</span>
          <input type="number" v-model.number="roomWidthCm" min="100" />
        </label>
        <label class="props-field">
          <span>寬度 (cm)</span>
          <input type="number" v-model.number="roomDepthCm" min="100" />
        </label>
      </aside>
      <aside class="props-panel props-empty" v-else>
        <Icon icon="mdi:cursor-default-click-outline" width="24" />
        <p>點選畫布上的家具或外框以編輯</p>
      </aside>
    </div>

    <span class="hint">拖動移動 · 右下角縮放 · ⟳ 旋轉 · 靠牆自動吸附 · 點選外框可調整房間尺寸</span>
  </div>
</template>

<style scoped>
.editor { display: flex; flex-direction: column; gap: 0.6rem; width: 100%; }

/* ── Toolbar ── */
.toolbar {
  display: flex; align-items: center; gap: 0.3rem; flex-wrap: wrap;
  background: #fff; border: 1px solid #e7dcc9; border-radius: 10px; padding: 0.4rem;
}
.tool-btn {
  display: flex; flex-direction: column; align-items: center; gap: 0.15rem;
  border: none; background: transparent; color: #6b4f30;
  border-radius: 8px; padding: 0.35rem 0.6rem; font-size: 0.68rem;
  font-family: inherit; font-weight: 600; cursor: pointer; transition: all 0.15s;
}
.tool-btn:hover:not(:disabled) { background: #f7efe3; }
.tool-btn.active { background: #8B5E3C; color: #fff; }
.tool-btn:disabled { opacity: 0.35; cursor: default; }
.tool-sep { width: 1px; height: 24px; background: #e7dcc9; margin: 0 0.2rem; }
.hint { font-size: 0.74rem; color: #a08a6f; text-align: center; }

/* ── Workspace (palette | board | properties) ── */
.workspace { display: flex; gap: 0.75rem; align-items: flex-start; flex-wrap: wrap; }

.palette {
  width: 225px; flex-shrink: 0; background: #fff; border: 1px solid #e7dcc9;
  border-radius: 10px; padding: 0.6rem; display: flex; flex-direction: column; gap: 0.4rem;
}
.palette-title { font-size: 0.8rem; font-weight: 700; color: #5c4630; }
.palette-room-select {
  width: 100%; border: 1px solid #e2d4bf; border-radius: 6px; padding: 0.3rem 0.4rem;
  font-size: 0.76rem; font-family: inherit; background: #fdfaf5;
}
.palette-list {
  display: grid; grid-template-columns: repeat(auto-fill, minmax(68px, 1fr));
  gap: 0.4rem; max-height: 500px; overflow-y: auto;
}
.palette-item {
  position: relative;
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  gap: 0.3rem; border: none; background: #f7efe3;
  border-radius: 10px; padding: 0.55rem 0.35rem; font-size: 0.7rem; font-family: inherit;
  color: #5c4630; cursor: pointer; text-align: center;
}
.palette-item:hover { background: #ecdcc4; }
.palette-item-icon { font-size: 1.3rem; }
.palette-item-label { line-height: 1.15; }
.palette-item-add {
  position: absolute; top: 0.2rem; right: 0.2rem;
  color: #8B5E3C; font-size: 0.8rem;
}
.palette-hint { font-size: 0.68rem; color: #a08a6f; margin: 0; text-align: center; }

.board-viewport {
  flex: 1; min-width: 420px; max-height: 720px; overflow: auto;
  display: flex; justify-content: center;
}
.board {
  position: relative; width: 100%; max-width: 720px;
  background: #fbf6ee; transform-origin: top center;
  border: 3px solid #2b2b2b; border-radius: 4px; overflow: hidden;
  box-shadow: 0 4px 24px rgba(0,0,0,0.12); touch-action: none; flex-shrink: 0;
}
.grid {
  position: absolute; inset: 0;
  background-image:
    linear-gradient(to right, rgba(120,90,60,0.08) 1px, transparent 1px),
    linear-gradient(to bottom, rgba(120,90,60,0.08) 1px, transparent 1px);
  background-size: 20% 20%;
}
.door {
  position: absolute; bottom: -3px; left: 45%; width: 10%; height: 6px;
  background: #fbf6ee; border-bottom: 3px solid #bfae95;
}
.window {
  position: absolute; top: -3px; left: 40%; width: 20%; height: 6px;
  background: #c0daf8; border: 1.5px solid #2e6ab5;
}

/* 外框點擊熱區——貼著內側邊緣，board 本身 overflow:hidden 所以不能用負值往外伸 */
.frame-hit { position: absolute; cursor: pointer; }
.frame-top, .frame-bottom { left: 0; right: 0; height: 10px; }
.frame-left, .frame-right { top: 0; bottom: 0; width: 10px; }
.frame-top    { top: 0; }
.frame-bottom { bottom: 0; }
.frame-left   { left: 0; }
.frame-right  { right: 0; }

.node {
  position: absolute; box-sizing: border-box;
  border: 1.5px solid #7a5c3a; background: rgba(180,140,100,0.32);
  border-radius: 3px; cursor: grab; display: flex; flex-direction: column;
  align-items: center; justify-content: center; gap: 1px;
  user-select: none; transition: box-shadow 0.12s;
}
.node:active { cursor: grabbing; }
.node.floor { background: rgba(160,160,160,0.20); border: 1.5px dashed #999; z-index: 0; }
.node.selected { box-shadow: 0 0 0 2px #8B5E3C, 0 3px 12px rgba(0,0,0,0.2); z-index: 5; }
.node.locked { cursor: default; opacity: 0.85; }
.node-icon { font-size: 1rem; line-height: 1; pointer-events: none; }
.node-label {
  font-size: 0.62rem; font-weight: 700; color: #4a3620; pointer-events: none;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis; padding: 0 2px; max-width: 100%;
}
.node-lock {
  position: absolute; top: 2px; right: 2px; color: #6b4f30; pointer-events: none;
}

.node-btn {
  position: absolute; width: 18px; height: 18px; border-radius: 50%;
  border: none; color: #fff; font-size: 0.7rem; line-height: 1; cursor: pointer;
  display: flex; align-items: center; justify-content: center; padding: 0;
}
.node-btn.rotate { top: -22px; left: 50%; transform: translateX(-50%); background: #6b4f30; }
.node-btn.del { top: -22px; right: -6px; background: #c0392b; }
.handle {
  position: absolute; right: -6px; bottom: -6px; width: 13px; height: 13px;
  background: #8B5E3C; border: 2px solid #fff; border-radius: 3px;
  cursor: nwse-resize;
}

/* ── Properties panel ── */
.props-panel {
  width: 255px; flex-shrink: 0; background: #fff; border: 1px solid #e7dcc9;
  border-radius: 10px; padding: 0.75rem; display: flex; flex-direction: column; gap: 0.6rem;
}
.props-panel.props-empty {
  align-items: center; justify-content: center; text-align: center; gap: 0.4rem;
  color: #a08a6f; min-height: 180px;
}
.props-panel.props-empty p { font-size: 0.76rem; margin: 0; }
.props-header {
  display: flex; align-items: center; gap: 0.4rem; font-size: 0.85rem;
  font-weight: 700; color: #5c4630; padding-bottom: 0.4rem; border-bottom: 1px solid #f0e6d6;
}
.props-field { display: flex; flex-direction: column; gap: 0.25rem; font-size: 0.74rem; color: #6b5a45; }
.props-field input {
  border: 1px solid #e2d4bf; border-radius: 6px; padding: 0.35rem 0.5rem;
  font-size: 0.82rem; font-family: inherit; background: #fdfaf5;
}
.props-toggle {
  display: flex; align-items: center; justify-content: space-between;
  font-size: 0.78rem; color: #5c4630; font-weight: 600;
}
.switch-input { width: 36px; height: 20px; accent-color: #8B5E3C; cursor: pointer; }
</style>
