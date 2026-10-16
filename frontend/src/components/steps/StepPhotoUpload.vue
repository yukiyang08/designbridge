<script setup>
/**
 * Step 01（上傳照片路徑）空間照片上傳 — Figma MacBook Air - 16
 *
 * 照片會當成 /api/generate 的 initial_image_path：visual_preprocessing 抽視覺特徵、
 * requirement agent 把照片一起餵給 Gemini，所以不需要新的後端端點。
 */
import AdvancedPanel from '@/components/shell/AdvancedPanel.vue'
import FengshuiPicker from '@/components/FengshuiPicker.vue'
import StyleSuggestions from '@/components/StyleSuggestions.vue'
import { ROOM_OPTIONS } from '@/config/furniture'
import { useDesignFlow, ASPECT_OPTIONS } from '@/composables/useDesignFlow'
import { API_BASE } from '@/config/api'

const {
  spacePhoto, roomType, spaceSizePing, outputAspect, extraPrompt,
  fengshuiRules, loading, submitPhoto, scheduleSearch,
  showSuggestions, styleCandidates, candidatesLoading, candidatesError, confirmedStyle,
  confirmStyle, clearConfirmedStyle, fetchStyleCandidates, showNextRound,
} = useDesignFlow()
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

    <!-- 風水禁忌擺在主畫面，理由同 StepSpaceSetup.vue：硬約束不該藏在摺疊面板裡。
         這條路徑不排家具，規則走的是 prompt 通道（SKILL.md 的 prompt_addition）。 -->
    <FengshuiPicker
      v-model="fengshuiRules"
      :room-type="roomType"
      hint="這條路徑不排家具，勾選的項目會寫進生成效果圖的描述裡。"
    />

    <!-- ══ 描述需求：跟其他路徑一樣直接在這一頁打字、背景跑風格推薦，
         不用先點「下一步」翻頁才看得到結果。 ══ -->
    <section class="describe">
      <h2 class="db-col-title">描述你想要的空間</h2>
      <textarea
        v-model="extraPrompt"
        class="db-textarea"
        rows="3"
        placeholder="例如：木質感、採光充足的明亮感…"
        @input="scheduleSearch"
      />
      <p class="describe-hint">
        這段描述會用來搜尋風格參考圖，也會直接影響生成的效果圖。
      </p>

      <section v-if="showSuggestions" class="suggest">
        <StyleSuggestions
          :candidates="styleCandidates"
          :confirmed="confirmedStyle"
          :loading="candidatesLoading"
          :error="candidatesError"
          :api-base="API_BASE"
          @confirm="confirmStyle"
          @clear="clearConfirmedStyle"
          @next-round="showNextRound"
          @retry="fetchStyleCandidates()"
          @similar="fetchStyleCandidates({ anchorSelected: true })"
        />
      </section>
    </section>

    <AdvancedPanel hint="房型・坪數・比例">
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
      </div>
    </AdvancedPanel>

    <div class="actions">
      <button class="db-btn" :disabled="loading || !spacePhoto.preview" @click="submitPhoto">
        生成渲染圖
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
  font-style: normal;
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

/* ── 描述需求 ── */
.describe {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding-top: 1.75rem;
  border-top: 1px solid #f0f0f0;
}
.db-col-title {
  position: relative;
  margin: 0 0 1rem;
  padding-bottom: 0.7rem;
  font-family: var(--db-font-display);
  font-style: italic;
  font-weight: 500;
  font-size: 1.3rem;
  color: var(--db-text);
}
.db-col-title::after {
  content: '';
  position: absolute;
  left: 50%;
  bottom: 0;
  width: 34px;
  height: 3px;
  border-radius: 2px;
  background: var(--db-accent);
  transform: translateX(-50%);
}
.describe .db-textarea { max-width: 720px; width: 100%; }
.describe-hint {
  margin: 0.55rem 0 0;
  max-width: 720px;
  width: 100%;
  font-size: 0.8rem;
  color: var(--db-placeholder);
}
.suggest { width: 100%; margin-top: 1.5rem; }

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
