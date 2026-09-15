<script setup>
/**
 * Step 01（上傳照片路徑）空間照片上傳 — Figma MacBook Air - 16
 *
 * 照片會當成 /api/generate 的 initial_image_path：visual_preprocessing 抽視覺特徵、
 * requirement agent 把照片一起餵給 Gemini，所以不需要新的後端端點。
 */
import AdvancedPanel from '@/components/shell/AdvancedPanel.vue'
import { ROOM_OPTIONS } from '@/config/furniture'
import { useDesignFlow, ASPECT_OPTIONS, FAMILY_OPTIONS, FENGSHUI_OPTIONS } from '@/composables/useDesignFlow'

const {
  spacePhoto, roomType, spaceSizePing, outputAspect,
  familyNeeds, fengshuiRules, loading, submitPhoto,
} = useDesignFlow()

function toggleIn(listRef, value) {
  listRef.value = listRef.value.includes(value)
    ? listRef.value.filter(v => v !== value)
    : [...listRef.value, value]
}
</script>

<template>
  <div class="photo-step">
    <label v-if="!spacePhoto.preview" class="drop">
      <input type="file" accept="image/*" hidden @change="spacePhoto.onChange" />
      <span class="drop-icon">📷</span>
      <span class="drop-label">點擊上傳</span>
      <small class="drop-hint">拍一張空間現況照，JPG、PNG、WebP</small>
    </label>

    <div v-else class="preview">
      <img :src="spacePhoto.preview" alt="已上傳的空間照片" />
      <button type="button" class="clear-btn" title="移除" @click="spacePhoto.remove()">✕</button>
    </div>

    <AdvancedPanel hint="房型・坪數・比例・家庭結構・風水">
      <div class="adv-grid">
        <div class="adv-field">
          <label class="field-label" for="photo-room">房間類型</label>
          <select id="photo-room" v-model="roomType" class="db-input">
            <option v-for="opt in ROOM_OPTIONS" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
          </select>
        </div>

        <div class="adv-field">
          <label class="field-label" for="photo-ping">空間坪數</label>
          <input id="photo-ping" v-model.number="spaceSizePing" type="number" min="1" max="100" step="0.5" class="db-input" />
        </div>

        <div class="adv-field">
          <label class="field-label" for="photo-aspect">輸出圖片長寬比</label>
          <select id="photo-aspect" v-model="outputAspect" class="db-input">
            <option v-for="opt in ASPECT_OPTIONS" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
          </select>
        </div>

        <div class="adv-field">
          <label class="field-label">家庭結構</label>
          <div class="chip-row">
            <button
              v-for="opt in FAMILY_OPTIONS" :key="opt.value" type="button"
              :class="['db-chip', { 'is-active': familyNeeds.includes(opt.value) }]"
              @click="toggleIn(familyNeeds, opt.value)"
            >{{ opt.label }}</button>
          </div>
        </div>

        <div class="adv-field">
          <label class="field-label">風水需求</label>
          <div class="chip-row">
            <button
              v-for="opt in FENGSHUI_OPTIONS" :key="opt.value" type="button"
              :class="['db-chip', { 'is-active': fengshuiRules.includes(opt.value) }]"
              @click="toggleIn(fengshuiRules, opt.value)"
            >{{ opt.label }}</button>
          </div>
        </div>
      </div>
    </AdvancedPanel>

    <div class="actions">
      <button class="db-btn" :disabled="loading || !spacePhoto.preview" @click="submitPhoto">
        下一步：輸入需求
      </button>
    </div>
  </div>
</template>

<style scoped>
.photo-step { display: flex; flex-direction: column; }

.drop {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 0.6rem;
  min-height: 360px;
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
  font-size: 1.6rem;
  color: var(--db-text-soft);
}
.drop-hint { color: var(--db-placeholder); font-size: 0.85rem; }

.preview {
  position: relative;
  display: grid;
  place-items: center;
  min-height: 360px;
  background: var(--db-chip-soft);
  border-radius: 8px;
  overflow: hidden;
}
.preview img {
  max-width: 100%;
  max-height: 460px;
  object-fit: contain;
}
.clear-btn {
  position: absolute;
  top: 0.75rem;
  right: 0.75rem;
  width: 32px;
  height: 32px;
  border: none;
  border-radius: 50%;
  background: rgba(0, 0, 0, 0.55);
  color: #fff;
  cursor: pointer;
}
.clear-btn:hover { background: rgba(0, 0, 0, 0.75); }

.adv-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: 1.25rem 1.5rem;
}
.field-label {
  display: block;
  margin-bottom: 0.45rem;
  font-size: 0.88rem;
  font-weight: 500;
  color: var(--db-text-soft);
}
.chip-row { display: flex; flex-wrap: wrap; gap: 0.5rem; }
.chip-row .db-chip { font-size: 0.92rem; padding: 0.4rem 0.9rem; }

.actions { display: flex; justify-content: center; padding-top: 1.5rem; }
.actions .db-btn { min-width: 337px; }

@media (max-width: 900px) {
  .actions .db-btn { min-width: 0; width: 100%; }
}
</style>
