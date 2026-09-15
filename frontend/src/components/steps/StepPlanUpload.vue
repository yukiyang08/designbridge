<script setup>
/**
 * Step 01（上傳 2D 平面配置圖路徑）
 *
 * 設計稿目前沒有指向這條路的入口卡，但後端 /api/parse-floor-plan 與流程邏輯都保留著。
 * 要重新開放：在 StartView 的 ENTRIES 補一筆 { source: 'upload', ... } 即可。
 */
import AdvancedPanel from '@/components/shell/AdvancedPanel.vue'
import { ROOM_OPTIONS } from '@/config/furniture'
import { useDesignFlow, ASPECT_OPTIONS } from '@/composables/useDesignFlow'

const {
  floorPlanUpload, roomType, spaceSizePing, customRoomW, customRoomD, outputAspect,
  loading, useUploadedPlan,
} = useDesignFlow()
</script>

<template>
  <div class="plan-upload">
    <label v-if="!floorPlanUpload.preview" class="drop">
      <input type="file" accept="image/*" hidden @change="floorPlanUpload.onChange" />
      <span class="drop-icon">📐</span>
      <span class="drop-label">上傳 2D 平面配置圖</span>
      <small class="drop-hint">AI 會辨識圖上的家具位置，之後可繼續拖曳微調</small>
    </label>

    <div v-else class="preview">
      <img :src="floorPlanUpload.preview" alt="已上傳的平面配置圖" />
      <button type="button" class="clear-btn" title="移除" @click="floorPlanUpload.remove()">✕</button>
    </div>

    <AdvancedPanel hint="房型・坪數・長寬・比例">
      <div class="adv-grid">
        <div class="adv-field">
          <label class="field-label" for="pu-room">房間類型</label>
          <select id="pu-room" v-model="roomType" class="db-input">
            <option v-for="opt in ROOM_OPTIONS" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
          </select>
        </div>
        <div class="adv-field">
          <label class="field-label" for="pu-ping">空間坪數</label>
          <input id="pu-ping" v-model.number="spaceSizePing" type="number" min="1" max="100" step="0.5" class="db-input" />
        </div>
        <div class="adv-field">
          <label class="field-label">自訂長寬（公尺，可留空）</label>
          <div class="pair">
            <input v-model.number="customRoomW" type="number" min="1" step="0.1" class="db-input" placeholder="長度" />
            <input v-model.number="customRoomD" type="number" min="1" step="0.1" class="db-input" placeholder="寬度" />
          </div>
        </div>
        <div class="adv-field">
          <label class="field-label" for="pu-aspect">輸出圖片長寬比</label>
          <select id="pu-aspect" v-model="outputAspect" class="db-input">
            <option v-for="opt in ASPECT_OPTIONS" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
          </select>
        </div>
      </div>
    </AdvancedPanel>

    <div class="actions">
      <button class="db-btn" :disabled="loading || !floorPlanUpload.preview" @click="useUploadedPlan">
        解析平面圖
      </button>
    </div>
  </div>
</template>

<style scoped>
.plan-upload { display: flex; flex-direction: column; }

.drop {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 0.6rem;
  min-height: 340px;
  border: 2px dashed #cfcfcf;
  border-radius: 8px;
  background: var(--db-chip);
  cursor: pointer;
  transition: background 0.16s, border-color 0.16s;
}
.drop:hover { background: #cfcfcf; border-color: var(--db-accent); }
.drop-icon { font-size: 2.5rem; }
.drop-label {
  font-family: var(--db-font-display);
  font-style: italic;
  font-size: 1.5rem;
  color: var(--db-text-soft);
}
.drop-hint { color: var(--db-placeholder); font-size: 0.85rem; }

.preview {
  position: relative;
  display: grid;
  place-items: center;
  min-height: 340px;
  background: var(--db-chip-soft);
  border-radius: 8px;
  overflow: hidden;
}
.preview img { max-width: 100%; max-height: 440px; object-fit: contain; }
.clear-btn {
  position: absolute; top: 0.75rem; right: 0.75rem;
  width: 32px; height: 32px;
  border: none; border-radius: 50%;
  background: rgba(0, 0, 0, 0.55); color: #fff; cursor: pointer;
}

.adv-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: 1.25rem 1.5rem;
}
.pair { display: grid; grid-template-columns: 1fr 1fr; gap: 0.5rem; }
.field-label {
  display: block; margin-bottom: 0.45rem;
  font-size: 0.88rem; font-weight: 500; color: var(--db-text-soft);
}

.actions { display: flex; justify-content: center; padding-top: 1.5rem; }
.actions .db-btn { min-width: 337px; }

@media (max-width: 900px) {
  .actions .db-btn { min-width: 0; width: 100%; }
}
</style>
