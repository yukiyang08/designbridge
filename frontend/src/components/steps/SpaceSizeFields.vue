<script setup>
/**
 * 空間大小：樣式與連動行為跟整層房屋（StepRoomProgram.vue）一致——
 * 總坪數與長寬連動：改坪數 → 依目前長寬比例重算長寬；改長或寬 → 重算坪數。
 *
 * 後端規則不變：customRoomW/D 兩者都有值才用長寬，否則用坪數換算（長寬比 5:4）。
 * 所以沒動過長寬時它們維持 null，畫面上顯示的是坪數換算值。
 */
import { computed } from 'vue'
import { useDesignFlow } from '@/composables/useDesignFlow'

defineProps({
  error: { type: String, default: '' },   // 由 StepSpaceSetup 的範圍檢查傳進來
})

const { spaceSizePing, customRoomW, customRoomD } = useDesignFlow()

const M2_PER_PING = 3.306   // 跟 api.py generate_layout 同一個換算
const r1 = (n) => Math.round(n * 10) / 10

// 坪數 → 長寬（長寬比 5:4，鏡射 api.py）
function sizeFromPing(ping, ratio = 1.25) {
  const m2 = (ping || 0) * M2_PER_PING
  if (m2 <= 0) return null
  const d = Math.sqrt(m2 / ratio)
  return { w: r1(d * ratio), d: r1(d) }
}

const derived = computed(() => sizeFromPing(spaceSizePing.value))
const shownW = computed(() => customRoomW.value ?? derived.value?.w ?? '')
const shownD = computed(() => customRoomD.value ?? derived.value?.d ?? '')
const m2 = computed(() => (spaceSizePing.value || 0) * M2_PER_PING)

const num = (e) => parseFloat(e.target.value)

function onPing(e) {
  const v = num(e)
  if (!(v > 0)) return
  spaceSizePing.value = v
  if (customRoomW.value > 0 && customRoomD.value > 0) {   // 已指定長寬：保持比例縮放
    const s = sizeFromPing(v, customRoomW.value / customRoomD.value)
    customRoomW.value = s.w
    customRoomD.value = s.d
  }
}
function onW(e) {
  const v = num(e)
  if (!(v > 0)) return
  const d = shownD.value
  customRoomW.value = v
  customRoomD.value = d
  spaceSizePing.value = r1((v * d) / M2_PER_PING)
}
function onD(e) {
  const v = num(e)
  if (!(v > 0)) return
  const w = shownW.value
  customRoomW.value = w
  customRoomD.value = v
  spaceSizePing.value = r1((w * v) / M2_PER_PING)
}

// 太狹長的房間家具很難排，只提醒不阻擋
const narrowWarn = computed(() => {
  const w = shownW.value, d = shownD.value
  if (!(w > 0 && d > 0)) return ''
  return Math.max(w, d) / Math.min(w, d) > 3 ? '房間偏狹長（長寬比超過 3:1），家具可能排不下' : ''
})
</script>

<template>
  <div class="size-block">
    <div class="ping-row">
      <label class="size-label" for="room-total-ping">總坪數 約</label>
      <input
        id="room-total-ping" :value="spaceSizePing" type="number"
        min="1" max="100" step="0.5" class="db-input size-input" @input="onPing"
      />
      <span class="size-unit">坪</span>
      <span class="ping-suffix">≈ {{ m2.toFixed(1) }} m²</span>
    </div>
    <div class="dim-fields">
      <label class="size-label" for="room-w">長</label>
      <input
        id="room-w" :value="shownW" type="number" min="1" max="30" step="0.1"
        class="db-input size-input" @input="onW"
      />
      <span class="dim-x" aria-hidden="true">×</span>
      <label class="size-label" for="room-d">寬</label>
      <input
        id="room-d" :value="shownD" type="number" min="1" max="30" step="0.1"
        class="db-input size-input" @input="onD"
      />
      <span class="size-unit">m</span>
    </div>
    <p v-if="error" class="size-error" role="alert">{{ error }}</p>
    <p v-else-if="narrowWarn" class="size-warn">{{ narrowWarn }}</p>
    <p v-else class="size-hint">改坪數會依目前的長寬比例調整長寬；改長或寬則會更新坪數。</p>
  </div>
</template>

<style scoped>
/* 跟 StepRoomProgram.vue 的 .size-block 同一套 */
.size-block { display: flex; flex-direction: column; gap: 0.6rem; width: 100%; }
.ping-row, .dim-fields { display: flex; align-items: center; flex-wrap: wrap; gap: 0.4rem 0.45rem; }
.size-label { font-size: 0.88rem; color: var(--db-text-soft); }
.size-input { width: 68px; height: 36px; padding: 0 0.3rem; text-align: center; font-size: 1rem; font-variant-numeric: tabular-nums; }
.size-unit { font-size: 0.88rem; color: var(--db-text-soft); }
.dim-x { color: var(--db-placeholder); }
.ping-suffix { font-size: 0.82rem; color: var(--db-placeholder); white-space: nowrap; }
.size-hint, .size-error, .size-warn { margin: 0; font-size: 0.76rem; line-height: 1.5; color: var(--db-placeholder); }
.size-error { color: var(--db-danger); }
.size-warn { color: #8a6a00; }
</style>
