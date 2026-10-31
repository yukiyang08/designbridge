<script setup>
/**
 * Step 01（上傳 2D 平面配置圖路徑）
 *
 * 設計稿目前沒有指向這條路的入口卡，但後端 /api/parse-floor-plan 與流程邏輯都保留著。
 * 要重新開放：在 StartView 的 ENTRIES 補一筆 { source: 'upload', ... } 即可。
 */
import { computed, watch } from 'vue'
import AdvancedPanel from '@/components/shell/AdvancedPanel.vue'
import PlanParseIssue from '@/components/steps/PlanParseIssue.vue'
import { useDesignFlow, ASPECT_OPTIONS } from '@/composables/useDesignFlow'

const {
  floorPlanUpload, uploadTotalPing, customRoomW, customRoomD, outputAspect,
  loading, useUploadedPlan, planParseIssue,
} = useDesignFlow()

const pingValid = computed(() => uploadTotalPing.value >= 1 && uploadTotalPing.value <= 500)

// 換了一張圖，上一張的解析結果就不適用了
watch(() => floorPlanUpload.preview, () => { planParseIssue.value = null })
</script>

<template>
  <div class="plan-upload">
    <label v-if="!floorPlanUpload.preview" class="drop">
      <input type="file" accept="image/*" hidden @change="floorPlanUpload.onChange" />
      <span class="drop-icon">📐</span>
      <span class="drop-label">上傳 CAD 平面配置圖</span>
      <small class="drop-hint">AI 會辨識圖上的家具位置，之後可繼續拖曳微調</small>
    </label>

    <div v-else class="preview">
      <img :src="floorPlanUpload.preview" alt="已上傳的平面配置圖" />
      <button type="button" class="clear-btn" title="移除" @click="floorPlanUpload.remove()">✕</button>
    </div>

    <PlanParseIssue />

    <!-- 解析前先填總坪數：比例尺以它換算，單間圖則直接當該房坪數 -->
    <div class="ping-field">
      <label class="field-label" for="pu-total-ping">總坪數 <span class="req">*</span></label>
      <div class="ping-input">
        <input id="pu-total-ping" v-model.number="uploadTotalPing" type="number" min="1" max="500" step="0.5"
               class="db-input" placeholder="例如 28" />
        <span class="unit">坪</span>
      </div>
      <small class="ping-hint">整戶圖填整戶室內坪數，單一房間圖填該房間坪數</small>
    </div>

    <!-- 沒有「房間類型」：上傳的可能是整層平面圖，每間房的類型由 AI 辨識 -->
    <AdvancedPanel hint="長寬・比例">
      <div class="adv-grid">
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
      <button v-if="!planParseIssue" class="db-btn" :disabled="loading || !floorPlanUpload.preview || !pingValid" @click="useUploadedPlan">
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
  font-style: normal;
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

.ping-field { padding-top: 1.25rem; }
.ping-input { display: flex; align-items: center; gap: 0.5rem; max-width: 240px; }
.unit { color: var(--db-text-soft); }
.req { color: var(--db-accent); }
.ping-hint { display: block; margin-top: 0.4rem; color: var(--db-placeholder); font-size: 0.8rem; }

.actions { display: flex; justify-content: center; padding-top: 1.5rem; }
.actions .db-btn { min-width: 337px; }

@media (max-width: 900px) {
  .actions .db-btn { min-width: 0; width: 100%; }
}
</style>
