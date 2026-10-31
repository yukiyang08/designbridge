<script setup>
import { ref, computed, watch, onMounted, onBeforeUnmount } from 'vue'
import { Icon } from '@iconify/vue'
import RoomWalls from '@/components/RoomWalls.vue'
import RoomDims from '@/components/RoomDims.vue'
import { doorKeepouts as doorKeepoutsOf, settlePlacements } from '@/utils/roomGeometry'
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
  geometry: { type: Object, default: null },            // 這間房的牆厚／門／窗（CAD 路徑才有，見 utils/roomGeometry）
  // 家具 id → 正面朝向（up/down/left/right），由後端 facing.py 推算，生圖時家具也照這個方向擺
  facing: { type: Object, default: () => ({}) },
})

const FACING_TEXT = { up: '上', down: '下', left: '左', right: '右' }
const CW = { up: 'right', right: 'down', down: 'left', left: 'up' }
const SCREEN_TO_FRONT = { up: 'far', down: 'near', left: 'left', right: 'right' }
const FRONT_TO_SCREEN = { far: 'up', near: 'down', left: 'left', right: 'right' }
// 使用者轉過的以 front 為準（後端健檢回來前就要看得到），其餘用後端推算的朝向
// 桌几、盆栽、地毯等四面都一樣的家具不標正面
const NO_FRONT_TYPES = new Set([
  'coffee_table', 'side_table', 'dining_table', 'desk', 'plant', 'rug', 'carpet', 'lamp', 'bean_bag', 'drying_rack',
])
const canRotate = (item) => !!item && !NO_FRONT_TYPES.has(item.type)
const faceOf = (item) => canRotate(item)
  ? FRONT_TO_SCREEN[item.front] || props.facing?.[item.id] || '' : ''
const emit = defineEmits(['update:placements', 'room-size-changed', 'opening-change'])

// 公尺，點畫布外框可直接調整（雙向綁定回父層，3D 預覽/最終渲染跟著用同一組數字）
const roomW = defineModel('roomW', { default: 5 })
const roomD = defineModel('roomD', { default: 4 })

// 牆沿房間矩形（= 牆中心線）往內畫一半厚度（見 RoomWalls.vue）。家具必須在牆的「內緣」以內，
// 不然會跟牆疊在一起；沒有牆資料（非 CAD 路徑）就是整個 0~1。
const bounds = computed(() => {
  const t = props.geometry?.wallT
  if (!t) return { x0: 0, x1: 1, y0: 0, y1: 1 }
  return {
    x0: t.left / 2 / roomW.value, x1: 1 - t.right / 2 / roomW.value,
    y0: t.top / 2 / roomD.value, y1: 1 - t.bottom / 2 / roomD.value,
  }
})
// 把一件家具拉回牆的內緣以內（太大放不下就縮到剛好）；已經在範圍內就原樣回傳同一個物件
function inBounds(it) {
  const b = bounds.value
  const w = Math.min(it.w, b.x1 - b.x0), h = Math.min(it.h, b.y1 - b.y0)
  const x = clamp(it.x, b.x0, b.x1 - w), y = clamp(it.y, b.y0, b.y1 - h)
  return x === it.x && y === it.y && w === it.w && h === it.h ? it : { ...it, x, y, w, h }
}

const FLOOR_TYPES = new Set(['rug', 'carpet'])
const isFloor = (t) => FLOOR_TYPES.has(t)

// ── Collision：一般家具不可疊放，地毯/地墊類（FLOOR_TYPES）例外可疊 ──────
function rectsOverlap(a, b) {
  return a.x < b.x + b.w && a.x + a.w > b.x && a.y < b.y + b.h && a.y + a.h > b.y
}
// 門會碰到的範圍：家具不能放進去（見 utils/roomGeometry 的 doorKeepouts / settlePlacements）。
const doorKeepouts = computed(() => doorKeepoutsOf(props.geometry, roomW.value, roomD.value))
// 預設擺法、門被拖動、房間改尺寸、撤銷之後，只要有家具壓在範圍裡就自動推到最近的空位。
// 也一併把壓在牆裡的家具拉回牆的內緣（舊的快照、房間改尺寸、面板改大小都可能讓家具跑進牆裡）。
watch([doorKeepouts, () => props.placements, bounds], () => {
  const bounded = props.placements.map(inBounds)
  const fitted = bounded.some((it, i) => it !== props.placements[i]) ? bounded : props.placements
  const next = settlePlacements(fitted, doorKeepouts.value, bounds.value)
  if (next !== props.placements) emit('update:placements', next)
}, { immediate: true })
const editorNotice = ref('')
function collidesWithOthers(rect, excludeId) {
  if (doorKeepouts.value.some((k) => rectsOverlap(rect, k))) return true
  return items.value.some((it) => (
    it.id !== excludeId && rectsOverlap(rect, it)
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
  const b = bounds.value
  const next = items.value.map((it) => {
    if (it.id !== drag.id) return it
    if (drag.mode === 'move') {
      const x = clamp(drag.ox + dx, b.x0, b.x1 - it.w)
      const y = clamp(drag.oy + dy, b.y0, b.y1 - it.h)
      // 撞到別的家具（非地毯類）：卡在目前位置，不繼續往那個方向移動
      if (collidesWithOthers({ x, y, w: it.w, h: it.h }, it.id)) return it
      return { ...it, x, y }
    }
    // resize from bottom-right corner
    const w = clamp(drag.ow + dx, MIN, b.x1 - drag.ox)
    const h = clamp(drag.oh + dy, MIN, b.y1 - drag.oy)
    if (collidesWithOthers({ x: drag.ox, y: drag.oy, w, h }, it.id)) return it
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
      const b = bounds.value
      let x = ox, y = oy
      // 貼牆是貼到牆的內緣，不是房間矩形（牆中心線）的邊
      if (x < b.x0 + SNAP) x = b.x0
      if (x + w > b.x1 - SNAP) x = b.x1 - w
      if (y < b.y0 + SNAP) y = b.y0
      if (y + h > b.y1 - SNAP) y = b.y1 - h
      // 貼牆會撞到別的家具的話，維持原位不貼牆
      if ((x !== ox || y !== oy) && collidesWithOthers({ x, y, w, h }, it.id)) return it
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

// ── 門窗：點選、沿牆拖曳、改寬度 ───────────────────────────────────
const OP_PREFIX = 'op:'
const selectedOpening = computed(
  () => props.geometry?.openings.find((o) => OP_PREFIX + o.id === selectedId.value) || null,
)
const opLen = (o) => (o.side === 'top' || o.side === 'bottom' ? roomW.value : roomD.value)
const OP_MARGIN = 0.1   // 門窗離牆角至少 10cm
function clampFrac(o, frac, width = o.width) {
  const L = opLen(o), m = (width / 2 + OP_MARGIN) / L
  return m >= 0.5 ? 0.5 : clamp(frac, m, 1 - m)
}
let opDrag = null
function onOpeningDown(o, e) {
  selectedId.value = OP_PREFIX + o.id
  const horiz = o.side === 'top' || o.side === 'bottom'
  const el = boardRef.value
  opDrag = {
    id: o.id, startX: e.clientX, startY: e.clientY, frac0: o.frac, horiz,
    px: (horiz ? el.clientWidth : el.clientHeight) * zoom.value,   // 畫面上這條牆有多少 px（含縮放）
  }
  window.addEventListener('pointermove', onOpeningMove)
  window.addEventListener('pointerup', onOpeningUp)
}
function onOpeningMove(e) {
  if (!opDrag) return
  const o = props.geometry.openings.find((x) => x.id === opDrag.id)
  if (!o) return
  const delta = (opDrag.horiz ? e.clientX - opDrag.startX : e.clientY - opDrag.startY) / opDrag.px
  emit('opening-change', o.id, { frac: clampFrac(o, opDrag.frac0 + delta) })
}
function onOpeningUp() {
  opDrag = null
  window.removeEventListener('pointermove', onOpeningMove)
  window.removeEventListener('pointerup', onOpeningUp)
}
// 面板：寬度、離牆角距離（公分）
const opWidthCm = computed({
  get: () => (selectedOpening.value ? Math.round(selectedOpening.value.width * 100) : 0),
  set: (cm) => {
    const o = selectedOpening.value
    if (!o || !(cm >= 40)) return
    const width = Math.min(cm / 100, opLen(o) - 2 * OP_MARGIN)
    emit('opening-change', o.id, { width, frac: clampFrac(o, o.frac, width) })
  },
})
const opOffsetCm = computed({
  get: () => (selectedOpening.value ? Math.round((selectedOpening.value.frac * opLen(selectedOpening.value) - selectedOpening.value.width / 2) * 100) : 0),
  set: (cm) => {
    const o = selectedOpening.value
    if (!o || !Number.isFinite(cm)) return
    emit('opening-change', o.id, { frac: clampFrac(o, (cm / 100 + o.width / 2) / opLen(o)) })
  },
})
const OP_SIDE = { top: '上牆', bottom: '下牆', left: '左牆', right: '右牆' }

// ── Item ops ────────────────────────────────────────────────────
// 90° 增量旋轉只轉正面朝向 front（寫進去讓後端箭頭、生圖、3D 照使用者方向），長寬位置不動。
// 沒正面的家具（NO_FRONT_TYPES）不給轉。
function rotateNTimes90(item, times) {
  let rotation = item.rotation || 0
  let face = faceOf(item) || 'up'
  for (let i = 0; i < times; i++) {
    rotation = (rotation + 90) % 360
    face = CW[face]
  }
  return { ...item, rotation, front: SCREEN_TO_FRONT[face] }
}

function applyRotation(item, steps) {
  const rotated = rotateNTimes90(item, steps)
  editorNotice.value = ''
  pushHistory()
  commit(items.value.map((it) => (it.id === item.id ? rotated : it)))
}

function rotate90(item) {
  if (canRotate(item)) applyRotation(item, 1)
}

// 面板輸入任意角度：四捨五入到最近的 90° 倍數（理由同上）。
function setRotationDeg(item, deg) {
  if (!canRotate(item)) return
  const target = (((Math.round(deg / 90) * 90) % 360) + 360) % 360
  const current = item.rotation || 0
  if (target !== current) applyRotation(item, ((target - current) / 90 + 4) % 4)
}

function removeItem(item) {
  if (!item) return
  pushHistory()
  commit(items.value.filter((it) => it.id !== item.id))
  if (selectedId.value === item.id) selectedId.value = null
}

// 由中心向外找同時避開門和其他家具的位置，找不到空位就不新增，避免家具疊在一起。
function findFreeSpot(w, h) {
  const b = bounds.value
  const maxX = b.x1 - w, maxY = b.y1 - h
  if (maxX < b.x0 || maxY < b.y0) return null
  const cx = clamp(0.5 - w / 2, b.x0, maxX)
  const cy = clamp(0.5 - h / 2, b.y0, maxY)
  const step = 0.02
  let best = null, bestDistance = Infinity
  for (let x = b.x0; x <= maxX + 1e-9; x += step) {
    for (let y = b.y0; y <= maxY + 1e-9; y += step) {
      const candidate = { x: Math.min(x, maxX), y: Math.min(y, maxY), w, h }
      if (collidesWithOthers(candidate, null)) continue
      const distance = Math.hypot(candidate.x - cx, candidate.y - cy)
      if (distance < bestDistance) {
        bestDistance = distance
        best = { x: candidate.x, y: candidate.y }
      }
    }
  }
  return best
}

function addItem(type) {
  const [w, h] = furnitureDefaultSize(type, roomW.value, roomD.value)
  const id = `${type}_${Date.now().toString(36)}`
  const spot = findFreeSpot(w, h)
  if (!spot) {
    editorNotice.value = '房間沒有足夠的空位放置這件家具。'
    return
  }
  editorNotice.value = ''
  const { x, y } = spot
  const item = { id, type, w, h, x, y, rotation: 0, locked: false }
  pushHistory()
  commit([...items.value, item])
  selectedId.value = id
}

function updateSelectedField(key, value) {
  if (!selectedItem.value) return
  const item = selectedItem.value
  const updated = inBounds({ ...item, [key]: value })
  if ((key === 'w' || key === 'h') && collidesWithOthers(updated, item.id)) {
    editorNotice.value = '這個尺寸會和門或其他家具重疊，請調小尺寸或移動家具。'
    return
  }
  editorNotice.value = ''
  pushHistory()
  commit(items.value.map((it) => (it.id === item.id ? updated : it)))
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
// 上傳平面圖的未命名空間房型是 room，沒有對應家具清單，先給客廳清單，使用者可再切換
const paletteRoomType = ref(FURNITURE_BY_ROOM[props.roomType] ? props.roomType : 'living_room')
const paletteCatalog = computed(() => FURNITURE_BY_ROOM[paletteRoomType.value] || [])

// ── 尺寸標示模式 ─────────────────────────────────────────────────
// 開啟後：畫布外圍顯示總長與門窗尺寸鏈、每件家具標寬×深、選取家具時標出它到四面牆的距離。
const showDims = ref(false)
const cmOf = (frac, meters) => Math.round(frac * meters * 100)
const gaps = computed(() => {
  const it = selectedItem.value
  if (!showDims.value || !it) return []
  return [
    { k: 'l', cls: 'gap-h', style: { left: 0, top: pct(it.y + it.h / 2), width: pct(it.x) }, cm: cmOf(it.x, roomW.value) },
    { k: 'r', cls: 'gap-h', style: { left: pct(it.x + it.w), top: pct(it.y + it.h / 2), width: pct(1 - it.x - it.w) }, cm: cmOf(1 - it.x - it.w, roomW.value) },
    { k: 't', cls: 'gap-v', style: { top: 0, left: pct(it.x + it.w / 2), height: pct(it.y) }, cm: cmOf(it.y, roomD.value) },
    { k: 'b', cls: 'gap-v', style: { top: pct(it.y + it.h), left: pct(it.x + it.w / 2), height: pct(1 - it.y - it.h) }, cm: cmOf(1 - it.y - it.h, roomD.value) },
  ].filter(g => g.cm > 0)
})

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
const viewportRef = ref(null)
const viewportSize = ref({ width: 0, height: 0 })
const boardStageStyle = computed(() => {
  const { width, height } = viewportSize.value
  if (!width || !height) return { transform: `scale(${zoom.value})`, '--z': zoom.value }
  const padding = showDims.value ? 92 : 0
  const availableWidth = Math.max(0, width - padding)
  const availableHeight = Math.max(0, height - padding)
  const boardWidth = Math.min(availableWidth, availableHeight * boardAspect.value, 720)
  const boardHeight = boardWidth / boardAspect.value
  return {
    width: `${boardWidth + padding}px`,
    height: `${boardHeight + padding}px`,
    transform: `scale(${zoom.value})`,
    '--z': zoom.value,
  }
})
let viewportObserver
onMounted(() => {
  viewportObserver = new ResizeObserver(([entry]) => {
    viewportSize.value = {
      width: entry.contentRect.width,
      height: entry.contentRect.height,
    }
  })
  if (viewportRef.value) viewportObserver.observe(viewportRef.value)
})
onBeforeUnmount(() => viewportObserver?.disconnect())
</script>

<template>
  <div class="editor">
    <div class="toolbar">
      <button class="tool-btn active" @click="selectedId = null" title="取消選取">
        <Icon icon="mdi:cursor-default-outline" width="16" /><span>選取</span>
      </button>
      <span class="tool-sep" />
      <button v-if="canRotate(selectedItem)" class="tool-btn" @click="rotate90(selectedItem)" title="旋轉 90°">
        <Icon icon="mdi:rotate-right" width="16" /><span>旋轉</span>
      </button>
      <button class="tool-btn" @click="zoomIn" title="放大">
        <Icon icon="mdi:magnify-plus-outline" width="16" /><span>放大</span>
      </button>
      <button class="tool-btn" @click="zoomOut" title="縮小">
        <Icon icon="mdi:magnify-minus-outline" width="16" /><span>縮小</span>
      </button>
      <button class="tool-btn" :class="{ active: showDims }" :aria-pressed="showDims" @click="showDims = !showDims" title="顯示／隱藏尺寸標示">
        <Icon icon="mdi:ruler" width="16" /><span>尺寸</span>
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
      <div ref="viewportRef" class="board-viewport">
        <div class="board-stage" :class="{ dims: showDims }" :style="boardStageStyle">
        <RoomDims v-if="showDims" :room-w="roomW" :room-d="roomD" :geometry="geometry" />
        <div ref="boardRef" class="board" :class="{ 'has-walls': !!geometry }"
             :style="{ aspectRatio: boardAspect }"
             @pointerdown="selectedId = null">
          <div class="grid"></div>
          <RoomWalls
            v-if="geometry" :room-w="roomW" :room-d="roomD" :geometry="geometry"
            :selected-id="selectedOpening?.id || ''" @pick="onOpeningDown"
          />

          <!-- 點外框可選取「房間」，調整整體長寬（見下方家具設定面板的房間分支） -->
          <div class="frame-hit frame-top"    title="調整房間尺寸" @pointerdown.stop="selectRoom"></div>
          <div class="frame-hit frame-bottom" title="調整房間尺寸" @pointerdown.stop="selectRoom"></div>
          <div class="frame-hit frame-left"   title="調整房間尺寸" @pointerdown.stop="selectRoom"></div>
          <div class="frame-hit frame-right"  title="調整房間尺寸" @pointerdown.stop="selectRoom"></div>

          <div
            v-for="(k, i) in doorKeepouts" :key="`k${i}`" class="keepout"
            :style="{ left: pct(k.x), top: pct(k.y), width: pct(k.w), height: pct(k.h) }"
          ></div>

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
            <span v-if="showDims" class="node-size">{{ cmOf(item.w, roomW) }}×{{ cmOf(item.h, roomD) }}</span>
            <Icon v-if="item.locked" icon="mdi:lock-outline" class="node-lock" />
            <template v-if="faceOf(item)">
              <span class="node-front" :class="`to-${faceOf(item)}`"></span>
              <span
                class="node-facing" :class="`to-${faceOf(item)}`"
                :title="`正面朝${FACING_TEXT[faceOf(item)]}`"
              ><Icon icon="mdi:arrow-up-bold" width="13" /></span>
            </template>

            <template v-if="selectedId === item.id && !item.locked">
              <!-- 按鈕在家具外的右上角（貼上牆時改放下方，不然被畫布裁掉點不到）；旋轉每按一次轉 90° -->
              <div class="node-btns" :class="{ below: item.y < 0.08 }">
                <button v-if="canRotate(item)" class="node-btn rot" :title="`旋轉 90°（目前 ${item.rotation || 0}°）`"
                        @pointerdown.stop @click.stop="rotate90(item)">
                  <Icon icon="mdi:rotate-right" width="12" />
                </button>
                <button class="node-btn del" title="刪除"
                        @pointerdown.stop @click.stop="removeItem(item)">
                  <Icon icon="mdi:close" width="12" />
                </button>
              </div>
              <!-- 貼右牆／下牆時把手收進家具內，不然被畫布裁掉一半抓不到 -->
              <div class="handle"
                   :class="{ 'in-x': item.x + item.w > bounds.x1 - 0.02, 'in-y': item.y + item.h > bounds.y1 - 0.02 }"
                   @pointerdown="onDown($event, item, 'resize')"></div>
            </template>
          </div>

          <!-- 選取家具 → 到四面牆的距離 -->
          <div v-for="g in gaps" :key="g.k" class="gap" :class="g.cls" :style="g.style">
            <span class="gap-lab">{{ g.cm }}</span>
          </div>
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
        <label v-if="canRotate(selectedItem)" class="props-field">
          <span>旋轉角度 (°)</span>
          <select v-model.number="rotationDeg">
            <option v-for="d in [0, 90, 180, 270]" :key="d" :value="d">{{ d }}°</option>
          </select>
        </label>
        <label class="props-toggle">
          <span>鎖定位置</span>
          <input type="checkbox" v-model="lockedModel" class="switch-input" />
        </label>
      </aside>
      <aside class="props-panel" v-else-if="selectedOpening">
        <div class="props-header">
          <Icon :icon="selectedOpening.type === 'door' ? 'mdi:door' : 'mdi:window-closed-variant'" width="20" />
          <span>{{ selectedOpening.type === 'door' ? (selectedOpening.entry ? '大門' : '門') : '窗' }}（{{ OP_SIDE[selectedOpening.side] }}）</span>
        </div>
        <label class="props-field">
          <span>寬度 (cm)</span>
          <input type="number" v-model.number="opWidthCm" min="40" />
        </label>
        <label class="props-field">
          <span>{{ selectedOpening.side === 'top' || selectedOpening.side === 'bottom' ? '離左側牆角 (cm)' : '離上側牆角 (cm)' }}</span>
          <input type="number" v-model.number="opOffsetCm" min="0" />
        </label>
        <p class="props-note">也可以直接在畫布上沿牆拖動</p>
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

    <span v-if="editorNotice" class="hint hint-notice" role="status">{{ editorNotice }}</span>
    <span v-else class="hint">拖動移動 · 右下角縮放 · ⟳ 旋轉 · 靠牆自動吸附 · 點選外框可調整房間尺寸 · 「尺寸」可顯示標註 · 橘色箭頭＝家具正面朝向</span>
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
.tool-btn.active { background: #756d66; color: #fff; }
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
  color: #756d66; font-size: 0.8rem;
}
.palette-hint { font-size: 0.68rem; color: #a08a6f; margin: 0; text-align: center; }

.board-viewport {
  flex: 1 1 420px; min-width: 0; height: min(70vh, 720px); overflow: auto;
  display: flex; align-items: center; justify-content: center;
}
.board-stage {
  position: relative;
  display: flex; align-items: center; justify-content: center;
  box-sizing: border-box;
  transform-origin: top center; flex-shrink: 0;
}
.board-stage.dims {
  padding: 46px;
}
.board {
  position: relative; width: 100%; height: 100%;
  aspect-ratio: var(--room-aspect);
  background: #fbf6ee;
  border: 3px solid #2b2b2b; border-radius: 4px; overflow: hidden;
  box-shadow: 0 4px 24px rgba(0,0,0,0.12); touch-action: none;
}
.board.has-walls { border: 0; border-radius: 0; }   /* 有真實牆體就不用外框當牆 */
.grid {
  position: absolute; inset: 0;
  background-image:
    linear-gradient(to right, rgba(120,90,60,0.08) 1px, transparent 1px),
    linear-gradient(to bottom, rgba(120,90,60,0.08) 1px, transparent 1px);
  background-size: 20% 20%;
}

/* 尺寸標示模式：家具尺寸與到牆距離 */
.node-size {
  position: absolute; left: 50%; bottom: 2px; transform: translateX(-50%);
  font-size: 10px; line-height: 1; padding: 1px 3px; border-radius: 2px;
  background: rgba(255,255,255,0.85); color: #5a4a36; white-space: nowrap; pointer-events: none;
}
.keepout {
  position: absolute; pointer-events: none;
  background: rgba(224, 138, 30, 0.10); border: 1px dashed rgba(224, 138, 30, 0.55);
}
.props-note { margin: 0; font-size: 0.74rem; color: #a08a6f; }
.gap { position: absolute; pointer-events: none; }
.gap-h { height: 0; border-top: 1px dashed #c0392b; }
.gap-v { width: 0; border-left: 1px dashed #c0392b; }
.gap-lab {
  position: absolute; left: 50%; top: 50%; transform: translate(-50%, -50%);
  padding: 0 3px; font-size: 10px; line-height: 1.3; border-radius: 2px;
  background: #fff; color: #c0392b; white-space: nowrap;
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
  border: 1.5px solid #7a5c3a; background: rgba(163, 155, 148,0.32);
  border-radius: 3px; cursor: grab; display: flex; flex-direction: column;
  align-items: center; justify-content: center; gap: 1px;
  user-select: none; transition: box-shadow 0.12s;
}
.node:active { cursor: grabbing; }
.node.floor { background: rgba(160,160,160,0.20); border: 1.5px dashed #999; z-index: 0; }
.node.selected { box-shadow: 0 0 0 2px #756d66, 0 3px 12px rgba(0,0,0,0.2); z-index: 5; }
.node.locked { cursor: default; opacity: 0.85; }
.node-icon { font-size: 1rem; line-height: 1; pointer-events: none; }
.node-label {
  font-size: 0.62rem; font-weight: 700; color: #4a3620; pointer-events: none;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis; padding: 0 2px; max-width: 100%;
}
.node-lock {
  position: absolute; top: 2px; right: 2px; color: #6b4f30; pointer-events: none;
}
/* 朝向：正面那條邊加粗上色，邊的中間再放一個跨在邊上的箭頭徽章 */
.node-front { position: absolute; background: #c8641e; pointer-events: none; }
.node-front.to-up    { top: -1.5px; left: -1.5px; right: -1.5px; height: 4px; border-radius: 3px 3px 0 0; }
.node-front.to-down  { bottom: -1.5px; left: -1.5px; right: -1.5px; height: 4px; border-radius: 0 0 3px 3px; }
.node-front.to-left  { left: -1.5px; top: -1.5px; bottom: -1.5px; width: 4px; border-radius: 3px 0 0 3px; }
.node-front.to-right { right: -1.5px; top: -1.5px; bottom: -1.5px; width: 4px; border-radius: 0 3px 3px 0; }
.node-facing {
  position: absolute; z-index: 2; width: 18px; height: 18px; border-radius: 50%;
  background: #c8641e; color: #fff; border: 1.5px solid #fff; box-shadow: 0 1px 3px rgba(0,0,0,0.25);
  display: flex; align-items: center; justify-content: center; cursor: help;
}
.node-facing.to-up    { top: 0; left: 50%; transform: translate(-50%, -50%); }
.node-facing.to-down  { bottom: 0; left: 50%; transform: translate(-50%, 50%) rotate(180deg); }
.node-facing.to-left  { left: 0; top: 50%; transform: translate(-50%, -50%) rotate(-90deg); }
.node-facing.to-right { right: 0; top: 50%; transform: translate(50%, -50%) rotate(90deg); }

/* 按鈕列與縮放把手疊在朝向箭頭（z 2）之上，箭頭頂多被蓋一角，按鈕永遠點得到 */
.node-btns {
  position: absolute; bottom: 100%; right: 0; margin-bottom: 12px;
  display: flex; gap: 4px; z-index: 3;
}
.node-btns.below { bottom: auto; top: 100%; margin: 12px 0 0; right: auto; left: 0; }
.node-btn {
  width: 20px; height: 20px; border-radius: 50%;
  border: 1.5px solid #fff; color: #fff; line-height: 1; cursor: pointer;
  display: flex; align-items: center; justify-content: center; padding: 0;
  box-shadow: 0 1px 3px rgba(0,0,0,0.25);
}
.node-btn.rot { background: #6b4f30; }
.node-btn.del { background: #c0392b; }
.handle {
  position: absolute; right: -6px; bottom: -6px; width: 13px; height: 13px; z-index: 3;
  background: #756d66; border: 2px solid #fff; border-radius: 3px;
  cursor: nwse-resize;
}
.handle.in-x { right: 1px; }
.handle.in-y { bottom: 1px; }

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
.props-field input, .props-field select {
  border: 1px solid #e2d4bf; border-radius: 6px; padding: 0.35rem 0.5rem;
  font-size: 0.82rem; font-family: inherit; background: #fdfaf5;
}
.props-toggle {
  display: flex; align-items: center; justify-content: space-between;
  font-size: 0.78rem; color: #5c4630; font-weight: 600;
}
.hint-notice { color: #a33b2b; font-weight: 600; }

@media (max-width: 900px) {
  .board-viewport { flex-basis: 100%; order: 2; height: min(70vh, 640px); }
  .props-panel { order: 3; }
  .palette { order: 1; }
}
.switch-input { width: 36px; height: 20px; accent-color: #756d66; cursor: pointer; }

/* 手機：畫布優先，工具列與家具面板收成單行橫向捲動，不再把畫布擠到畫面下方 */
@media (max-width: 640px) {
  .toolbar { flex-wrap: nowrap; overflow-x: auto; }
  .tool-btn { flex: none; }
  .board-viewport { order: 1; height: min(60vh, 480px); }
  .palette { order: 2; width: 100%; box-sizing: border-box; }
  .props-panel { order: 3; }
  .palette-list { display: flex; overflow-x: auto; max-height: none; padding-bottom: 0.2rem; }
  .palette-item { flex: none; min-width: 72px; }
  .palette-hint { display: none; }
}
</style>
