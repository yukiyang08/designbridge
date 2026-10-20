<script setup>
/**
 * CAD 多房間逐一設計：右上角常駐縮圖。
 *
 * 顯示整層樓分區圖（沿用 cadPlanResult.svg_markup），用顏色標示每間房的狀態：
 *  · 目前正在設計的房間 → accent 色
 *  · 已經渲染完成的房間 → accent-deep 色（較深）
 *  · 還沒開始的房間 → 預設底色
 * 只有目前這間房已經渲染完成（activeRoomId 對應的狀態是 'done'）才能點縮圖上
 * 其他房間切過去——這是使用者明確要的行為，避免設計到一半跳房弄亂進度。
 *
 * 整層套用：目前這間渲染完 → 「用這個風格做其他房間」就地展開確認卡（預設全選，
 * 點標籤或點平面圖上的房間可以排除）→ 開始後同一張卡變成「接片」，每間一格，
 * 依序從等待、生成中到縮圖浮現；失敗的格子直接顯示原因與重試。
 */
import { ref, computed, watch, nextTick, onBeforeUnmount, onMounted } from 'vue'
import { CONCURRENCY } from '@/composables/design-flow/cadBatch'
import FengshuiPicker from '@/components/FengshuiPicker.vue'
import { CAD_ROOM_TYPE_TO_EDITOR, FENGSHUI_OPTIONS } from '@/composables/design-flow/state'

const props = defineProps({
  plan:             { type: Object, required: true },   // cadPlanResult：{ rooms, svg_markup, ... }
  roomStatus:       { type: Object, default: () => ({}) }, // { [roomId]: 'active' | 'done' }
  activeRoomId:     { type: String, default: null },
  activePlacements: { type: Array, default: () => [] },    // 目前這間房的 editPlacements，即時反映在縮圖上
  batch:            { type: Object, default: () => ({}) }, // { [roomId]: { status: 'queued'|'running'|'failed', error } }
  batchRunning:     { type: Boolean, default: false },
  rendering:        { type: Object, default: () => ({}) }, // { [roomId]: true } 正在渲染的房間（含使用者自己按「生成」的那間）
  thumbs:           { type: Object, default: () => ({}) }, // { [roomId]: 渲染完成的縮圖 url }
  settingLabels:    { type: Array, default: () => [] },    // 「沿用」哪些設定，例如 ['風格：現代', '比例：16:9']
  fengshuiRules:    { type: Array, default: () => [] },
  compact:          { type: Boolean, default: false },     // 頂部細列：隱藏平面圖，只留進度與「放大平面圖」
  overviewActive:   { type: Boolean, default: false },     // 目前在看整層總覽（頂部列的「總覽」分頁反白）
})
const emit = defineEmits(['select-room', 'abandon', 'apply', 'cancel', 'overview', 'update:fengshuiRules'])

const boardRef = ref(null)
const modalBoardRef = ref(null)
const expanded = ref(false)      // 放大平面圖（只看／切房，選房間在確認卡裡做）
const stage = ref('idle')        // 'idle' | 'confirm'
const skipped = ref(new Set())   // 確認卡裡被排除的房間
const runIds = ref([])           // 這一輪套用的房間，用來畫「接片」
const confirmingAbandon = ref(false)   // 兩段式確認，避免誤點就清掉一間房的進度
function onAbandon() {
  if (!confirmingAbandon.value) { confirmingAbandon.value = true; return }
  confirmingAbandon.value = false
  closeModal()
  emit('abandon')
}
let cleanupFns = []

const totalCount = computed(() => props.plan?.rooms?.length || 0)
const doneCount = computed(() => Object.values(props.roomStatus).filter(s => s === 'done').length)
const activeIsDone = computed(() => !props.activeRoomId || props.roomStatus[props.activeRoomId] === 'done')

const roomsList = computed(() => props.plan?.rooms || [])
const roomById = (id) => roomsList.value.find(r => r.id === id)
const batchStatus = (id) => props.batch[id]?.status
// 批次佔用的房間不能進去編輯；使用者自己送出渲染的房間可以進去看進度，所以不算 busy
const isBusy = (id) => ['queued', 'running'].includes(batchStatus(id))
// 畫面上顯示用的狀態：批次狀態，或使用者自己正在渲染（顯示成「生成中」）
const shownStatus = (id) => batchStatus(id) || (props.rendering[id] ? 'running' : undefined)
const selecting = computed(() => stage.value === 'confirm')

// 房間標籤的狀態樣式與附註（批次中的房間不能進去，由 disabled 擋掉）
const tabClass = (r) => ({
  active: r.id === props.activeRoomId && !props.overviewActive,
  done: props.roomStatus[r.id] === 'done',
  wip: r.id !== props.activeRoomId && props.roomStatus[r.id] === 'active',
  busy: ['queued', 'running'].includes(shownStatus(r.id)),
  failed: shownStatus(r.id) === 'failed',
})
const tabNote = (r) => ({ queued: '等待中', running: '生成中', failed: '失敗' }[shownStatus(r.id)] || '')

// 還沒做、也沒在批次裡的房間：才有可能被套用
// 設計到一半的房間（roomStatus 有值但還沒 done）不算：批次用的是預設家具擺法，會把使用者的編輯蓋掉
const candidates = computed(() => roomsList.value.filter(
  r => r.id !== props.activeRoomId && !props.roomStatus[r.id] && !batchStatus(r.id),
))
const targets = computed(() => candidates.value.filter(r => !skipped.value.has(r.id)))
const candidateRoomTypes = computed(() => [...new Set(candidates.value.map(
  r => CAD_ROOM_TYPE_TO_EDITOR[r.room_type] || 'living_room',
))])
const selectedFengshuiCount = computed(() =>
  FENGSHUI_OPTIONS.filter(o => props.fengshuiRules.includes(o.value)).length,
)
const batchFengshuiRules = computed({
  get: () => props.fengshuiRules,
  set: value => emit('update:fengshuiRules', value),
})
// 每張約 30–60 秒，同時 CONCURRENCY 張
const estimate = computed(() => {
  const rounds = Math.ceil(targets.value.length / CONCURRENCY)
  const lo = Math.max(1, Math.ceil(rounds / 2))
  return lo >= rounds ? `${lo} 分鐘` : `${lo}–${rounds} 分鐘`
})
// 浴室、陽台的預設家具擺法是固定位置，不看門窗與水管，生出來可能不準
const hasLooseRooms = computed(() => candidates.value.some(r => ['bathroom', 'balcony'].includes(r.room_type)))

// ── 接片：這一輪每間房一格 ──
const frames = computed(() => {
  const ids = runIds.value.length ? runIds.value : Object.keys(props.batch)   // 元件重掛載時 runIds 會是空的
  return ids.map(roomById).filter(Boolean)
})
function frameState(r) {
  if (props.roomStatus[r.id] === 'done') return 'done'
  return batchStatus(r.id) || 'stopped'   // queued | running | failed | 已停止（取消後 batch 被清空）
}
const frameDone = computed(() => frames.value.filter(r => frameState(r) === 'done').length)
const frameFailed = computed(() => frames.value.filter(r => frameState(r) === 'failed').length)
const runFinished = computed(() => frames.value.length > 0 && !props.batchRunning)
const runTitle = computed(() => {
  if (props.batchRunning) return `生成中　${frameDone.value} / ${frames.value.length}`
  if (frameDone.value === frames.value.length) return '全部完成'
  return `完成 ${frameDone.value} / ${frames.value.length}`
})
const STATE_TEXT = { queued: '等待中', running: '生成中', stopped: '已停止' }

const allOn = computed(() => candidates.value.length > 0 && targets.value.length === candidates.value.length)
// 只想做其中幾間：先「全部取消」再點要做的，比一間間排除快
function toggleAll() {
  skipped.value = allOn.value ? new Set(candidates.value.map(r => r.id)) : new Set()
}
function openConfirm() {
  runIds.value = []
  skipped.value = new Set()   // 預設全部都做
  stage.value = 'confirm'
}
function cancelConfirm() { stage.value = 'idle' }
function startApply() {
  const ids = targets.value.map(r => r.id)
  if (!ids.length) return
  runIds.value = ids
  stage.value = 'idle'
  emit('apply', ids)
}
function retry(id) {
  if (!runIds.value.includes(id)) runIds.value = [...runIds.value, id]
  emit('apply', [id])
}
function retryFailed() {
  const ids = frames.value.filter(r => frameState(r) === 'failed').map(r => r.id)
  if (!ids.length) return
  runIds.value = [...new Set([...runIds.value, ...ids])]
  emit('apply', ids)
}
function stopRun() { emit('cancel') }
function dismissRun() { runIds.value = [] }
function closeModal() { expanded.value = false }
function toggleSkip(id) {
  const next = new Set(skipped.value)
  next.has(id) ? next.delete(id) : next.add(id)
  skipped.value = next
}

function clearHandlers() {
  cleanupFns.forEach(fn => fn())
  cleanupFns = []
}

// 縮圖與彈出的大卡片是同一份 svg_markup，各自一個容器，都要上色 / 掛點擊
const boards = () => [boardRef.value, modalBoardRef.value].filter(Boolean)

// 縮圖不顯示尺寸線後，原本留給它們的邊距就成了空白：把縮圖的視窗裁到房間本身（外加一圈牆與門的弧線）。
// 放大的大卡片維持完整的 viewBox，尺寸細節都還在。
function fitSmallBoard(board) {
  const svg = board.querySelector('svg')
  const floors = svg ? [...svg.querySelectorAll('.room-floor')] : []
  if (!floors.length) return
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity
  for (const f of floors) {
    const x = parseFloat(f.getAttribute('x')), y = parseFloat(f.getAttribute('y'))
    const w = parseFloat(f.getAttribute('width')), h = parseFloat(f.getAttribute('height'))
    if (![x, y, w, h].every(Number.isFinite)) return
    x0 = Math.min(x0, x); y0 = Math.min(y0, y); x1 = Math.max(x1, x + w); y1 = Math.max(y1, y + h)
  }
  const pad = 26   // 外牆約 10px、大門的開門弧線會畫到牆外
  svg.setAttribute('viewBox', `${x0 - pad} ${y0 - pad} ${x1 - x0 + pad * 2} ${y1 - y0 + pad * 2}`)
}

function paint() {
  clearHandlers()
  if (boardRef.value) fitSmallBoard(boardRef.value)
  boards().forEach(paintBoard)
  paintLiveFurniture()
}

function paintBoard(board) {
  const svg = board.querySelector('svg')
  if (!svg) return
  const applying = selecting.value
  svg.querySelectorAll('.room-rect').forEach((g) => {
    const roomId = g.getAttribute('data-room-id')
    const room = roomById(roomId)
    const isActive = roomId === props.activeRoomId
    const isDone = props.roomStatus[roomId] === 'done'
    const st = shownStatus(roomId)
    const busy = isBusy(roomId)
    const pickable = applying && !isActive && !isDone && !st
    const isSkipped = pickable && skipped.value.has(roomId)
    const isTarget = pickable && !isSkipped

    g.classList.toggle('is-active', isActive)
    g.classList.toggle('is-wip', !isActive && props.roomStatus[roomId] === 'active')   // 切走時還沒完成的房間
    g.classList.toggle('is-done', isDone)
    g.classList.toggle('is-queued', st === 'queued')
    g.classList.toggle('is-running', st === 'running')
    g.classList.toggle('is-failed', st === 'failed')
    g.classList.toggle('is-target', isTarget)
    g.classList.toggle('is-skipped', isSkipped)

    setSelectMark(g, room, isTarget ? 'on' : isSkipped ? 'off' : null)

    // 確認卡打開時：點平面圖上的房間 = 切換「要不要做」；平常：點了切過去編輯
    let action = null
    if (applying) {
      if (pickable && room) action = () => toggleSkip(roomId)
    } else if (room && !isActive && !busy) {
      action = () => { closeModal(); emit('select-room', room) }
    }
    const locked = !applying && !isActive && busy   // 只有被批次佔用的房間不能進去；其他隨時可以切
    g.classList.toggle('is-clickable', !!action)
    g.classList.toggle('is-locked', locked)

    // 游標移上去的補充說明（重要資訊都另外寫在卡片文字裡，不能只靠這個，手機沒有 hover）
    const tipText = st === 'queued' ? '等待生成'
      : st === 'running' ? '生成中…'
      : st === 'failed' ? `生成失敗：${props.batch[roomId].error || ''}`
      : isSkipped ? '已排除，點一下加回'
      : isTarget ? '會套用目前風格，點一下排除'
      : locked ? '批次生成中，完成後再進入編輯'
      : ''
    g.querySelector(':scope > title.room-tip')?.remove()
    if (tipText) {
      const tip = document.createElementNS('http://www.w3.org/2000/svg', 'title')
      tip.setAttribute('class', 'room-tip')
      tip.textContent = tipText
      g.prepend(tip)
    }

    if (action) {
      g.addEventListener('click', action)
      cleanupFns.push(() => g.removeEventListener('click', action))
    }
    // 選房間是在平面圖上做的，沒有另外的清單，所以房間要能用鍵盤（Tab、Enter／空白鍵）操作
    const keyboard = applying && pickable && room
    if (keyboard) {
      g.setAttribute('tabindex', '0')
      g.setAttribute('role', 'button')
      g.setAttribute('aria-pressed', String(isTarget))
      g.setAttribute('aria-label', `${room.label_zh}：${isTarget ? '會生成' : '已排除'}，按 Enter 切換`)
      const onKeydown = (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggleSkip(roomId) } }
      g.addEventListener('keydown', onKeydown)
      cleanupFns.push(() => g.removeEventListener('keydown', onKeydown))
    } else {
      for (const k of ['tabindex', 'role', 'aria-pressed', 'aria-label']) g.removeAttribute(k)
    }
  })
}

// 確認卡打開時，在每間「候選」房間的左上角畫一個 ✓（會生成）／✕（已排除）。
// 光靠描邊顏色的差別太細，也沒辦法給色盲或讀屏的人看。
function setSelectMark(g, room, state) {
  g.querySelector(':scope > .sel-mark')?.remove()
  if (!state || !room) return
  const floor = g.querySelector('.room-floor')
  const x = parseFloat(floor?.getAttribute('x')), y = parseFloat(floor?.getAttribute('y'))
  if (!Number.isFinite(x) || !Number.isFinite(y)) return
  const mark = document.createElementNS(SVG_NS, 'g')
  mark.setAttribute('class', `sel-mark is-${state}`)
  mark.setAttribute('pointer-events', 'none')
  const cx = x + 24, cy = y + 24
  const circle = document.createElementNS(SVG_NS, 'circle')
  circle.setAttribute('cx', cx); circle.setAttribute('cy', cy); circle.setAttribute('r', 16)
  const glyph = document.createElementNS(SVG_NS, 'text')
  glyph.setAttribute('x', cx); glyph.setAttribute('y', cy)
  glyph.setAttribute('text-anchor', 'middle'); glyph.setAttribute('dominant-baseline', 'central')
  glyph.setAttribute('font-size', 20); glyph.setAttribute('font-weight', 700)
  glyph.textContent = state === 'on' ? '✓' : '✕'
  mark.append(circle, glyph)
  g.append(mark)
}

// 把目前這間房的預設家具（靜態 SVG 裡的 .room-furniture）換成使用者實際編輯的
// editPlacements，選了哪些家具、擺在哪就照樣畫在縮圖上——不用等後端重繪整層 SVG，
// LayoutEditor 一有變動這裡就同步更新。只用純色 rect（不是完整的家具符號），
// 縮圖這麼小，細節符號看不出差異，沒必要在前端重做一份 Python 那邊的家具繪製邏輯。
const SVG_NS = 'http://www.w3.org/2000/svg'

function paintLiveFurniture() {
  if (props.activeRoomId) boards().forEach(paintFurnitureOn)
}

function paintFurnitureOn(board) {
  const svg = board.querySelector('svg')
  if (!svg) return
  const g = [...svg.querySelectorAll('.room-rect')].find(
    (el) => el.getAttribute('data-room-id') === props.activeRoomId,
  )
  const floor = g?.querySelector('.room-floor')
  if (!g || !floor) return

  const fx = parseFloat(floor.getAttribute('x'))
  const fy = parseFloat(floor.getAttribute('y'))
  const fw = parseFloat(floor.getAttribute('width'))
  const fh = parseFloat(floor.getAttribute('height'))
  if (!Number.isFinite(fx) || !Number.isFinite(fw)) return

  g.querySelector('.room-furniture')?.remove()

  const group = document.createElementNS(SVG_NS, 'g')
  group.setAttribute('class', 'room-furniture')
  for (const p of props.activePlacements) {
    const x = fx + (p.x || 0) * fw
    const y = fy + (p.y || 0) * fh
    const w = Math.max(1, (p.w || 0) * fw)
    const h = Math.max(1, (p.h || 0) * fh)
    const rect = document.createElementNS(SVG_NS, 'rect')
    rect.setAttribute('x', x.toFixed(1))
    rect.setAttribute('y', y.toFixed(1))
    rect.setAttribute('width', w.toFixed(1))
    rect.setAttribute('height', h.toFixed(1))
    rect.setAttribute('rx', '1')
    rect.setAttribute('fill', 'white')
    rect.setAttribute('stroke', '#2a2a2a')
    rect.setAttribute('stroke-width', '0.8')
    if (p.rotation) {
      const cx = x + w / 2, cy = y + h / 2
      rect.setAttribute('transform', `rotate(${p.rotation} ${cx.toFixed(1)} ${cy.toFixed(1)})`)
    }
    group.appendChild(rect)
  }
  floor.insertAdjacentElement('afterend', group)
}

watch(
  () => [props.plan?.svg_markup, props.roomStatus, props.activeRoomId, expanded.value, stage.value, skipped.value, props.batch],
  () => nextTick(paint),
  { immediate: true, deep: true },
)
// 家具本身變動（拖曳/加/刪）不需要整個 paint() 重跑（那會重掛點擊事件），
// 只要重畫這間房的家具就好。
watch(() => props.activePlacements, () => nextTick(paintLiveFurniture), { deep: true })
// 目前這間房又被改動（不再是「已完成」）時，確認卡就不成立了
watch(activeIsDone, (ok) => { if (!ok) cancelConfirm() })
onBeforeUnmount(clearHandlers)
function onKey(e) {
  if (e.key !== 'Escape') return
  closeModal()
  if (props.compact && selecting.value) cancelConfirm()   // 結果頁的選房間浮動視窗
}
onMounted(() => window.addEventListener('keydown', onKey))
onBeforeUnmount(() => window.removeEventListener('keydown', onKey))
</script>

<template>
  <div class="cad-minimap" :class="{ 'is-compact': compact && !selecting, 'is-compact-open': compact && selecting }">
      <div class="minimap-head">
        <span class="minimap-title">{{ compact && selecting ? '套用到其他房間' : '整層進度' }}</span>
        <span v-if="compact && selecting" class="minimap-count">已選 {{ targets.length }} / {{ candidates.length }} 間</span>
        <span v-else class="minimap-count">{{ doneCount }} / {{ totalCount }} 間完成</span>
        <button
          v-if="compact && selecting"
          type="button" class="minimap-close" aria-label="關閉" @click="cancelConfirm"
        >✕</button>
      </div>
      <div ref="boardRef" class="minimap-board" v-html="plan?.svg_markup || ''"></div>
      <!-- 結果頁頂部：房間標籤列取代「整層進度 N/M」。✓ 已完成、深色 = 目前這間，點標籤直接切房 -->
      <ul v-if="compact && !selecting" class="room-tabs" aria-label="房間">
        <li>
          <button
            type="button" class="room-tab room-tab--overview" :class="{ active: overviewActive, done: !overviewActive }"
            :aria-current="overviewActive ? 'true' : null" @click="emit('overview')"
          >總覽</button>
        </li>
        <li v-for="r in roomsList" :key="r.id">
          <button
            type="button" class="room-tab" :class="tabClass(r)"
            :disabled="isBusy(r.id)" :aria-current="r.id === activeRoomId && !overviewActive ? 'true' : null"
            @click="(r.id !== activeRoomId || overviewActive) && emit('select-room', r)"
          >
            {{ r.label_zh }}
            <small v-if="tabNote(r)" class="tab-note">{{ tabNote(r) }}</small>
          </button>
        </li>
      </ul>
      <button type="button" class="minimap-expand" @click="expanded = true">{{ compact ? '查看平面圖' : '檢視平面圖' }}</button>

      <!-- ① 一般狀態：目前這間做完、還有房間沒做 -->
      <button
        v-if="activeIsDone && candidates.length && stage === 'idle' && !frames.length"
        type="button" class="minimap-apply" @click="openConfirm"
      >
        <span>{{ compact ? `套用風格到其他 ${candidates.length} 間` : '將此風格套用到其他房間' }}</span>
        <small>還有 {{ candidates.length }} 間沒做，可以自己挑要做哪幾間</small>
      </button>

      <!-- ② 確認卡：就地展開，不開視窗。預設全選，大多數人直接按「開始生成」就好 -->
      <section v-if="selecting" class="apply-card" aria-label="套用到其他房間">
        <template v-if="compact">
          <!-- 浮動視窗：標題在視窗頂部，這裡只放設定標籤與房間勾選清單（和平面圖同步） -->
          <div v-if="settingLabels.length" class="card-label-row">
            <p class="card-label">沿用設定</p>
          </div>
          <ul v-if="settingLabels.length" class="chips">
            <li v-for="s in settingLabels" :key="s">{{ s }}</li>
          </ul>
        </template>
        <template v-else>
          <h3 class="card-title">套用到其他房間</h3>
          <p v-if="settingLabels.length" class="card-sub">沿用　{{ settingLabels.join(' · ') }}</p>
        </template>
        <div class="card-label-row">
          <p class="card-label">{{ compact ? '點左邊平面圖的房間，可排除不要生成的' : '點上面的平面圖，選要生成的房間' }}</p>
          <button type="button" class="link-btn" @click="toggleAll">{{ allOn ? '全部取消' : '全選' }}</button>
        </div>
        <details class="batch-fengshui">
          <summary>
            風水禁忌
            <span class="batch-fengshui-count">{{ selectedFengshuiCount ? `已選 ${selectedFengshuiCount} 條` : '未限制' }}</span>
          </summary>
          <FengshuiPicker
            v-model="batchFengshuiRules"
            :room-types="candidateRoomTypes"
            hint="只套用到符合房型的房間；未勾選就不會限制排版。"
          />
        </details>
        <button type="button" class="apply-go" :disabled="!targets.length" @click="startApply">
          開始生成 {{ targets.length }} 間
        </button>
        <p class="card-foot">
          <span v-if="targets.length">預估約 {{ estimate }}</span>
          <span v-else>請至少留一間</span>
          <button v-if="!compact" type="button" class="link-btn" @click="cancelConfirm">取消</button>
        </p>
      </section>

      <!-- ③-a 結果頁頂部：房間標籤本身就是進度（各自標註生成中／等待中／失敗），這裡只留一行總狀態 -->
      <div v-if="compact && frames.length && !selecting" class="batch-status" role="status" aria-live="polite">
        <span class="batch-text">{{ runTitle }}</span>
        <span v-if="batchRunning" class="batch-bar" aria-hidden="true">
          <i :style="{ width: `${(frameDone / frames.length) * 100}%` }"></i>
        </span>
        <button v-if="batchRunning" type="button" class="link-btn" @click="stopRun">停止等待</button>
        <template v-else>
          <button v-if="frameFailed" type="button" class="link-btn" @click="retryFailed">重試失敗的 {{ frameFailed }} 間</button>
          <button type="button" class="link-btn" @click="dismissRun">關閉</button>
        </template>
      </div>

      <!-- ③ 接片：每間房一格，依序從等待、生成中到縮圖浮現 -->
      <section v-if="frames.length && !selecting && !compact" class="apply-card" aria-label="套用進度">
        <div class="card-headline">
          <h3 class="card-title" role="status" aria-live="polite">{{ runTitle }}</h3>
          <button v-if="batchRunning" type="button" class="link-btn" @click="stopRun">停止等待</button>
          <button v-else-if="runFinished" type="button" class="link-btn" @click="dismissRun">關閉</button>
        </div>
        <ul class="frames">
          <li v-for="r in frames" :key="r.id" class="frame" :class="`is-${frameState(r)}`">
            <button
              v-if="frameState(r) === 'done'" type="button" class="frame-face frame-btn"
              :aria-label="`查看${r.label_zh}的生成結果`" @click="emit('select-room', r)"
            >
              <img v-if="thumbs[r.id]" :src="thumbs[r.id]" :alt="`${r.label_zh}的渲染圖`" class="frame-img" />
              <span class="frame-name">{{ r.label_zh }}</span>
              <span class="frame-badge" aria-hidden="true">✓</span>
            </button>
            <div v-else class="frame-face">
              <span class="frame-name">{{ r.label_zh }}</span>
              <span v-if="frameState(r) !== 'failed'" class="frame-state">{{ STATE_TEXT[frameState(r)] }}</span>
              <template v-else>
                <span class="frame-state frame-state--fail">失敗</span>
                <span v-if="batch[r.id]?.error" class="frame-error" :title="batch[r.id].error">{{ batch[r.id].error }}</span>
                <button
                  type="button" class="frame-retry" :disabled="batchRunning"
                  :title="batchRunning ? '其他房間生成完才能重試' : ''" @click="retry(r.id)"
                >重試</button>
              </template>
            </div>
          </li>
        </ul>
        <p v-if="runFinished && frameFailed" class="card-note card-note--fail">
          有 {{ frameFailed }} 間失敗，可以在格子裡個別重試。
        </p>
        <p v-else-if="runFinished" class="card-note">點任一格可以看那間的生成結果。</p>
      </section>

      <p v-if="!activeIsDone && rendering[activeRoomId]" class="minimap-hint">
        這間房還在渲染，可以先去看別間，完成後會自動標示。
      </p>
      <button
        v-else-if="!activeIsDone"
        type="button"
        class="minimap-abandon"
        @click="onAbandon" @blur="confirmingAbandon = false"
      >{{ confirmingAbandon ? '確定放棄？進度會清除' : '放棄這間房，改選其他' }}</button>
      <p v-if="doneCount >= totalCount && totalCount > 0" class="minimap-hint minimap-hint--done">
        全部房間都完成了，點任一間可以再看一次渲染圖
      </p>

    <!-- 放大平面圖：確認卡打開時點房間 = 切換要不要做；平常點房間 = 切過去編輯 -->
    <Teleport to="body">
      <div v-if="expanded" class="minimap-modal" @click.self="closeModal">
        <div class="modal-card" role="dialog" aria-modal="true" aria-label="整層平面圖">
          <div class="modal-head">
            <h3 class="modal-title">整層平面圖 <small>{{ doneCount }} / {{ totalCount }} 間完成</small></h3>
            <button type="button" class="modal-close" aria-label="關閉" @click="closeModal">✕</button>
          </div>
          <p class="modal-hint">
            <template v-if="selecting">點房間決定要不要套用，選好回到卡片按「開始生成」。</template>
            <template v-else>
              點已完成的房間看生成結果；其他房間會進去設計，目前這間的編輯會先幫你存起來。
            </template>
          </p>
          <button
            v-if="!activeIsDone && !rendering[activeRoomId]"
            type="button"
            class="minimap-abandon modal-abandon"
            @click="onAbandon" @blur="confirmingAbandon = false"
          >{{ confirmingAbandon ? '確定放棄？進度會清除' : '放棄這間房，改選其他' }}</button>
          <div ref="modalBoardRef" class="minimap-board modal-board" v-html="plan?.svg_markup || ''"></div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
.cad-minimap {
  position: sticky;
  top: 24px;
  padding: 1.1rem;
  border-radius: var(--db-radius-chip);
  background: var(--db-chip-soft);
}

/* 頂部細列：平面圖只隱藏不卸載（點房間的事件還掛在上面），確認卡打開時會自動回到完整版 */
.cad-minimap.is-compact {
  position: static;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0 1.25rem;
  margin-bottom: 1.25rem;
  padding: 0 0.25rem;
  border-radius: 0;
  background: none;
  border-bottom: 1px solid #e6dfd3;   /* 不再是一個框，只有一條底線，標籤的底線指示器壓在上面 */
}
.is-compact .minimap-head { display: none; }   /* 進度改由房間標籤列表達 */
.is-compact .minimap-board { display: none; }
/* 房間標籤列（底線式分頁）：目前這間加粗＋深色底線、已完成 = 深色字、其餘灰字、虛線底線 = 做到一半切走的，點標籤直接切房 */
.room-tabs { display: flex; flex: 1 1 auto; flex-wrap: wrap; gap: 0 2rem; margin: 0; padding: 0; list-style: none; }
.room-tab {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  margin-bottom: -1px;   /* 底線壓住整條的底線 */
  padding: 0.85rem 0.1rem;
  border: none;
  border-bottom: 3px solid transparent;
  background: none;
  color: var(--db-text-soft);
  font-size: 1.3rem;
  cursor: pointer;
  transition: color 0.16s, border-color 0.16s;
}
.room-tab:hover:not(:disabled):not(.active) { color: var(--db-text); border-bottom-color: #cfc6b8; }
.room-tab.done { color: var(--db-text); }   /* 做完 = 深色字；還沒做完／生成中 = 灰字，不用 ✓ */
.room-tab.wip { border-bottom: 3px dashed var(--db-accent-ink); }
.room-tab.active { color: var(--db-text); font-weight: 600; border-bottom-color: var(--db-accent-ink); cursor: default; }
.room-tab--overview { padding-right: 1.4rem; margin-right: 0.2rem; border-right: 1px solid #e6dfd3; border-radius: 0; }   /* 「總覽」跟各房間之間隔一條細線 */
.room-tab.busy { color: var(--db-text-soft); }
.room-tab.failed { color: var(--db-danger); }
.room-tab:disabled { cursor: not-allowed; opacity: 0.6; }
.room-tab:focus-visible { outline: 2px solid var(--db-text); outline-offset: 2px; }
.batch-status { display: flex; align-items: center; gap: 0.75rem; font-size: 0.9rem; font-variant-numeric: tabular-nums; }
.batch-text { color: var(--db-text); font-weight: 600; white-space: nowrap; }
.batch-bar { display: inline-block; width: 96px; height: 6px; border-radius: 3px; background: #e4ded4; overflow: hidden; }
.batch-bar i { display: block; height: 100%; background: var(--db-accent-ink); transition: width 0.3s; }
.tab-note { font-size: 0.8rem; opacity: 0.8; }
/* 「查看平面圖」是文字連結（只是看圖，不是主要動作）；「一次做完」是右邊唯一的動作按鈕 */
.is-compact .minimap-expand {
  width: auto; margin: 0; padding: 0.2rem 0.25rem;
  border: none; background: none; color: var(--db-text-soft); font-size: 0.88rem;
  text-decoration: underline; text-underline-offset: 3px;
}
.is-compact .minimap-expand:hover { background: none; color: var(--db-text); }
/* 「一次做完」：外框膠囊，說明小字不顯示 */
.is-compact .minimap-apply {
  width: auto; min-height: 0; margin: 0; padding: 0.45rem 1.1rem;
  border: 1.5px solid var(--db-accent-ink); border-radius: var(--db-radius-pill);
  background: #fff; color: var(--db-accent-ink); font-size: 0.88rem;
}
.is-compact .minimap-apply small { display: none; }
.is-compact .minimap-apply:hover { filter: none; transform: none; background: #faf8f5; }
/* 右側的連結／按鈕／狀態：標籤列上下沒有留白，這幾個自己留 */
.is-compact .minimap-expand, .is-compact .minimap-apply, .is-compact .batch-status { margin-block: 0.5rem; }
.is-compact .apply-card { flex: 1 1 100%; max-width: 640px; margin-top: 0; }
/* 選房間時：整塊變成置中的浮動視窗（左平面圖、右確認卡），背後壓暗；
   inset:0 + margin:auto + 固定寬度 = 置中，box-shadow 當遮罩，不用另外加一層 modal 元素 */
.cad-minimap.is-compact-open {
  position: fixed;
  inset: 0;
  z-index: 1000;
  box-sizing: border-box;
  width: min(1120px, calc(100vw - 2rem));
  height: fit-content;
  max-height: calc(100vh - 2rem);
  margin: auto;
  overflow-y: auto;
  padding: 1.75rem;
  border-radius: 16px;
  background: var(--db-card);
  box-shadow: 0 0 0 100vmax rgba(20, 18, 14, 0.55), 0 12px 40px rgba(0, 0, 0, 0.3);
  display: grid;
  grid-template-columns: minmax(280px, 560px) minmax(0, 1fr);
  gap: 1rem 2rem;
  align-items: start;
  animation: card-in 0.22s ease-out;
}
.is-compact-open .minimap-head { grid-column: 1 / -1; margin: 0; align-items: center; justify-content: flex-start; gap: 1rem; }
.is-compact-open .minimap-title { font-size: 1.4rem; }
.is-compact-open .minimap-count { margin-left: auto; font-size: 1rem; }
.minimap-close {
  display: grid;
  place-items: center;
  width: 40px;
  height: 40px;
  border: none;
  border-radius: 50%;
  background: var(--db-chip-soft);
  color: var(--db-text);
  font-size: 1.05rem;
  cursor: pointer;
  transition: background 0.16s;
}
.minimap-close:hover { background: #e2ded6; }
.minimap-close:focus-visible { outline: 2px solid var(--db-text); outline-offset: 2px; }
/* 浮動視窗本身就是面板，裡面的確認卡不再自己畫框（避免框中有框） */
.is-compact-open .minimap-head { padding-bottom: 0.9rem; border-bottom: 1px solid #eeeae3; }
.is-compact-open .apply-card { padding: 0; border: none; border-radius: 0; animation: none; }
.is-compact-open .card-label, .is-compact-open .card-foot, .is-compact-open .batch-fengshui summary { font-size: 0.95rem; }
.is-compact-open .apply-go { min-height: 54px; font-size: 1.1rem; }
.chips { display: flex; flex-wrap: wrap; gap: 0.4rem; margin: 0 0 1.1rem; padding: 0; list-style: none; }
.chips li {
  max-width: 100%;
  padding: 0.25rem 0.8rem;
  border-radius: var(--db-radius-pill);
  background: var(--db-chip-soft);
  color: var(--db-text);
  font-size: 0.85rem;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.is-compact-open .minimap-board { grid-column: 1; grid-row: 2 / span 4; }
.is-compact-open .minimap-expand { display: none; }
.is-compact-open .apply-card { grid-column: 2; grid-row: 2; margin-top: 0; }
@media (max-width: 700px) {
  .cad-minimap.is-compact-open { grid-template-columns: 1fr; }
  .is-compact-open .minimap-board, .is-compact-open .apply-card { grid-column: 1; grid-row: auto; }
}
.is-compact .minimap-hint, .is-compact .minimap-abandon { width: auto; margin: 0; }

.minimap-expand {
  display: block;
  width: 100%;
  margin-top: 0.6rem;
  padding: 0.45rem;
  border: 1px solid #e2ddd0;
  border-radius: var(--db-radius-pill);
  background: #fff;
  color: var(--db-text);
  font-size: 0.8rem;
  cursor: pointer;
}
.minimap-expand:hover { border-color: var(--db-accent); background: #f7f6f3; }

/* ① 主行動：整層最重要的一個按鈕，深色實心，旁邊小字說明還剩幾間 */
.minimap-apply {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.1rem;
  width: 100%;
  min-height: 48px;
  margin-top: 0.6rem;
  padding: 0.55rem 0.8rem;
  border: none;
  border-radius: var(--db-radius-chip);
  background: var(--db-accent-ink);
  color: #fff;
  font-size: 0.88rem;
  cursor: pointer;
  transition: transform 0.15s, filter 0.15s;
}
.minimap-apply small { font-size: 0.72rem; opacity: 0.8; }
.minimap-apply:hover { filter: brightness(1.1); transform: translateY(-1px); }
.minimap-apply:focus-visible, .apply-go:focus-visible, .frame-btn:focus-visible {
  outline: 2px solid var(--db-text); outline-offset: 2px;
}

/* ② 確認卡／③ 接片：同一張卡，內容隨階段改變 */
.apply-card {
  margin-top: 0.7rem;
  padding: 0.9rem;
  border: 1px solid #e8e5df;
  border-top: 3px solid var(--db-accent-ink);
  border-radius: var(--db-radius-chip);
  background: #fff;
  animation: card-in 0.22s ease-out;
}
@keyframes card-in { from { opacity: 0; transform: translateY(-4px); } to { opacity: 1; transform: none; } }
.card-headline { display: flex; align-items: baseline; justify-content: space-between; gap: 0.5rem; }
.card-title {
  margin: 0 0 0.4rem;
  font-family: var(--db-font-display);
  font-style: italic;
  font-weight: 500;
  font-size: 1.02rem;
  font-variant-numeric: tabular-nums;
}
.card-headline .card-title { margin-bottom: 0.5rem; }
.card-sub { margin: 0 0 0.6rem; font-size: 0.78rem; color: var(--db-text-soft); line-height: 1.6; }
.card-label-row { display: flex; align-items: baseline; justify-content: space-between; gap: 0.5rem; margin-bottom: 0.35rem; }
.card-label { margin: 0; font-size: 0.74rem; color: var(--db-text-soft); }
.card-note { margin: 0.55rem 0 0; font-size: 0.74rem; line-height: 1.5; color: var(--db-text-soft); }
.card-note--fail { color: var(--db-danger); }
.batch-fengshui { margin-top: 0.55rem; border-top: 1px solid #eeeae3; }
.batch-fengshui > summary {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
  min-height: 40px;
  color: var(--db-text);
  font-size: 0.78rem;
  cursor: pointer;
}
.batch-fengshui-count { color: var(--db-text-soft); font-size: 0.72rem; }
.batch-fengshui :deep(.fengshui) { margin: 0; padding: 0.4rem 0 0; border: 0; }
.batch-fengshui :deep(.fs-head) { text-align: left; }
.batch-fengshui :deep(.fs-hint) { margin: 0; font-size: 0.72rem; }
.batch-fengshui :deep(.fs-bar) { margin: 0.55rem 0; }
.batch-fengshui :deep(.fs-grid) { grid-template-columns: minmax(0, 1fr); gap: 0.4rem; }
.batch-fengshui :deep(.fs-card) { gap: 0.45rem; padding: 0.55rem; }
.batch-fengshui :deep(.fs-diagram) { width: 42px; height: 32px; }
.batch-fengshui :deep(.fs-label) { font-size: 0.88rem; }
.batch-fengshui :deep(.fs-desc) { font-size: 0.72rem; }
.card-foot { display: flex; align-items: center; justify-content: space-between; margin: 0.5rem 0 0; font-size: 0.76rem; color: var(--db-text-soft); }
.link-btn {
  padding: 0.3rem 0.1rem;
  border: none;
  background: none;
  color: var(--db-text-soft);
  font-size: 0.76rem;
  text-decoration: underline;
  cursor: pointer;
}
.link-btn:hover { color: var(--db-text); }

/* 房間標籤：預設全部「✓」，點一下變「✕」排除。高度 40px 方便手指點 */
.apply-go {
  display: block;
  width: 100%;
  min-height: 46px;
  margin-top: 0.8rem;
  border: none;
  border-radius: var(--db-radius-chip);
  background: var(--db-accent-ink);
  color: #fff;
  font-size: 0.92rem;
  font-weight: 600;
  cursor: pointer;
  transition: filter 0.15s;
}
.apply-go:hover:not(:disabled) { filter: brightness(1.1); }
.apply-go:disabled { opacity: 0.45; cursor: not-allowed; }

/* ③ 接片 */
.frames {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(92px, 1fr));
  gap: 0.45rem;
  margin: 0;
  padding: 0;
  list-style: none;
}
.frame { position: relative; aspect-ratio: 4 / 3; }
/* 失敗的格子要放得下原因與重試按鈕，所以比別格高；同一列的其他格會一起拉高 */
.frame.is-failed { aspect-ratio: auto; min-height: 112px; }
.frame-face > * { flex-shrink: 0; }
.frame-face {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  justify-content: flex-end;
  gap: 0.1rem;
  overflow: hidden;
  padding: 0.4rem 0.5rem;
  border: 1px solid #e6e3dd;
  border-radius: 8px;
  background: var(--db-chip-soft);
  text-align: left;
}
.frame-name { position: relative; z-index: 1; font-size: 0.78rem; font-weight: 600; color: var(--db-text); }
.frame-state { position: relative; z-index: 1; font-size: 0.7rem; color: var(--db-text-soft); }
.frame-state--fail { color: var(--db-danger); font-weight: 600; }
.frame-error { position: relative; z-index: 1; font-size: 0.66rem; line-height: 1.3; color: var(--db-danger); display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.frame-retry:disabled { opacity: 0.45; cursor: not-allowed; }
.frame-retry {
  position: relative; z-index: 1;
  align-self: flex-start;
  margin-top: 0.15rem;
  padding: 0.1rem 0.55rem;
  border: 1px solid var(--db-danger);
  border-radius: var(--db-radius-pill);
  background: #fff;
  color: var(--db-danger);
  font-size: 0.7rem;
  cursor: pointer;
}
.frame.is-queued .frame-face { background: #f6f5f2; }
.frame.is-queued .frame-name, .frame.is-queued .frame-state { opacity: 0.6; }
.frame.is-stopped .frame-face { background: #f3f3f3; border-style: dashed; }
.frame.is-failed .frame-face { background: var(--db-danger-soft); border-color: #e9c4bf; }

/* 生成中：一道緩慢掃過的光，像底片正在顯影 */
.frame.is-running .frame-face::before {
  content: '';
  position: absolute;
  inset: 0;
  background: linear-gradient(100deg, transparent 20%, rgba(255, 255, 255, 0.85) 50%, transparent 80%);
  transform: translateX(-100%);
  animation: develop 1.5s ease-in-out infinite;
}
@keyframes develop { to { transform: translateX(100%); } }

/* 完成：縮圖浮現，名字壓在底部漸層上 */
.frame.is-done .frame-face { padding: 0; border-color: var(--db-accent-ink); cursor: pointer; }
.frame-btn { width: 100%; height: 100%; cursor: pointer; }
.frame-img { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; animation: develop-in 0.5s ease-out; }
@keyframes develop-in { from { opacity: 0; filter: blur(6px); } to { opacity: 1; filter: none; } }
.frame.is-done .frame-name {
  position: absolute;
  left: 0; right: 0; bottom: 0;
  padding: 1rem 0.5rem 0.35rem;
  background: linear-gradient(to top, rgba(0, 0, 0, 0.6), transparent);
  color: #fff;
}
.frame-badge {
  position: absolute;
  top: 0.3rem; right: 0.3rem;
  z-index: 1;
  display: grid; place-items: center;
  width: 20px; height: 20px;
  border-radius: 50%;
  background: #fff;
  color: var(--db-accent-ink);
  font-size: 0.72rem;
  font-weight: 700;
}

@media (prefers-reduced-motion: reduce) {
  .apply-card, .frame-img { animation: none; }
  .frame.is-running .frame-face::before { animation: none; transform: none; background: rgba(255, 255, 255, 0.55); }
  .minimap-apply { transition: none; }
}

.minimap-abandon {
  display: block;
  width: 100%;
  margin-top: 0.4rem;
  padding: 0.4rem;
  border: none;
  border-radius: var(--db-radius-pill);
  background: none;
  color: var(--db-text-soft);
  font-size: 0.76rem;
  text-decoration: underline;
  cursor: pointer;
}
.minimap-abandon:hover { color: var(--db-danger); }
.modal-abandon { width: auto; margin: 0 0 0.8rem; padding: 0.2rem 0; }

.minimap-modal {
  position: fixed;
  inset: 0;
  z-index: 1000;
  display: grid;
  place-items: center;
  padding: 1.5rem;
  background: rgba(20, 18, 14, 0.55);
}
.modal-card {
  width: min(1000px, 100%);
  max-height: 100%;
  overflow: auto;
  padding: 1.25rem 1.5rem 1.5rem;
  border-radius: var(--db-radius-card);
  background: #fff;
  box-shadow: var(--db-shadow-card);
}
.modal-head { display: flex; align-items: center; justify-content: space-between; gap: 1rem; }
.modal-title { margin: 0; font-family: var(--db-font-display); font-style: italic; font-weight: 500; font-size: 1.3rem; }
.modal-title small { margin-left: 0.6rem; font-size: 0.85rem; color: var(--db-text-soft); font-style: normal; }
.modal-close { border: none; background: var(--db-chip-soft); width: 36px; height: 36px; border-radius: 50%; cursor: pointer; }
.modal-close:hover { background: var(--db-chip); }
.modal-hint { margin: 0.4rem 0 0.8rem; font-size: 0.85rem; color: var(--db-text-soft); }
.modal-board { cursor: default; }


.minimap-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 0.5rem;
  margin-bottom: 0.5rem;
}
.minimap-title {
  font-family: var(--db-font-display);
  font-style: italic;
  font-weight: 500;
  font-size: 0.88rem;
  color: var(--db-text);
}
.minimap-count {
  font-size: 0.74rem;
  color: var(--db-text-soft);
  font-variant-numeric: tabular-nums;
}

.minimap-board { overflow: hidden; border-radius: 8px; }
.minimap-board :deep(svg) { width: 100%; height: auto; display: block; }

/* 縮圖很小：尺寸、門窗寬度、面積、總面積這類細節只會糊成一團，整組不顯示；
   房名反而要放大才看得清楚（SVG 的 CSS 單位＝畫布座標，縮圖約縮成一半，所以字要設得比預期大）。
   放大後的大卡片（.modal-board）維持完整細節。 */
.minimap-board:not(.modal-board) :deep(.plan-detail) { display: none; }
.minimap-board:not(.modal-board) :deep(.plan-name) {
  font-size: 26px;
  stroke-width: 5px;
  transform: translateY(14px);   /* 面積那行不顯示後，房名移到房間正中央 */
}

.minimap-board :deep(.room-rect.is-clickable) { cursor: pointer; }
.minimap-board :deep(.room-rect.is-locked) { cursor: not-allowed; }
.minimap-board :deep(.room-rect .room-floor) { transition: fill 0.15s, stroke 0.15s; }
.minimap-board :deep(.room-rect.is-clickable:hover .room-floor) {
  fill: var(--db-accent-soft);
  stroke: var(--db-accent-deep);
}
.minimap-board :deep(.room-rect.is-active .room-floor) {
  fill: var(--db-accent);
  stroke: var(--db-accent-deep);
}
.minimap-board :deep(.room-rect.is-done:not(.is-active) .room-floor) {
  fill: var(--db-accent-deep);
}
/* 設計到一半、先切去別間的房間：淡色底加虛線，提醒「這間還沒做完」 */
.minimap-board :deep(.room-rect.is-wip:not(.is-active) .room-floor) { fill: var(--db-accent-soft); stroke: var(--db-accent-ink); stroke-dasharray: 6 4; }
/* 確認卡打開時：會做的房間描邊、排除的變灰虛線；批次中：排隊淡色、生成中閃動、失敗紅描邊 */
.minimap-board :deep(.room-rect.is-target .room-floor) { stroke: var(--db-accent-ink); stroke-width: 3; }
.minimap-board :deep(.room-rect.is-skipped .room-floor) { fill: #e4e1da; stroke: #9a968c; stroke-dasharray: 6 4; }
/* 確認卡打開時，每間候選房間左上角的 ✓／✕；用鍵盤聚焦到房間時外框加粗 */
.minimap-board :deep(.sel-mark circle) { fill: var(--db-accent-ink); stroke: #fff; stroke-width: 2; }
.minimap-board :deep(.sel-mark text) { fill: #fff; }
.minimap-board :deep(.sel-mark.is-off circle) { fill: #fff; stroke: #9a968c; stroke-dasharray: 4 3; }
.minimap-board :deep(.sel-mark.is-off text) { fill: #9a968c; }
.minimap-board :deep(.room-rect:focus-visible) { outline: none; }
.minimap-board :deep(.room-rect:focus-visible .room-floor) { stroke: var(--db-text); stroke-width: 4; }
.minimap-board :deep(.room-rect.is-queued .room-floor) { fill: var(--db-accent-soft); }
.minimap-board :deep(.room-rect.is-running .room-floor) { fill: var(--db-accent); animation: room-pulse 1.2s ease-in-out infinite; }
.minimap-board :deep(.room-rect.is-failed .room-floor) { stroke: var(--db-danger); stroke-width: 3; }
@keyframes room-pulse { 50% { opacity: 0.55; } }
@media (prefers-reduced-motion: reduce) {
  .minimap-board :deep(.room-rect.is-running .room-floor) { animation: none; }
}

.minimap-hint {
  margin: 0.5rem 0 0;
  font-size: 0.72rem;
  line-height: 1.5;
  color: var(--db-placeholder);
  text-align: center;
}
.minimap-hint--done { color: var(--db-accent-deep); }

@media (max-width: 1100px) {
  .cad-minimap { position: static; width: 100%; margin-bottom: 1.25rem; }
}
</style>
