<script setup>
/**
 * Step: 選擇房間 — upload 入口專用：上傳的平面圖偵測到多個房間才會經過這一步，
 * 底圖是點陣圖 + 歸一化座標框（見 RoomPicker.vue 的 props）。
 *
 * cad 入口原本也共用這個 key，現已併入 StepRoomProgram（房型設定生成完後，
 * 房間選擇器直接在同一頁展開，不再跳到這裡）。
 */
import { useDesignFlow } from '@/composables/useDesignFlow'
import RoomPicker from '@/components/RoomPicker.vue'

const { detectedRooms, uploadedPlanUrl, handleRoomSelected, prevStep } = useDesignFlow()
</script>

<template>
  <div class="room-pick-step">
    <div class="panel-head">
      <h2 class="panel-title">選擇要生成的房間</h2>
    </div>

    <RoomPicker :imageUrl="uploadedPlanUrl" :rooms="detectedRooms" @select-room="handleRoomSelected" />

    <div class="actions">
      <button class="db-btn db-btn--ghost db-btn--sm" @click="prevStep">← 上一步</button>
    </div>
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

.actions {
  display: flex;
  justify-content: center;
  padding-top: 1.5rem;
}

@media (max-width: 900px) {
  .actions .db-btn { width: 100%; }
}
</style>
