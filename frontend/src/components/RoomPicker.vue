<script setup>
import { ROOM_OPTIONS } from '../config/furniture.js'

const props = defineProps({
  imageUrl: { type: String, required: true },
  rooms:    { type: Array,  required: true }, // [{id, room_type, x, y, w, h}] normalized
})
defineEmits(['select-room'])

function pct(v) { return `${v * 100}%` }

function boxStyle(room) {
  return { left: pct(room.x), top: pct(room.y), width: pct(room.w), height: pct(room.h) }
}

function labelOf(roomType) {
  return ROOM_OPTIONS.find(o => o.value === roomType)?.label || '未支援的空間'
}
</script>

<template>
  <div class="room-picker">
    <p class="hint">偵測到多個空間，點選要生成渲染圖的房間</p>
    <div class="board">
      <img :src="imageUrl" class="plan-img" alt="平面圖" />
      <div
        v-for="room in props.rooms"
        :key="room.id"
        class="room-box"
        :class="{ disabled: room.room_type === 'other' }"
        :style="boxStyle(room)"
        @click="room.room_type !== 'other' && $emit('select-room', room)"
      >
        <span class="room-label">{{ labelOf(room.room_type) }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.room-picker { display: flex; flex-direction: column; gap: 0.6rem; }

.hint { font-size: 0.85rem; color: #a07850; margin: 0; }

.board {
  position: relative;
  width: 100%;
  border-radius: 8px;
  overflow: hidden;
  background: #fff;
}

.plan-img { display: block; width: 100%; height: auto; }

.room-box {
  position: absolute;
  border: 2px solid var(--primary, #c98a4b);
  background: rgba(201, 138, 75, 0.12);
  cursor: pointer;
  display: flex;
  align-items: flex-start;
  justify-content: flex-start;
  transition: background 0.15s, border-color 0.15s;
}
.room-box:hover {
  background: rgba(201, 138, 75, 0.28);
  border-color: #a86a30;
}

.room-box.disabled {
  cursor: not-allowed;
  border-color: #b8b8b8;
  background: rgba(120, 120, 120, 0.12);
}
.room-box.disabled:hover { background: rgba(120, 120, 120, 0.12); }

.room-label {
  font-size: 0.7rem;
  font-weight: 600;
  color: #5a3a1a;
  background: rgba(255, 255, 255, 0.85);
  padding: 0.1rem 0.35rem;
  border-radius: 4px;
  margin: 0.2rem;
  white-space: nowrap;
}
.room-box.disabled .room-label { color: #666; }
</style>
