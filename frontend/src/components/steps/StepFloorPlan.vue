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
import { Icon } from '@iconify/vue'
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

const VIEW_MODES = [
  { key: '2d', num: '2D', label: '平面', icon: 'mdi:floor-plan' },
  { key: '3d', num: '3D', label: '立體', icon: 'mdi:cube-outline' },
]

function goNext() {
  scheduleSearch()
  nextStep()
}
</script>

<template>
  <div class="floor-plan-step">
    <!-- 2D／3D 切換放在畫布上方自成一列：兩種模式位置不變，也不會蓋到手機上橫向捲動的工具列 -->
    <div v-if="editPlacements.length" class="stage-head">
      <div class="view-toggle" role="radiogroup" aria-label="檢視模式">
        <button
          v-for="m in VIEW_MODES" :key="m.key" type="button" role="radio"
          :aria-checked="layoutViewMode === m.key" :class="{ active: layoutViewMode === m.key }"
          @click="layoutViewMode = m.key"
        >
          <Icon :icon="m.icon" width="18" aria-hidden="true" />
          {{ m.num }} {{ m.label }}
        </button>
      </div>
    </div>
    <div class="stage">
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
      />
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
      <button class="db-btn db-btn--ghost db-btn--sm" @click="prevStep">← 上一步</button>      <button class="db-btn" :disabled="loading" @click="goNext">
        <span class="label-full">下一步：生成渲染圖</span><span class="label-short">下一步</span>
      </button>
    </div>

  </div>
</template>

<style scoped>
.floor-plan-step { display: flex; flex-direction: column; }

.stage-head { display: flex; justify-content: flex-end; align-items: center; margin-bottom: 0.75rem; }
.view-toggle {
  display: inline-flex;
  padding: 3px;
  border: 1px solid var(--db-line);
  border-radius: var(--db-radius-pill);
  background: var(--db-chip-soft);
}
.view-toggle button {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  min-height: 40px;
  padding: 0 1.1rem 0 0.9rem;
  border: none;
  border-radius: var(--db-radius-pill);
  background: none;
  color: var(--db-text-soft);
  font-family: var(--db-font-body);
  font-size: 0.95rem;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.18s, color 0.18s, box-shadow 0.18s;
}
.view-toggle button:hover:not(.active) { color: var(--db-text); }
.view-toggle button.active {
  background: var(--db-ink);
  color: #fff;
  box-shadow: 0 2px 8px rgba(28, 24, 18, 0.18);
}
.view-toggle button:focus-visible { outline: 2px solid var(--db-accent-deep); outline-offset: 2px; }
.label-short { display: none; }
@media (max-width: 640px) {
  .label-full { display: none; }   /* 手機上整句會折成兩行 */
  .label-short { display: inline; }
  .view-toggle { display: flex; width: 100%; }
  .view-toggle button { flex: 1; justify-content: center; min-height: 44px; }
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
  color: var(--db-text-soft);
  font-size: 0.82rem;
}

/* ── 讓既有的 LayoutEditor 換上 Figma 的配色，不改動元件本身 ── */
.stage :deep(.node.selected) { border-color: var(--db-accent); }
</style>
