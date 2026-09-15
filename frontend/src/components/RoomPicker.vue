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
  border: 2px solid var(--db-accent, #cdc5ac);
  background: color-mix(in srgb, var(--db-accent, #cdc5ac) 20%, transparent);
  cursor: pointer;
  display: flex;
  align-items: flex-start;
  justify-content: flex-start;
  transition: background 0.15s, border-color 0.15s;
}
.room-box:hover {
  background: color-mix(in srgb, var(--db-accent-soft, #e4dfd0) 70%, transparent);
  border-color: var(--db-accent-deep, #b7ad8c);
}

.room-box.disabled {
  cursor: not-allowed;
  border-color: var(--db-muted, #c2c1c1);
  background: color-mix(in srgb, var(--db-muted, #c2c1c1) 20%, transparent);
}
.room-box.disabled:hover { background: color-mix(in srgb, var(--db-muted, #c2c1c1) 20%, transparent); }

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
.room-box.disabled .room-label { color: var(--db-placeholder, #b2b2b2); }
</style>
