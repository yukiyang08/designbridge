<script setup>
/**
 * 空間大小：「用坪數估算」與「我知道長寬」擇一。
 *
 * 原本坪數與長寬雙向連動：填長會覆蓋寬、填寬又覆蓋長，改坪數長寬卻不動，
 * 兩邊很容易互相矛盾。改成擇一之後只有一組是輸入、另一組永遠是唯讀換算值，
 * 後端收到的 space_size_ping 與 room_w/room_d 就不會對不上。
 */
import { ref, computed } from 'vue'
import { useDesignFlow } from '@/composables/useDesignFlow'

defineProps({
  error: { type: String, default: '' },   // 由 StepSpaceSetup 的範圍檢查傳進來
})

const { spaceSizePing, customRoomW, customRoomD } = useDesignFlow()

const M2_PER_PING = 3.306   // 跟 api.py generate_layout 同一個換算
const mode = ref(customRoomW.value && customRoomD.value ? 'dims' : 'ping')

// 坪數 → 長寬（長寬比 5:4，鏡射 api.py）
function sizeFromPing(ping) {
  const m2 = (ping || 0) * M2_PER_PING
  if (m2 <= 0) return null
  return {
    w: Math.round(Math.sqrt(m2 * 5 / 4) * 10) / 10,
    d: Math.round(Math.sqrt(m2 * 4 / 5) * 10) / 10,
  }
}

function setMode(next) {
  if (next === mode.value) return
  if (next === 'dims') {
    // 從目前的坪數估算帶入，使用者接著微調，不用從空白開始
    const s = sizeFromPing(spaceSizePing.value)
    customRoomW.value = s?.w ?? null
    customRoomD.value = s?.d ?? null
  } else {
    customRoomW.value = null
    customRoomD.value = null
  }
  mode.value = next
}

// 只在使用者真的輸入長寬時才回寫坪數；切換模式不經過這裡，坪數不會因四捨五入漂移
function onDimsInput() {
  const { value: w } = customRoomW
  const { value: d } = customRoomD
  if (w > 0 && d > 0) spaceSizePing.value = Math.round((w * d / M2_PER_PING) * 10) / 10
}

const derived = computed(() => (mode.value === 'ping' ? sizeFromPing(spaceSizePing.value) : null))

// 太狹長的房間家具很難排，只提醒不阻擋
const narrowWarn = computed(() => {
  const w = mode.value === 'dims' ? customRoomW.value : derived.value?.w
  const d = mode.value === 'dims' ? customRoomD.value : derived.value?.d
  if (!(w > 0 && d > 0)) return ''
  return Math.max(w, d) / Math.min(w, d) > 3 ? '房間偏狹長（長寬比超過 3:1），家具可能排不下' : ''
})
</script>

<template>
  <div class="size-fields">
    <div class="size-mode" role="group" aria-label="空間大小輸入方式">
      <button type="button" :class="{ active: mode === 'ping' }" :aria-pressed="mode === 'ping'" @click="setMode('ping')">用坪數估算</button>
      <button type="button" :class="{ active: mode === 'dims' }" :aria-pressed="mode === 'dims'" @click="setMode('dims')">我知道長寬</button>
    </div>

    <template v-if="mode === 'ping'">
      <div class="ping-main">
        <span class="ping-word-lg">約</span>
        <input
          v-model.number="spaceSizePing"
          type="number" min="1" max="100" step="0.5"
          class="db-input ping-input-lg"
          aria-label="空間坪數"
        />
        <span class="ping-word-lg">坪</span>
      </div>
      <p class="size-hint">≈ {{ Math.round((spaceSizePing || 0) * M2_PER_PING) }} m²</p>
      <div v-if="derived" class="size-readout">
        <span class="readout-label">換算約</span>
        <span class="readout-val">{{ derived.w }} × {{ derived.d }} <small>公尺</small></span>
      </div>
    </template>

    <template v-else>
      <div class="size-wd">
        <input
          v-model.number="customRoomW" type="number" min="1" max="30" step="0.1"
          class="db-input" placeholder="長 (m)" aria-label="房間長度（公尺）" @input="onDimsInput"
        />
        <span class="size-x">×</span>
        <input
          v-model.number="customRoomD" type="number" min="1" max="30" step="0.1"
          class="db-input" placeholder="寬 (m)" aria-label="房間寬度（公尺）" @input="onDimsInput"
        />
      </div>
      <div class="size-readout">
        <span class="readout-label">換算約</span>
        <span class="readout-val">{{ spaceSizePing }} <small>坪</small></span>
      </div>
    </template>

    <p v-if="error" class="size-msg size-error" role="alert">{{ error }}</p>
    <p v-else-if="narrowWarn" class="size-msg size-warn">{{ narrowWarn }}</p>
  </div>
</template>

<style scoped>
.size-fields { display: flex; flex-direction: column; align-items: center; width: 100%; }

.size-mode {
  display: inline-flex;
  padding: 3px;
  margin-bottom: 1rem;
  border: 1px solid #e2ddd0;
  border-radius: var(--db-radius-pill);
  background: var(--db-chip-soft);
}
.size-mode button {
  padding: 0.35rem 0.9rem;
  border: none;
  border-radius: var(--db-radius-pill);
  background: none;
  color: var(--db-text-soft);
  font-family: var(--db-font-body);
  font-size: 0.85rem;
  cursor: pointer;
  transition: background 0.16s, color 0.16s;
}
.size-mode button:not(.active):hover { background: rgba(255, 255, 255, 0.7); color: var(--db-text); }
.size-mode button.active { background: var(--db-accent); color: var(--db-on-accent); cursor: default; }

.ping-main { display: flex; align-items: center; justify-content: center; gap: 0.7rem; }
.ping-word-lg {
  font-family: var(--db-font-display);
  font-style: normal;
  font-size: 1.4rem;
  color: var(--db-text);
}
/* 白底 + 外框，看起來才像可以打字的欄位 */
.ping-input-lg {
  width: 120px;
  height: 58px;
  border: 2px solid var(--db-chip);
  border-radius: 8px;
  background: #fff;
  text-align: center;
  font-size: 1.5rem;
  font-variant-numeric: tabular-nums;
}
.ping-input-lg:focus { border-color: var(--db-accent); background: #fff; }

.size-wd { display: flex; align-items: center; gap: 0.5rem; width: 100%; }
.size-wd .db-input { min-width: 0; text-align: center; }
.size-x { color: var(--db-text-soft); }

.size-hint { margin: 0.6rem 0 0; font-size: 0.85rem; color: var(--db-text-soft); }

.size-readout {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.25rem;
  margin-top: 1.1rem;
  padding: 0.7rem 1rem;
  border-radius: var(--db-radius-chip);
  background: var(--db-chip-soft);
}
.readout-label { font-size: 0.75rem; color: var(--db-text-soft); }
.readout-val {
  font-family: var(--db-font-display);
  font-size: 1.1rem;
  color: var(--db-text);
  font-variant-numeric: tabular-nums;
}
.readout-val small { font-size: 0.78rem; color: var(--db-text-soft); }

.size-msg { margin: 0.7rem 0 0; font-size: 0.82rem; text-align: center; }
.size-error { color: var(--db-danger); }
.size-warn { color: #8a6a00; }
</style>
