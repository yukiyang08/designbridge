<script setup>
/**
 * Step: 房型設定（CAD 入口）— 輸入幾房幾廳幾衛幾廚幾陽台＋總坪數，交給
 * /api/generate-room-plan 直接切割整層樓的房間配置。表單沿用 RoomPlanView.vue
 * 那顆獨立工具頁的寫法，只是狀態換成 useDesignFlow 的 cadCounts/cadTotalPing，
 * 生成完後由 submitRoomProgram 自動導去下一步（選房間），不在這裡處理導頁。
 */
import { computed } from 'vue'
import { useDesignFlow } from '@/composables/useDesignFlow'

const { cadCounts, cadTotalPing, loading, submitRoomProgram, startFlow } = useDesignFlow()

const PING_TO_M2 = 3.305785

const COUNT_FIELDS = [
  { key: 'bedroom_count', label: '臥室' },
  { key: 'living_count', label: '客餐廳' },
  { key: 'bathroom_count', label: '衛浴' },
  { key: 'kitchen_count', label: '廚房' },
  { key: 'balcony_count', label: '陽台' },
]

const estimatedM2 = computed(() => (cadTotalPing.value || 0) * PING_TO_M2)

function setCount(key, delta) {
  cadCounts.value = { ...cadCounts.value, [key]: Math.max(0, Math.min(10, cadCounts.value[key] + delta)) }
}
</script>

<template>
  <div class="room-program-step">
    <div class="panel-head">
      <h2 class="panel-title">房型設定</h2>

      <!-- 這一步預設是「整層房屋」（CAD 房型切割）；點「單間」直接切到原本單房間
           2D 平面圖流程（StepSpaceSetup），不用先填整層房型再回頭選。 -->
      <div class="mode-toggle-wrap">
        <span class="mode-toggle-label">生成範圍</span>
        <div class="mode-toggle" role="group" aria-label="生成範圍">
          <button type="button" :disabled="loading" @click="startFlow('generate')">單間</button>
          <button type="button" class="active">整層房屋</button>
        </div>
      </div>
    </div>

    <p class="page-hint">輸入幾房幾廳＋總坪數，自動生成含牆體、門窗與尺寸標註的房間配置平面圖，下一步再選一間房進去編輯家具。</p>

    <div class="count-grid">
      <div v-for="f in COUNT_FIELDS" :key="f.key" class="count-row">
        <span class="count-label">{{ f.label }}</span>
        <div class="count-stepper">
          <button type="button" class="count-btn" @click="setCount(f.key, -1)">−</button>
          <span class="count-num">{{ cadCounts[f.key] }}</span>
          <button type="button" class="count-btn" @click="setCount(f.key, 1)">＋</button>
        </div>
      </div>
    </div>

    <div class="ping-main">
      <span class="ping-word-lg">總坪數 約</span>
      <input
        v-model.number="cadTotalPing"
        type="number" min="1" max="200" step="0.5"
        class="db-input ping-input-lg"
        aria-label="總坪數"
      />
      <span class="ping-word-lg">坪</span>
    </div>
    <p class="ping-hint">≈ {{ estimatedM2.toFixed(1) }} m²</p>

    <div class="actions">
      <button class="db-btn" :disabled="loading" @click="submitRoomProgram">生成房型配置</button>
    </div>

    <div class="alt-actions">
      <span class="alt-divider">或者</span>
      <button type="button" class="upload-card" :disabled="loading" @click="startFlow('upload')">
        <span class="upload-icon" aria-hidden="true">📐</span>
        <span class="upload-text">
          <span class="upload-title">上傳我自己的 CAD 平面配置圖</span>
          <span class="upload-desc">已有設計師的平面圖？直接上傳，AI 幫你辨識房間與家具</span>
        </span>
        <span class="upload-arrow" aria-hidden="true">→</span>
      </button>
    </div>
  </div>
</template>

<style scoped>
.room-program-step { display: flex; flex-direction: column; }

.panel-head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  margin-bottom: 1rem;
}
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

/* 單間／整層房屋——加大字級/圖示/邊框，跟其他次要控制項區分開，一眼看出這是
   可以切換的模式選擇，不是裝飾用的標籤。 */
.mode-toggle-wrap {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 0.35rem;
}
.mode-toggle-label {
  font-size: 0.78rem;
  font-weight: 600;
  letter-spacing: 0.02em;
  color: var(--db-text-soft);
}
.mode-toggle {
  display: inline-flex;
  padding: 4px;
  border: 1px solid #e2ddd0;
  border-radius: var(--db-radius-pill);
  background: var(--db-chip-soft);
  box-shadow: inset 0 1px 2px rgba(0, 0, 0, 0.04);
}
.mode-toggle button {
  padding: 0.55rem 1.3rem;
  border: none;
  border-radius: var(--db-radius-pill);
  background: none;
  color: var(--db-text-soft);
  font-family: var(--db-font-display);
  font-style: italic;
  font-weight: 500;
  font-size: 1rem;
  cursor: pointer;
  transition: background 0.16s, color 0.16s, box-shadow 0.16s;
}
.mode-toggle button:not(.active):hover { background: rgba(255, 255, 255, 0.7); color: var(--db-text); }
.mode-toggle button:disabled { opacity: 0.5; cursor: not-allowed; }
.mode-toggle button.active {
  background: var(--db-accent);
  color: var(--db-on-accent);
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.12);
  cursor: default;
}

.page-hint {
  margin: 0 0 1.75rem;
  text-align: center;
  color: var(--db-text-soft);
  font-size: 0.92rem;
}

.count-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 1rem;
  max-width: 720px;
  margin: 0 auto 1.75rem;
}
.count-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  padding: 0.6rem 1rem;
  border-radius: var(--db-radius-chip);
  background: var(--db-chip-soft);
}
.count-label {
  font-family: var(--db-font-display);
  font-style: italic;
  font-weight: 500;
  color: var(--db-text);
}
.count-stepper { display: flex; align-items: center; gap: 0.6rem; }
.count-btn {
  width: 28px; height: 28px;
  border: none; border-radius: 50%;
  background: #fff;
  color: var(--db-text);
  font-size: 1rem;
  line-height: 1;
  cursor: pointer;
}
.count-btn:hover { background: var(--db-accent); color: var(--db-on-accent); }
.count-num {
  min-width: 1.4em;
  text-align: center;
  font-variant-numeric: tabular-nums;
  font-size: 1.05rem;
}

.ping-main {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.7rem;
}
.ping-word-lg {
  font-family: var(--db-font-display);
  font-style: italic;
  font-size: 1.2rem;
  color: var(--db-text);
}
.ping-input-lg {
  width: 120px;
  height: 58px;
  border: 2px solid var(--db-chip);
  border-radius: 8px;
  background: #fff;
  text-align: center;
  font-size: 1.5rem;
  font-variant-numeric: tabular-nums;
}
.ping-input-lg:focus { border-color: var(--db-accent); background: #fff; }
.ping-hint {
  margin: 0.6rem 0 0;
  text-align: center;
  font-size: 0.85rem;
  color: var(--db-text-soft);
}

.actions {
  display: flex;
  justify-content: center;
  padding-top: 1.5rem;
}

.alt-actions {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.9rem;
  margin-top: 1.75rem;
  padding-top: 1.5rem;
  border-top: 1px solid #ececec;
}
.alt-divider {
  font-size: 0.8rem;
  color: var(--db-placeholder);
}

.upload-card {
  display: flex;
  align-items: center;
  gap: 1rem;
  width: 100%;
  max-width: 560px;
  padding: 1rem 1.25rem;
  border: 2px solid #dcdcdc;
  border-radius: var(--db-radius-card, 16px);
  background: #fff;
  text-align: left;
  cursor: pointer;
  transition: border-color 0.16s, background 0.16s, transform 0.12s;
}
.upload-card:hover {
  border-color: var(--db-accent);
  background: #fbfaf6;
  transform: translateY(-2px);
}
.upload-card:disabled { opacity: 0.5; cursor: not-allowed; transform: none; }

.upload-icon {
  flex-shrink: 0;
  display: grid;
  place-items: center;
  width: 44px;
  height: 44px;
  border-radius: 50%;
  background: var(--db-chip-soft);
  font-size: 1.4rem;
}
.upload-text {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
  min-width: 0;
}
.upload-title {
  font-family: var(--db-font-display);
  font-style: italic;
  font-weight: 500;
  font-size: 1.02rem;
  color: var(--db-text);
}
.upload-desc {
  font-size: 0.82rem;
  color: var(--db-text-soft);
  line-height: 1.4;
}
.upload-arrow {
  flex-shrink: 0;
  color: var(--db-accent-deep, var(--db-accent));
  font-size: 1.2rem;
}

@media (max-width: 640px) {
  .count-grid { grid-template-columns: 1fr; }
  .panel-head { justify-content: flex-start; }
  .mode-toggle-wrap { align-items: flex-start; width: 100%; }
  .mode-toggle { width: 100%; }
  .mode-toggle button { flex: 1; justify-content: center; }
  .upload-card { max-width: none; }
}
</style>
