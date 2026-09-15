<script setup>
/**
 * Step 微調編輯 — Figma MacBook Air - 19 / 21
 *
 * 左邊需求輸入 + 畫筆工具，右邊在渲染圖上塗抹遮罩。設計稿在畫筆與橡皮擦旁各畫了
 * 一條滑桿：上面那條對應筆刷大小，下面那條接到既有但先前沒有 UI 的 edit_scope
 * （改動幅度），讓這個實際會送進 API 的參數第一次可以被調整。
 */
import { computed } from 'vue'
import RefineCanvas from '@/components/RefineCanvas.vue'
import { useDesignFlow } from '@/composables/useDesignFlow'

const {
  textPrompt, brushSize, drawMode, editScope,
  spaceImage, baseImagePreview, refineCanvasRef,
  loading, submitRefine, nextStep, prevStep,
} = useDesignFlow()

const hasBase = computed(() => !!baseImagePreview.value)
</script>

<template>
  <div class="refine-step">
    <div class="cols">

      <!-- ── 左：需求 + 工具 ── -->
      <div class="panel">
        <label class="field-label" for="refine-prompt">輸入你的微調需求</label>
        <textarea
          id="refine-prompt"
          v-model="textPrompt"
          class="db-textarea"
          rows="4"
          placeholder="例如：把沙發換成藍色布藝款式、窗簾改為白色薄紗"
        />

        <h3 class="tool-title">用畫筆圈選微調範圍</h3>

        <div class="tool-row">
          <button
            type="button"
            :class="['tool-btn', { active: drawMode === 'draw' }]"
            @click="drawMode = 'draw'"
          >畫筆</button>
          <input
            v-model.number="brushSize"
            type="range" min="5" max="120" step="5"
            class="slider" aria-label="筆刷大小"
          />
          <span class="slider-val">{{ brushSize }}px</span>
        </div>

        <div class="tool-row">
          <button
            type="button"
            :class="['tool-btn', { active: drawMode === 'erase' }]"
            @click="drawMode = 'erase'"
          >橡皮擦</button>
          <input
            v-model.number="editScope"
            type="range" min="0.1" max="1" step="0.05"
            class="slider" aria-label="改動幅度"
          />
          <span class="slider-val">改動 {{ Math.round(editScope * 100) }}%</span>
        </div>

        <p class="tool-hint">
          不塗抹就整張重繪；塗抹後只重繪塗到的區域。改動幅度越高，AI 越敢偏離原圖。
        </p>

        <!-- 沒有基底圖時（例如直接從網址進到這一步）給一個上傳入口 -->
        <div v-if="!hasBase" class="fallback">
          <label class="field-label">先上傳一張要修改的空間圖</label>
          <label class="mini-drop">
            <input type="file" accept="image/*" hidden @change="spaceImage.onChange" />
            <span>點擊上傳</span>
          </label>
        </div>
      </div>

      <!-- ── 右：畫布 ── -->
      <div class="canvas-wrap">
        <RefineCanvas
          v-if="hasBase"
          ref="refineCanvasRef"
          :image-url="baseImagePreview"
          :brush-size="brushSize"
          :draw-mode="drawMode"
        />
        <div v-else class="canvas-empty">
          <span class="empty-icon">🖌️</span>
          <p>先在上一步生成一張渲染圖，或在左側上傳一張空間圖</p>
        </div>
      </div>
    </div>

    <div class="actions">
      <button class="db-btn db-btn--ghost db-btn--sm" @click="prevStep">← 上一步</button>
      <button class="db-btn db-btn--ghost" :disabled="loading || !hasBase" @click="submitRefine">
        生成新圖
      </button>
      <button class="db-btn" :disabled="!hasBase" @click="nextStep">
        完成：進入預算估計
      </button>
    </div>
  </div>
</template>

<style scoped>
.refine-step { display: flex; flex-direction: column; }

.cols {
  display: grid;
  grid-template-columns: minmax(260px, 340px) 1fr;
  gap: clamp(1.25rem, 3vw, 2.5rem);
  align-items: stretch;
}

.panel { min-width: 0; }

.field-label {
  display: block;
  margin-bottom: 0.45rem;
  font-size: 0.9rem;
  font-weight: 500;
  color: var(--db-text-soft);
}

.tool-title {
  margin: 1.5rem 0 0.85rem;
  font-family: var(--db-font-display);
  font-style: italic;
  font-weight: 500;
  font-size: 1.1rem;
  color: var(--db-text);
}

.tool-row {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  margin-bottom: 0.85rem;
}

.tool-btn {
  flex-shrink: 0;
  min-width: 92px;
  padding: 0.45rem 1rem;
  border: 2px solid transparent;
  border-radius: 4px;
  background: var(--db-secondary-2);
  color: #fff;                     /* 底色是灰的，不吃 --db-on-accent */
  font-family: var(--db-font-display);
  font-style: italic;
  font-size: 0.98rem;
  cursor: pointer;
  transition: background 0.16s, border-color 0.16s;
}
.tool-btn.active {
  background: var(--db-accent);
  border-color: var(--db-accent-deep);
  color: var(--db-on-accent);
}
.tool-btn:hover:not(.active) { background: #6f6a6a; }

.slider { flex: 1; min-width: 0; accent-color: var(--db-accent); }
.slider-val {
  flex-shrink: 0;
  min-width: 5.5em;
  font-size: 0.8rem;
  color: var(--db-text-soft);
  font-variant-numeric: tabular-nums;
}

.tool-hint {
  margin: 0.25rem 0 0;
  font-size: 0.8rem;
  line-height: 1.65;
  color: var(--db-placeholder);
}

.fallback { margin-top: 1.5rem; }
.mini-drop {
  display: grid;
  place-items: center;
  padding: 1.25rem;
  border: 2px dashed #d4d4d4;
  border-radius: 8px;
  background: var(--db-chip-soft);
  color: var(--db-text-soft);
  cursor: pointer;
}
.mini-drop:hover { border-color: var(--db-accent); }

/* 之前沒給高度：RefineCanvas 內部是 width/height:100%，父層沒有實際高度
   時整組畫布會塌縮成圖片的原始像素大小，遠比左欄小、佔不滿右半邊。
   這裡給一個跟畫面高度連動的高度，畫布才會真的填滿右側。 */
.canvas-wrap {
  min-width: 0;
  height: clamp(460px, 66vh, 720px);
}

.canvas-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 0.75rem;
  height: 100%;
  min-height: 380px;
  border-radius: 8px;
  background: var(--db-chip-soft);
  color: var(--db-text-soft);
  text-align: center;
  padding: 2rem;
}
.empty-icon { font-size: 2.5rem; }
.canvas-empty p { margin: 0; max-width: 32ch; line-height: 1.7; }

.actions {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 1rem;
  padding-top: 1.75rem;
}

@media (max-width: 900px) {
  .cols { grid-template-columns: 1fr; }
  .actions { flex-direction: column-reverse; }
  .actions .db-btn { width: 100%; }
}
</style>
