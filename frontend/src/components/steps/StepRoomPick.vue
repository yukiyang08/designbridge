<script setup>
/**
 * Step: 選擇房間 — 只有上傳的平面圖偵測到多個房間時才會經過這一步
 * （見 useDesignFlow 的 useUploadedPlan：偵測到 ≤1 間就直接跳過）。
 */
import { useDesignFlow } from '@/composables/useDesignFlow'
import RoomPicker from '@/components/RoomPicker.vue'

const { detectedRooms, uploadedPlanUrl, handleRoomSelected } = useDesignFlow()
</script>

<template>
  <div class="room-pick-step">
    <div class="panel-head">
      <h2 class="panel-title">選擇要生成的房間</h2>
    </div>

    <RoomPicker
      :imageUrl="uploadedPlanUrl"
      :rooms="detectedRooms"
      @select-room="handleRoomSelected"
    />
  </div>
</template>

<style scoped>
.room-pick-step { display: flex; flex-direction: column; }

.panel-head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 1rem;
  margin-bottom: 1rem;
}

/* 跟 StepFloorPlan.vue 同一套面板標題列樣式，維持步驟之間視覺一致 */
.panel-title {
  margin: 0;
  padding: 0.6rem 1.5rem;
  border-radius: 4px;
  background: var(--db-secondary-2);
  color: #fff;
  font-family: var(--db-font-display);
  font-style: italic;
  font-weight: 500;
  font-size: 1.25rem;
}
</style>
