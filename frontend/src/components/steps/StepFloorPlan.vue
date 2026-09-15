<script setup>
/**
 * Step 02 繪製平面圖 — Figma MacBook Air - 11
 *
 * 與設計稿的差異（刻意保留的既有功能）：
 *  · 2D / 3D 切換：設計稿只畫了 2D 平面圖，但 LayoutPreview3D 可以把同一組家具座標
 *    直接顯示成可拖曳的 3D 模型，兩邊共用 editPlacements，是既有功能不能掉。
 *  · LayoutEditor 自帶的旋轉／刪除／縮放／復原／家具尺寸與房間尺寸面板一併保留。
 *  · 沒有「更新平面圖」按鈕：拖曳/加/刪/轉家具都會在鬆手 0.5 秒後自動重繪
 *    （debounce 在 useDesignFlow 的 onEditorChange 裡），不需要使用者自己按。
 *    submit3D 送出前也會補跑一次，確保用的是最新的平面圖。
 */
import { computed, defineAsyncComponent } from 'vue'
import LayoutEditor from '@/components/LayoutEditor.vue'
import { useDesignFlow } from '@/composables/useDesignFlow'

// three.js 約 700KB，只有切到 3D 才下載
const LayoutPreview3D = defineAsyncComponent(() => import('@/components/LayoutPreview3D.vue'))

const {
  editPlacements, roomW, roomD, roomTypeForPlan, layoutViewMode, layoutRenderConfig,
  floorPlanUrl, uploadedPlanUrl, onEditorChange,
  nextStep, scheduleSearch, loading,
} = useDesignFlow()

const editSceneGraph = computed(() => ({ furniture_placements: editPlacements.value }))
const editSpaceInfo = computed(() => ({
  estimated_size: { width: roomW.value, depth: roomD.value },
}))

function goNext() {
  scheduleSearch()
  nextStep()
}
</script>

<template>
  <div class="floor-plan-step">
    <div class="panel-head">
      <h2 class="panel-title">
        {{ layoutViewMode === '3d' ? '3D 佈局預覽' : '2D 平面配置圖' }}
      </h2>

      <div class="head-actions">
        <!-- 設計稿沒有這個切換，但 3D 佈局預覽是既有功能 -->
        <div v-if="editPlacements.length" class="view-toggle" role="group" aria-label="檢視模式">
          <button :class="{ active: layoutViewMode === '2d' }" @click="layoutViewMode = '2d'">2D模式</button>
          <button :class="{ active: layoutViewMode === '3d' }" @click="layoutViewMode = '3d'">3D模式</button>
        </div>
      </div>
    </div>

    <div class="stage">
      <LayoutEditor
        v-if="layoutViewMode === '2d'"
        :placements="editPlacements"
        v-model:room-w="roomW"
        v-model:room-d="roomD"
        :room-type="roomTypeForPlan"
        @update:placements="onEditorChange"
        @room-size-changed="onEditorChange(editPlacements)"
      />
      <LayoutPreview3D
        v-else
        :scene-graph="editSceneGraph"
        :render-config="layoutRenderConfig"
        :space-info="editSpaceInfo"
        editable
        @layout-changed="onEditorChange"
      />
    </div>

    <p v-if="!editPlacements.length" class="empty-hint">
      未辨識到家具座標，將以整張平面圖作為結構參考生成 3D 渲染圖。
    </p>

    <div class="refs">
      <details v-if="floorPlanUrl">
        <summary>檢視平面圖 PNG</summary>
        <img :src="floorPlanUrl" alt="2D 平面配置圖" class="ref-img" />
      </details>
      <details v-if="uploadedPlanUrl">
        <summary>對照原始上傳平面圖</summary>
        <img :src="uploadedPlanUrl" alt="原始上傳平面圖" class="ref-img" />
      </details>
    </div>

    <div class="actions">
      <button class="db-btn" :disabled="loading" @click="goNext">
        下一步：繼續生成 3D 渲染圖
      </button>
    </div>

    <p class="foot-hint">拖動調整家具位置，鬆手後平面圖會自動更新。</p>
  </div>
</template>

<style scoped>
.floor-plan-step { display: flex; flex-direction: column; }

.panel-head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 1rem;
  margin-bottom: 1rem;
}

/* 設計稿的「家具列表」標題列：#878181 底、白字 */
.panel-title {
  margin: 0;
  padding: 0.6rem 1.5rem;
  border-radius: 4px;
  background: var(--db-secondary-2);
  color: #fff;                     /* 底色是灰的，不吃 --db-on-accent */
  font-family: var(--db-font-display);
  font-style: italic;
  font-weight: 500;
  font-size: 1.25rem;
}

.head-actions {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  margin-left: auto;
}

.view-toggle {
  display: inline-flex;
  padding: 3px;
  border-radius: var(--db-radius-pill);
  background: var(--db-chip-soft);
}
.view-toggle button {
  padding: 0.4rem 1.05rem;
  border: none;
  border-radius: var(--db-radius-pill);
  background: none;
  color: var(--db-text-soft);
  font-family: var(--db-font-body);
  font-size: 0.9rem;
  cursor: pointer;
  transition: background 0.16s, color 0.16s;
}
.view-toggle button.active {
  background: var(--db-accent);
  color: var(--db-on-accent);
}

.stage { min-height: 430px; }

.empty-hint {
  margin: 0.75rem 0 0;
  color: var(--db-text-soft);
  font-size: 0.9rem;
}

.refs {
  display: flex;
  flex-wrap: wrap;
  gap: 1.25rem;
  margin-top: 1rem;
}
/* 原本 0.88rem 太不起眼，使用者常常沒發現這裡可以點開對照原圖 */
.refs summary {
  cursor: pointer;
  color: var(--db-text);
  font-family: var(--db-font-display);
  font-style: italic;
  font-weight: 500;
  font-size: 1.05rem;
}
.refs summary::marker { color: var(--db-accent); }
.refs summary:hover { color: var(--db-accent-deep); }
.ref-img {
  display: block;
  max-width: min(460px, 100%);
  margin-top: 0.6rem;
  border-radius: 8px;
  border: 1px solid #ececec;
}

.actions {
  display: flex;
  justify-content: center;
  gap: 1rem;
  padding-top: 1.5rem;
}

.foot-hint {
  margin: 0.85rem 0 0;
  text-align: center;
  color: var(--db-placeholder);
  font-size: 0.82rem;
}

/* ── 讓既有的 LayoutEditor 換上 Figma 的配色，不改動元件本身 ── */
.stage :deep(.palette-title) {
  background: var(--db-secondary-2);
  color: #fff;
  border-radius: 4px;
  padding: 0.4rem 0.75rem;
  font-family: var(--db-font-display);
  font-style: italic;
}
.stage :deep(.palette-item) {
  border-radius: var(--db-radius-chip);
  background: var(--db-chip-soft);
}
.stage :deep(.palette-item:hover) { background: var(--db-accent-soft); }
.stage :deep(.tool-btn.active),
.stage :deep(.node.selected) { border-color: var(--db-accent); }

@media (max-width: 900px) {
  .panel-head { flex-direction: column; align-items: stretch; }
  .head-actions { margin-left: 0; justify-content: space-between; }
  .actions { flex-direction: column; }
  .actions .db-btn { width: 100%; }
}
</style>
