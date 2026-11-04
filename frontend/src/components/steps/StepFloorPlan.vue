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
 *  · 風水＋動線健檢跟著家具即時更新：家具座標在這一步定案，健檢在這裡排程；
 *    報告本身顯示在 StudioView 的右欄（全局資訊），不佔畫布下方的空間。
 */
import { computed, defineAsyncComponent, watch } from 'vue'
import LayoutEditor from '@/components/LayoutEditor.vue'
import { useDesignFlow } from '@/composables/useDesignFlow'

// three.js 約 700KB，只有切到 3D 才下載
const LayoutPreview3D = defineAsyncComponent(() => import('@/components/LayoutPreview3D.vue'))

const {
  editPlacements, roomW, roomD, roomTypeForPlan, roomGeometry, setOpeningEdit, layoutViewMode, layoutRenderConfig,
  floorPlanUrl, uploadedPlanUrl, onEditorChange,
  nextStep, prevStep, scheduleSearch, loading, planSource,
  fengshuiEnabled, fengshuiExcluded, fengshuiReport, fengshuiLastFix, fengshuiHighlight, scheduleFengshuiAudit,
} = useDesignFlow()

// 使用者自己動了家具，一鍵調整的「復原」就不該再蓋掉這些修改。
// 編輯器自動校正（把一鍵調整的結果推出門口範圍、拉回牆內緣）不算，否則調整完紀錄立刻消失。
function onUserEdit(next, meta) {
  if (!meta?.auto) fengshuiLastFix.value = null
  onEditorChange(next)
}

watch(
  [editPlacements, roomW, roomD, roomTypeForPlan, roomGeometry, fengshuiEnabled, fengshuiExcluded],
  () => scheduleFengshuiAudit(),
  { immediate: true, deep: true },
)

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
    <div class="stage">
      <!-- 2D／3D 切換固定浮在畫布區右上角：2D 時剛好落在編輯器工具列的右端（省一整排），
           3D 時在預覽的右上角——切換前後按鈕位置不變。2D 工具列右側留了同寬的空位，不會蓋到工具。 -->
      <div v-if="editPlacements.length" class="view-toggle" role="group" aria-label="檢視模式">
        <button :class="{ active: layoutViewMode === '2d' }" @click="layoutViewMode = '2d'">2D模式</button>
        <button :class="{ active: layoutViewMode === '3d' }" @click="layoutViewMode = '3d'">3D模式</button>
      </div>
      <LayoutEditor
        v-if="layoutViewMode === '2d'"
        :placements="editPlacements"
        v-model:room-w="roomW"
        v-model:room-d="roomD"
        :room-type="roomTypeForPlan"
        :geometry="roomGeometry"
        :facing="fengshuiReport?.facing || {}"
        :highlight="fengshuiHighlight"
        @opening-change="setOpeningEdit"
        @update:placements="onUserEdit"
        @room-size-changed="onUserEdit(editPlacements)"
      >
        <template v-if="editPlacements.length" #toolbar-end>
          <span class="toggle-room" aria-hidden="true"></span>
        </template>
      </LayoutEditor>
      <LayoutPreview3D
        v-else
        :scene-graph="editSceneGraph"
        :render-config="layoutRenderConfig"
        :space-info="editSpaceInfo"
        :geometry="roomGeometry"
        :facing="fengshuiReport?.facing || null"
        editable
        @layout-changed="onUserEdit"
      />
    </div>

    <p v-if="!editPlacements.length" class="empty-hint">
      未辨識到家具座標，將以整張平面圖作為結構參考生成渲染圖。
    </p>

    <div class="actions">
      <button class="db-btn db-btn--ghost db-btn--sm" @click="prevStep">← 上一步</button>
      <button class="db-btn" :disabled="loading" @click="goNext">
        下一步：生成渲染圖
      </button>
    </div>

  </div>
</template>

<style scoped>
.floor-plan-step { display: flex; flex-direction: column; }

.view-toggle {
  position: absolute;
  top: 1.3rem;      /* 落在編輯區工具列裡、上下置中（編輯區內距＋框線＋工具列內距） */
  right: 1.05rem;
  z-index: 10;
  display: inline-flex;
  padding: 4px;
  border-radius: var(--db-radius-pill);
  background: var(--db-chip-soft);
}
/* 工具列右端給浮在上面的 2D／3D 切換留位子（寬度 ≈ 兩顆按鈕＋內距） */
.toggle-room { display: block; width: 13.5rem; }
.view-toggle button {
  min-width: 76px;
  min-height: 44px;
  padding: 0.55rem 1.25rem;
  border: none;
  border-radius: var(--db-radius-pill);
  background: none;
  color: var(--db-text-soft);
  font-family: var(--db-font-body);
  font-size: 1rem;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.16s, color 0.16s;
}
.view-toggle button.active {
  background: var(--db-accent);
  color: var(--db-on-accent);
}

.stage { position: relative; min-height: 430px; }

.empty-hint {
  margin: 0.75rem 0 0;
  color: var(--db-text-soft);
  font-size: 0.9rem;
}

/* .actions（上一步靠左、下一步靠右、黏在視窗底）由 StudioView 統一排版，這裡不另外定義 */

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
</style>
