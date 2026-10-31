<script setup>
import { computed } from 'vue'
import { ROOM_OPTIONS } from '../config/furniture.js'

const props = defineProps({
  imageUrl: { type: String, required: true },
  // [{id, room_type, x, y, w, h, label?, polygon?, anchor?}] normalized；
  // 有 polygon（後端依牆線切出的輪廓）就畫輪廓，否則退回畫外框
  rooms:    { type: Array,  required: true },
})
const emit = defineEmits(['select-room'])

const polyRooms = computed(() => props.rooms.filter(r => r.polygon?.length >= 3))
const boxRooms  = computed(() => props.rooms.filter(r => !(r.polygon?.length >= 3)))

function points(room) { return room.polygon.map(([x, y]) => `${x},${y}`).join(' ') }

function anchorStyle(room) {
  const [x, y] = room.anchor || [room.x + room.w / 2, room.y + room.h / 2]
  return { left: pct(x), top: pct(y) }
}

// 每間都可以點；不支援的房型由 handleRoomSelected 直接進空白家具配置
function pick(room) {
  emit('select-room', room)
}

function pct(v) { return `${v * 100}%` }

function boxStyle(room) {
  return { left: pct(room.x), top: pct(room.y), width: pct(room.w), height: pct(room.h) }
}

// 餐廳後端支援，但 9 月精簡房型時從 ROOM_OPTIONS 拿掉了，名稱另外補
const TYPE_LABELS = {
  ...Object.fromEntries(ROOM_OPTIONS.map(o => [o.value, o.label])),
  dining_room: '餐廳',
}
// 佈局引擎不支援、但認得出來的空間（後端 space_type），直接顯示名稱
const SPACE_LABELS = { bathroom: '浴室', balcony: '陽台', circulation: '玄關' }

// 名稱優先用圖上寫的房名，其次是房型名、浴室／陽台；都沒有就依序標房間1、房間2…
const labels = computed(() => {
  let n = 0
  const out = {}
  for (const room of props.rooms) {
    out[room.id] = room.label || TYPE_LABELS[room.room_type] || SPACE_LABELS[room.space_type] || `房間${++n}`
  }
  return out
})
const labelOf = room => labels.value[room.id]
</script>

<template>
  <div class="room-picker">
    <p class="hint">偵測到多個空間，點選要配置的房間</p>
    <div class="board">
      <img :src="imageUrl" class="plan-img" alt="平面圖" />
      <svg v-if="polyRooms.length" class="poly-layer" viewBox="0 0 1 1" preserveAspectRatio="none">
        <polygon
          v-for="room in polyRooms"
          :key="room.id"
          class="room-poly"
          :points="points(room)"
          vector-effect="non-scaling-stroke"
          @click="pick(room)"
        />
      </svg>
      <span
        v-for="room in polyRooms"
        :key="`${room.id}-label`"
        class="room-label room-label--anchored"
        :style="anchorStyle(room)"
      >{{ labelOf(room) }}</span>
      <div
        v-for="room in boxRooms"
        :key="room.id"
        class="room-box"
        :style="boxStyle(room)"
        @click="pick(room)"
      >
        <span class="room-label">{{ labelOf(room) }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.room-picker { display: flex; flex-direction: column; gap: 0.6rem; }

.hint { font-size: 0.85rem; color: var(--db-text-soft, #5a5a5a); margin: 0; }

.board {
  position: relative;
  width: 100%;
  border-radius: var(--db-radius-card, 20px);
  overflow: hidden;
  background: var(--db-card, #fff);
}

.plan-img { display: block; width: 100%; height: auto; }

.room-box {
  position: absolute;
  border: 2px solid var(--db-accent, #c9c4bb);
  background: color-mix(in srgb, var(--db-accent, #c9c4bb) 20%, transparent);
  cursor: pointer;
  display: flex;
  align-items: flex-start;
  justify-content: flex-start;
  transition: background 0.15s, border-color 0.15s;
}
.room-box:hover {
  background: color-mix(in srgb, var(--db-accent-soft, #e6e3dd) 70%, transparent);
  border-color: var(--db-accent-deep, #a39b94);
}


.room-label {
  font-size: 0.7rem;
  font-weight: 500;
  color: var(--db-text, #1a1a1a);
  background: var(--db-chip-soft, #efefef);
  padding: 0.15rem 0.5rem;
  border-radius: var(--db-radius-chip, 10px);
  margin: 0.3rem;
  white-space: nowrap;
  font-family: var(--db-font-body, inherit);
}

.poly-layer { position: absolute; inset: 0; width: 100%; height: 100%; }

.room-poly {
  fill: color-mix(in srgb, var(--db-accent, #c9c4bb) 20%, transparent);
  stroke: var(--db-accent, #c9c4bb);
  stroke-width: 2;
  cursor: pointer;
  transition: fill 0.15s, stroke 0.15s;
}
.room-poly:hover {
  fill: color-mix(in srgb, var(--db-accent-soft, #e6e3dd) 70%, transparent);
  stroke: var(--db-accent-deep, #a39b94);
}

/* 標籤疊在輪廓上方但不攔點擊，點標籤等於點房間 */
.room-label--anchored {
  position: absolute;
  transform: translate(-50%, -50%);
  margin: 0;
  pointer-events: none;
}
</style>
