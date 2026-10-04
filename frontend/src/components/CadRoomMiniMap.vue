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
 */
import { ref, computed, watch, nextTick, onBeforeUnmount, onMounted } from 'vue'

const props = defineProps({
  plan:             { type: Object, required: true },   // cadPlanResult：{ rooms, svg_markup, ... }
  roomStatus:       { type: Object, default: () => ({}) }, // { [roomId]: 'active' | 'done' }
  activeRoomId:     { type: String, default: null },
  activePlacements: { type: Array, default: () => [] },    // 目前這間房的 editPlacements，即時反映在縮圖上
})
const emit = defineEmits(['select-room'])

const collapsed = ref(false)
const boardRef = ref(null)
const modalBoardRef = ref(null)
const expanded = ref(false)   // 點縮圖 → 彈出大卡片，在裡面選其他空間
let cleanupFns = []

const totalCount = computed(() => props.plan?.rooms?.length || 0)
const doneCount = computed(() => Object.values(props.roomStatus).filter(s => s === 'done').length)
const activeIsDone = computed(() => !props.activeRoomId || props.roomStatus[props.activeRoomId] === 'done')

function clearHandlers() {
  cleanupFns.forEach(fn => fn())
  cleanupFns = []
}

// 縮圖與彈出的大卡片是同一份 svg_markup，各自一個容器，都要上色 / 掛點擊
const boards = () => [boardRef.value, modalBoardRef.value].filter(Boolean)

function paint() {
  clearHandlers()
  boards().forEach(paintBoard)
  paintLiveFurniture()
}

function paintBoard(board) {
  const svg = board.querySelector('svg')
  if (!svg) return
  svg.querySelectorAll('.room-rect').forEach((g) => {
    const roomId = g.getAttribute('data-room-id')
    const isActive = roomId === props.activeRoomId
    const isDone = props.roomStatus[roomId] === 'done'
    const clickable = !isActive && activeIsDone.value

    g.classList.toggle('is-active', isActive)
    g.classList.toggle('is-done', isDone)
    g.classList.toggle('is-clickable', clickable)

    if (clickable) {
      const room = (props.plan.rooms || []).find(r => r.id === roomId)
      if (room) {
        const onClick = () => { expanded.value = false; emit('select-room', room) }
        g.addEventListener('click', onClick)
        cleanupFns.push(() => g.removeEventListener('click', onClick))
      }
    }
  })
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
  () => [props.plan?.svg_markup, props.roomStatus, props.activeRoomId, expanded.value],
  () => nextTick(paint),
  { immediate: true, deep: true },
)
// 家具本身變動（拖曳/加/刪）不需要整個 paint() 重跑（那會重掛點擊事件），
// 只要重畫這間房的家具就好。
watch(() => props.activePlacements, () => nextTick(paintLiveFurniture), { deep: true })
onBeforeUnmount(clearHandlers)
function onKey(e) { if (e.key === 'Escape') expanded.value = false }
onMounted(() => window.addEventListener('keydown', onKey))
onBeforeUnmount(() => window.removeEventListener('keydown', onKey))
</script>

<template>
  <div class="cad-minimap" :class="{ collapsed }">
    <button type="button" class="minimap-toggle" @click="collapsed = !collapsed">
      {{ collapsed ? '展開整層平面圖' : '收合' }}
    </button>

    <template v-if="!collapsed">
      <div class="minimap-head">
        <span class="minimap-title">整層進度</span>
        <span class="minimap-count">{{ doneCount }} / {{ totalCount }} 間完成</span>
      </div>
      <div ref="boardRef" class="minimap-board" v-html="plan?.svg_markup || ''"></div>
      <button type="button" class="minimap-expand" @click="expanded = true">放大並選擇其他空間</button>
      <p v-if="doneCount >= totalCount && totalCount > 0" class="minimap-hint minimap-hint--done">
        全部房間都完成了 🎉 點任一間可以再看一次渲染圖
      </p>
    </template>

    <!-- 大卡片：放大的整層平面圖，在這裡點選其他空間（規則同縮圖：目前這間渲染完才能切） -->
    <Teleport to="body">
      <div v-if="expanded" class="minimap-modal" @click.self="expanded = false">
        <div class="modal-card" role="dialog" aria-modal="true" aria-label="整層平面圖">
          <div class="modal-head">
            <h3 class="modal-title">整層平面圖 <small>{{ doneCount }} / {{ totalCount }} 間完成</small></h3>
            <button type="button" class="modal-close" aria-label="關閉" @click="expanded = false">✕</button>
          </div>
          <p class="modal-hint">
            {{ activeIsDone ? '點選其他房間切換過去編輯' : '目前這間房完成渲染後，才能切換到其他房間' }}
          </p>
          <div ref="modalBoardRef" class="minimap-board modal-board" v-html="plan?.svg_markup || ''"></div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
/* 這是卡片內部 grid 的第二欄（見 StudioView.vue 的 .studio-card.has-minimap），
   不是另外浮在旁邊的獨立白卡，所以不用自己的背景/陰影/圓角去模仿一個框——
   淡底色只是跟主內容拉開一點視覺區隔，不是「第二個框框」。
   position: sticky 讓它在卡片內容比視窗高、需要捲動時還留在看得到的地方。 */
.cad-minimap {
  position: sticky;
  top: 24px;
  padding: 0.85rem;
  border-radius: var(--db-radius-chip);
  background: var(--db-chip-soft);
}
.cad-minimap.collapsed { padding: 0.5rem; }

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

.minimap-toggle {
  display: block;
  margin: 0 auto 0.5rem;
  padding: 0.3rem 0.8rem;
  border: none;
  border-radius: var(--db-radius-pill);
  background: var(--db-chip-soft);
  color: var(--db-text-soft);
  font-size: 0.76rem;
  cursor: pointer;
}
.collapsed .minimap-toggle { margin-bottom: 0; }
.minimap-toggle:hover { background: var(--db-chip); color: var(--db-text); }

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

.minimap-board :deep(.room-rect.is-clickable) { cursor: pointer; }
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
