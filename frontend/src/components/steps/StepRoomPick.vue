<script setup>
/**
 * Step: 選擇房間 — 兩條入口路徑共用同一個步驟 key（見 useDesignFlow 的
 * STEP_FLOWS）：
 *  · upload：上傳的平面圖偵測到多個房間才會經過這一步，底圖是點陣圖 + 歸一化座標框
 *  · cad：CAD 房型生成一定是多房間（整層樓），底圖是產生的 SVG，房間本身就是
 *    可點擊的 SVG 元素
 * 用 planSource 決定要哪一種 picker，兩邊各自的資料完全不同格式（見
 * RoomPicker.vue vs RoomPickerCad.vue 的 props）。
 */
import { useDesignFlow } from '@/composables/useDesignFlow'
import RoomPicker from '@/components/RoomPicker.vue'
import RoomPickerCad from '@/components/RoomPickerCad.vue'

const {
  planSource, detectedRooms, uploadedPlanUrl, handleRoomSelected,
  cadPlanResult, handleCadRoomSelected,
} = useDesignFlow()
</script>

<template>
  <div class="room-pick-step">
    <div class="panel-head">
      <h2 class="panel-title">選擇要生成的房間</h2>
    </div>

    <RoomPickerCad
      v-if="planSource === 'cad'"
      :svg-markup="cadPlanResult?.svg_markup || ''"
      :rooms="cadPlanResult?.rooms || []"
      @select-room="handleCadRoomSelected"
    />
    <RoomPicker
      v-else
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
