<script setup>
/**
 * 整層總覽：每間房的渲染縮圖、平面圖對照，以及整層家具預算加總。
 * 資料都來自既有狀態：目前這間用全域 result，其餘房間用 cadRoomSnapshots。
 * 預算只加總「已估價」的房間（估價要 30–40 秒、不會自動做），沒估的由「為其餘 N 間估價」補。
 */
import { computed, ref, watch, nextTick, onMounted } from 'vue'
import { useDesignFlow } from '@/composables/useDesignFlow'
import { quotationTotal } from '@/composables/design-flow/quotation'

const {
  cadPlanResult, cadRoomStatus, cadActiveRoomId, cadRoomSnapshots, cadQuoting, cadBatch,
  result, lastGeneratedImage, quotationLoading, handleCadRoomSelected, quoteRooms,
} = useDesignFlow()

const rooms = computed(() => cadPlanResult.value?.rooms || [])

const rows = computed(() => rooms.value.map((room) => {
  const isActive = room.id === cadActiveRoomId.value
  const snap = cadRoomSnapshots.value[room.id]
  const res = isActive ? result.value : snap?.result
  const img = isActive ? lastGeneratedImage.value : snap?.lastGeneratedImage
  const q = res?.quotation_result || null
  return {
    room,
    done: cadRoomStatus.value[room.id] === 'done',
    img: img?.url || res?.generated_image_url || '',
    quoted: !!q,
    total: q ? quotationTotal(q) : 0,
    count: q?.furniture_list?.length || 0,
    quoting: !!cadQuoting.value[room.id] || (isActive && quotationLoading.value),
    generating: ['queued', 'running'].includes(cadBatch.value[room.id]?.status),
  }
}))

const doneRows = computed(() => rows.value.filter(r => r.done))
const quotedCount = computed(() => doneRows.value.filter(r => r.quoted).length)
const totalBudget = computed(() => rows.value.reduce((s, r) => s + (r.quoted ? r.total : 0), 0))
const pending = computed(() => doneRows.value.filter(r => !r.quoted && r.img))
const quotingCount = computed(() => rows.value.filter(r => r.quoting).length)

function quoteAll() { quoteRooms(pending.value.map(r => r.room.id)) }

// ── 平面圖：同一份 svg，只上色與掛點擊；滑過房間／卡片互相高亮，方便對照 ──
const boardRef = ref(null)
const hoverId = ref(null)
const roomIdOf = (e) => e.target.closest?.('.room-rect')?.getAttribute('data-room-id') || null

function onBoardClick(e) {
  const room = rooms.value.find(r => r.id === roomIdOf(e))
  if (room) handleCadRoomSelected(room)
}
function paint() {
  const svg = boardRef.value?.querySelector('svg')
  if (!svg) return
  svg.querySelectorAll('.room-rect').forEach((g) => {
    const id = g.getAttribute('data-room-id')
    g.classList.toggle('is-done', cadRoomStatus.value[id] === 'done')
    g.classList.toggle('is-hover', hoverId.value === id)
  })
}
watch(
  () => [cadPlanResult.value?.svg_markup, cadRoomStatus.value, hoverId.value],
  () => nextTick(paint),
  { deep: true },
)
onMounted(paint)
</script>

<template>
  <div class="overview">
    <header class="ov-head">
      <div>
        <h2 class="ov-title">整層總覽</h2>
        <p class="ov-sub">
          {{ doneRows.length }} / {{ rooms.length }} 間完成<template v-if="doneRows.length < rooms.length">，其餘點房間繼續設計</template>
        </p>
      </div>
      <div class="ov-budget">
        <span class="ov-budget-label">
          整層家具預算<template v-if="quotedCount < doneRows.length">（已估價 {{ quotedCount }} / {{ doneRows.length }} 間）</template>
        </span>
        <span class="ov-budget-val">NT$ {{ totalBudget.toLocaleString() }}</span>
        <button
          v-if="pending.length || quotingCount"
          type="button" class="db-btn db-btn--sm" :disabled="quotingCount > 0" @click="quoteAll"
        >{{ quotingCount ? `估價中…（${quotingCount} 間）` : `為其餘 ${pending.length} 間估價` }}</button>
      </div>
    </header>

    <div class="ov-body">
      <div
        ref="boardRef" class="ov-plan" v-html="cadPlanResult?.svg_markup || ''"
        @click="onBoardClick" @mouseover="hoverId = roomIdOf($event)" @mouseleave="hoverId = null"
      ></div>

      <ul class="ov-rooms">
        <li v-for="r in rows" :key="r.room.id">
          <button
            type="button" class="ov-card" :class="{ 'is-empty': !r.done, 'is-hover': hoverId === r.room.id }"
            @click="handleCadRoomSelected(r.room)"
            @mouseenter="hoverId = r.room.id" @mouseleave="hoverId = null"
            @focus="hoverId = r.room.id" @blur="hoverId = null"
          >
            <span class="ov-thumb">
              <img v-if="r.img" :src="r.img" :alt="`${r.room.label_zh}的渲染圖`" />
              <span v-else class="ov-thumb-empty">{{ r.generating ? '生成中…' : '尚未設計' }}</span>
            </span>
            <span class="ov-name">{{ r.room.label_zh }}</span>
            <span class="ov-price">
              <template v-if="r.quoted">NT$ {{ r.total.toLocaleString() }}<small>{{ r.count }} 件</small></template>
              <template v-else-if="r.quoting">估價中…</template>
              <template v-else-if="r.done">尚未估價</template>
            </span>
          </button>
        </li>
      </ul>
    </div>
  </div>
</template>

<style scoped>
.overview { display: flex; flex-direction: column; gap: 1.5rem; }

.ov-head { display: flex; flex-wrap: wrap; align-items: flex-end; justify-content: space-between; gap: 1rem 2rem; }
.ov-title {
  margin: 0;
  font-family: var(--db-font-display);
  font-style: italic;
  font-weight: 500;
  font-size: 1.6rem;
  color: var(--db-text);
}
.ov-sub { margin: 0.25rem 0 0; color: var(--db-text-soft); font-size: 0.95rem; }
.ov-budget { display: flex; flex-wrap: wrap; align-items: baseline; justify-content: flex-end; gap: 0.5rem 1rem; }
.ov-budget-label { color: var(--db-text-soft); font-size: 0.92rem; }
.ov-budget-val {
  font-family: var(--db-font-display);
  font-size: 2rem;
  color: var(--db-text);
  font-variant-numeric: tabular-nums;
}

.ov-body { display: grid; grid-template-columns: minmax(280px, 0.8fr) minmax(0, 1.2fr); gap: 2rem; align-items: start; }

.ov-plan { overflow: hidden; border-radius: 12px; background: #fff; border: 1px solid #ececec; padding: 0.75rem; }
.ov-plan :deep(svg) { width: 100%; height: auto; display: block; }
.ov-plan :deep(.room-rect) { cursor: pointer; }
.ov-plan :deep(.room-rect .room-floor) { transition: fill 0.15s, stroke 0.15s; }
.ov-plan :deep(.room-rect.is-done .room-floor) { fill: var(--db-accent-soft); }
.ov-plan :deep(.room-rect.is-hover .room-floor) { fill: var(--db-accent); stroke: var(--db-accent-deep); }

.ov-rooms { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 1rem; margin: 0; padding: 0; list-style: none; }
.ov-card {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
  width: 100%;
  padding: 0.5rem;
  border: 2px solid #ececec;
  border-radius: 14px;
  background: #fff;
  text-align: left;
  cursor: pointer;
  transition: border-color 0.16s, box-shadow 0.16s;
}
.ov-card:hover, .ov-card.is-hover { border-color: var(--db-accent-ink); box-shadow: var(--db-shadow-soft); }
.ov-card:focus-visible { outline: 2px solid var(--db-text); outline-offset: 2px; }
.ov-thumb {
  display: grid;
  place-items: center;
  aspect-ratio: 16 / 10;
  border-radius: 10px;
  background: var(--db-chip-soft);
  overflow: hidden;
}
.ov-thumb img { width: 100%; height: 100%; object-fit: cover; display: block; }
.ov-thumb-empty { color: var(--db-placeholder); font-size: 0.9rem; }
.ov-card.is-empty .ov-name { color: var(--db-text-soft); }
.ov-name { padding: 0 0.25rem; font-size: 1.15rem; font-weight: 600; color: var(--db-text); }
.ov-price { min-height: 1.3em; padding: 0 0.25rem 0.2rem; color: var(--db-text-soft); font-size: 0.92rem; font-variant-numeric: tabular-nums; }
.ov-price small { margin-left: 0.5rem; font-size: 0.8rem; }

@media (max-width: 1100px) {
  .ov-body { grid-template-columns: 1fr; }
}
</style>
