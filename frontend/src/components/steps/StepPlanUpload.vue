<script setup>
import { Icon } from '@iconify/vue'
/**
 * Step 01（上傳 2D 平面配置圖路徑）
 *
 * 設計稿目前沒有指向這條路的入口卡，但後端 /api/parse-floor-plan 與流程邏輯都保留著。
 * 要重新開放：在 StartView 的 ENTRIES 補一筆 { source: 'upload', ... } 即可。
 */
import { computed, ref, watch } from 'vue'
import ModeBackButton from '@/components/shell/ModeBackButton.vue'
import PlanParseIssue from '@/components/steps/PlanParseIssue.vue'
import { useDesignFlow } from '@/composables/useDesignFlow'

const {
  floorPlanUpload, uploadTotalPing, loading, useUploadedPlan, planParseIssue,
} = useDesignFlow()

const pingValid = computed(() => uploadTotalPing.value >= 1 && uploadTotalPing.value <= 500)

// 換了一張圖，上一張的解析結果就不適用了
watch(() => floorPlanUpload.preview, () => { planParseIssue.value = null })

// 跟後端 _IMAGE_SUFFIXES、_MAX_UPLOAD_BYTES、floorplan_quality._MIN_SIDE 同步：選圖當下就擋，不用等上傳完
const ACCEPT = '.png,.jpg,.jpeg,.webp,.gif,.bmp'
const MAX_BYTES = 20 * 1024 * 1024
const MIN_SIDE = 300
const fileInput = ref(null)

async function checkFile(file) {
  const ext = file.name.slice(file.name.lastIndexOf('.')).toLowerCase()
  if (!ACCEPT.split(',').includes(ext)) return `不支援 ${ext} 格式，請用 PNG、JPG 或 WebP`
  if (file.size > MAX_BYTES) return '圖片太大（上限 20 MB）'
  try {
    const bmp = await createImageBitmap(file)
    const side = Math.min(bmp.width, bmp.height)
    bmp.close()
    if (side < MIN_SIDE) return `圖片解析度太低（短邊 ${side}px，至少要 ${MIN_SIDE}px），請上傳更清楚的平面圖`
  } catch {
    return '無法讀取這張圖片，請換一張'
  }
  return ''
}

async function onPick(e) {
  const file = e.target.files[0]
  e.target.value = ''   // 清掉才能再選同一個檔案
  if (!file) return
  const issue = await checkFile(file)
  if (issue) {
    planParseIssue.value = { kind: 'quality', reason: issue }
    return
  }
  floorPlanUpload.setFile(file)
}
</script>

<template>
  <div class="plan-upload">
    <!-- 用 sr-only 不用 hidden：hidden 的 input 鍵盤 Tab 不到 -->
    <input
      id="pu-file" ref="fileInput" type="file" :accept="ACCEPT" class="sr-only"
      aria-describedby="pu-file-req" @change="onPick"
    />
    <label v-if="!floorPlanUpload.preview" for="pu-file" class="drop">
      <Icon icon="mdi:floor-plan" class="drop-icon" aria-hidden="true" />
      <span class="drop-label">上傳 CAD 平面配置圖</span>
      <small class="drop-hint">AI 會辨識圖上的家具位置，之後可繼續拖曳微調</small>
      <small id="pu-file-req" class="drop-req">
        俯視平面圖・線條清楚・短邊至少 {{ MIN_SIDE }}px<br />室內照片、3D 透視圖無法辨識
      </small>
    </label>

    <div v-else class="preview">
      <img :src="floorPlanUpload.preview" alt="已上傳的平面配置圖" />
      <div class="preview-actions">
        <button type="button" class="db-btn db-btn--ghost db-btn--sm swap-btn" @click="fileInput.click()">換一張圖</button>
        <button type="button" class="clear-btn" aria-label="移除圖片" title="移除圖片" @click="floorPlanUpload.remove()"><Icon icon="mdi:close" aria-hidden="true" /></button>
      </div>
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

    <!-- 不放進階設定：輸出比例在結果頁調，房間長寬在繪製平面圖那步調；這裡只要決定比例尺的坪數 -->

    <div class="actions">
      <ModeBackButton />
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
  border: 2px dashed var(--db-accent);
  border-radius: 8px;
  background: var(--db-chip);
  cursor: pointer;
  transition: background 0.16s, border-color 0.16s;
}
.drop:hover { background: var(--db-accent-soft); border-color: var(--db-accent); }
.sr-only:focus-visible + .drop { outline: 2px solid var(--db-accent); outline-offset: 3px; }
.sr-only { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; }
.drop-icon { font-size: 2.5rem; }
.drop-label {
  font-family: var(--db-font-display);
  font-style: normal;
  font-size: 1.5rem;
  color: var(--db-text-soft);
}
.drop-hint { color: var(--db-text-soft); font-size: 0.85rem; }
.drop-req { color: var(--db-text-soft); font-size: 0.8rem; line-height: 1.6; text-align: center; }

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
.preview-actions {
  position: absolute; top: 0.75rem; right: 0.75rem;
  display: flex; align-items: center; gap: 0.5rem;
}
.swap-btn { background: rgba(255, 255, 255, 0.92); }
.clear-btn {
  width: 44px; height: 44px;
  border: none; border-radius: 50%;
  background: rgba(0, 0, 0, 0.55); color: #fff; cursor: pointer;
}
.clear-btn:focus-visible, .swap-btn:focus-visible { outline: 2px solid var(--db-accent); outline-offset: 2px; }

.field-label {
  display: block; margin-bottom: 0.45rem;
  font-size: 0.88rem; font-weight: 500; color: var(--db-text-soft);
}

.ping-field { padding-top: 1.25rem; }
.ping-input { display: flex; align-items: center; gap: 0.5rem; max-width: 240px; }
.unit { color: var(--db-text-soft); }
.req { color: var(--db-accent); }
.ping-hint { display: block; margin-top: 0.4rem; color: var(--db-text-soft); font-size: 0.8rem; }

.actions { display: flex; justify-content: center; padding-top: 1.5rem; }
.actions .db-btn { min-width: 337px; }

@media (max-width: 900px) {
  .actions .db-btn { min-width: 0; width: 100%; }
}
</style>
