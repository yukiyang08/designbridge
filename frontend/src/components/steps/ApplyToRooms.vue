<script setup>
/**
 * 渲染完成頁的「套用到其他房間」（整層／cad 流程才有）。
 * 把目前這間房的風格、描述、比例、風水直接套到勾選的房間，一次生成它們的渲染圖。
 * 批次引擎見 composables/design-flow/cadBatch.js。
 */
import { computed, ref, watch } from 'vue'
import { useDesignFlow, ASPECT_OPTIONS } from '@/composables/useDesignFlow'

const {
  planSource, cadPlanResult, cadRoomStatus, cadActiveRoomId, cadBatch, cadBatchRunning,
  applyToRooms, cancelCadBatch, handleCadRoomSelected,
  confirmedStyle, result, outputAspect, extraPrompt,
} = useDesignFlow()

const CONCURRENCY = 2
const SKIP_BY_DEFAULT = new Set(['bathroom', 'balcony'])   // 預設家具擺法對這兩種不太能直接用

const rooms = computed(() =>
  planSource.value === 'cad'
    ? (cadPlanResult.value?.rooms || []).filter(r => r.id !== cadActiveRoomId.value)
    : [],
)
const isDone = (r) => cadRoomStatus.value[r.id] === 'done'
const batchOf = (r) => cadBatch.value[r.id]
const pickable = (r) => !isDone(r) && !batchOf(r)

const picked = ref(new Set())
// 房間清單變了（換了一整層、或換了目前編輯的房間）才重設預設勾選，不要在每間完成時洗掉使用者的選擇
watch(
  () => rooms.value.map(r => r.id).join(','),
  () => { picked.value = new Set(rooms.value.filter(r => pickable(r) && !SKIP_BY_DEFAULT.has(r.room_type)).map(r => r.id)) },
  { immediate: true },
)
function toggle(r) {
  const s = new Set(picked.value)
  s.has(r.id) ? s.delete(r.id) : s.add(r.id)
  picked.value = s
}

const chosen = computed(() => rooms.value.filter(r => pickable(r) && picked.value.has(r.id)))

// 每張約 30–60 秒（跟載入畫面同一個說法），同時跑 CONCURRENCY 張
const estimate = computed(() => {
  const rounds = Math.ceil(chosen.value.length / CONCURRENCY)
  return `${Math.max(1, Math.round(rounds * 30 / 60))}–${Math.max(1, Math.ceil(rounds))} 分鐘`
})

const total = computed(() => Object.keys(cadBatch.value).length)
const failedCount = computed(() => rooms.value.filter(r => batchOf(r)?.status === 'failed').length)

const settingLabels = computed(() => [
  `風格：${confirmedStyle.value?.style_name || result.value?.style_params?.style_profile_id || '自動'}`,
  `比例：${ASPECT_OPTIONS.find(o => o.value === outputAspect.value)?.label || outputAspect.value}`,
  extraPrompt.value.trim() ? `描述：${extraPrompt.value.trim().slice(0, 16)}${extraPrompt.value.trim().length > 16 ? '…' : ''}` : '',
].filter(Boolean))

const STATUS_TEXT = { queued: '等待中', running: '生成中…', failed: '失敗' }
</script>

<template>
  <section v-if="rooms.length" class="apply-rooms">
    <h3 class="sub-title">套用到其他房間</h3>
    <p class="hint">
      把這間房的設定套用過去，依平面圖一次生成其他房間的渲染圖。每間先用預設家具擺法，生成後可以再進去微調。
    </p>
    <p class="settings">
      <span v-for="s in settingLabels" :key="s" class="setting-chip">{{ s }}</span>
    </p>

    <ul class="room-list">
      <li v-for="r in rooms" :key="r.id" class="room-row" :class="{ 'is-busy': batchOf(r) && batchOf(r).status !== 'failed' }">
        <label v-if="pickable(r)" class="room-check">
          <input type="checkbox" :checked="picked.has(r.id)" :disabled="cadBatchRunning" @change="toggle(r)" />
          <span>{{ r.label_zh }}</span>
        </label>
        <span v-else class="room-name">{{ r.label_zh }}</span>

        <span v-if="isDone(r)" class="badge badge-done">✓ 已完成</span>
        <span v-else-if="batchOf(r)" class="badge" :class="`badge-${batchOf(r).status}`">
          {{ STATUS_TEXT[batchOf(r).status] }}<template v-if="batchOf(r).error">：{{ batchOf(r).error }}</template>
        </span>

        <button v-if="isDone(r)" type="button" class="row-btn" @click="handleCadRoomSelected(r)">進入編輯</button>
        <button
          v-else-if="batchOf(r)?.status === 'failed'" type="button" class="row-btn"
          :disabled="cadBatchRunning" @click="applyToRooms([r.id])"
        >重試</button>
      </li>
    </ul>

    <div class="apply-actions">
      <button
        v-if="!cadBatchRunning" type="button" class="db-btn db-btn--sm"
        :disabled="!chosen.length" @click="applyToRooms(chosen.map(r => r.id))"
      >生成 {{ chosen.length }} 間的渲染圖</button>
      <template v-else>
        <span class="progress">生成中，剩 {{ total }} 間</span>
        <button type="button" class="db-btn db-btn--ghost db-btn--sm" @click="cancelCadBatch">取消</button>
      </template>
      <span v-if="!cadBatchRunning && chosen.length" class="estimate">預估約 {{ estimate }}（同時生成 {{ CONCURRENCY }} 間）</span>
      <span v-if="!cadBatchRunning && failedCount" class="estimate">{{ failedCount }} 間失敗，可個別重試</span>
    </div>
  </section>
</template>

<style scoped>
.apply-rooms { margin-top: 1.5rem; padding-top: 1.25rem; border-top: 1px solid #f0f0f0; }
.sub-title { margin: 0 0 0.4rem; font-family: var(--db-font-display); font-style: italic; font-weight: 500; font-size: 1.15rem; }
.hint { margin: 0 0 0.6rem; font-size: 0.85rem; color: var(--db-text-soft); }
.settings { display: flex; flex-wrap: wrap; gap: 0.4rem; margin: 0 0 0.9rem; }
.setting-chip { padding: 0.15rem 0.6rem; border-radius: var(--db-radius-pill); background: var(--db-chip-soft); font-size: 0.78rem; color: var(--db-text); }

.room-list { list-style: none; margin: 0 0 1rem; padding: 0; display: flex; flex-direction: column; gap: 0.35rem; }
.room-row {
  display: flex; align-items: center; gap: 0.75rem;
  padding: 0.5rem 0.8rem; border-radius: var(--db-radius-chip); background: var(--db-chip-soft);
  font-size: 0.92rem;
}
.room-row.is-busy { opacity: 0.8; }
.room-check { display: flex; align-items: center; gap: 0.5rem; cursor: pointer; min-width: 7rem; }
.room-name { min-width: 7rem; color: var(--db-text-soft); }

.badge { font-size: 0.8rem; color: var(--db-text-soft); }
.badge-done { color: var(--db-accent-deep); font-weight: 600; }
.badge-running { color: var(--db-text); }
.badge-failed { color: var(--db-danger); }

.row-btn {
  margin-left: auto; padding: 0.25rem 0.8rem; border: 1px solid #dcdcdc; border-radius: var(--db-radius-pill);
  background: #fff; color: var(--db-text); font-size: 0.8rem; cursor: pointer;
}
.row-btn:hover:not(:disabled) { border-color: var(--db-accent); background: #f7f6f3; }
.row-btn:disabled { opacity: 0.5; cursor: not-allowed; }

.apply-actions { display: flex; flex-wrap: wrap; align-items: center; gap: 0.75rem; }
.estimate, .progress { font-size: 0.82rem; color: var(--db-text-soft); }
</style>
