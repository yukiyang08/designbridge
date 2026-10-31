<script setup>
/**
 * 線性精靈外殼（Figma frame 10/11/13/15/18/19/20 共用的版面）：
 * 滿版背景 → 導覽列 → 流程列 → 置中白卡，白卡內容由當前步驟決定。
 */
import { computed, onMounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { jsonFetch } from '@/config/api'
import AppNav from '@/components/shell/AppNav.vue'
import StepBar from '@/components/shell/StepBar.vue'
import LoadingState from '@/components/shell/LoadingState.vue'
import StepSpaceSetup from '@/components/steps/StepSpaceSetup.vue'
import StepPhotoUpload from '@/components/steps/StepPhotoUpload.vue'
import StepPlanUpload from '@/components/steps/StepPlanUpload.vue'
import StepRoomProgram from '@/components/steps/StepRoomProgram.vue'
import StepRoomPick from '@/components/steps/StepRoomPick.vue'
import StepFloorPlan from '@/components/steps/StepFloorPlan.vue'
import StepResult from '@/components/steps/StepResult.vue'
import CadRoomMiniMap from '@/components/CadRoomMiniMap.vue'
import CadOverview from '@/components/CadOverview.vue'
import { useDesignFlow, ASPECT_OPTIONS } from '@/composables/useDesignFlow'
import sceneBg from '@/assets/figma/room-bg.png'

const router = useRouter()
const flow = useDesignFlow()
const {
  steps, stepIndex, currentStep, goStep,
  loading, loadingMsg, error,
  editPlacements, floorPlanUrl, spacePhotoPath, planSource,
  detectedRooms, cadPlanResult, cadRoomStatus, cadActiveRoomId, jumpToCadRoom, abandonCadRoom,
  cadBatch, cadBatchRunning, applyToRooms, cancelCadBatch,
  cadRoomSnapshots, cadRendering, planSource: flowPlanSource, confirmedStyle, result, outputAspect, extraPrompt,
  fengshuiRules, cadOverview,
  fetchStyleOptions, fetchStyleDemoImages, resetFlow,
} = flow

// 右上角縮圖只在 CAD 多房間流程、且已經進到逐一設計房間（plan 之後）的步驟才顯示——
// roomProgram 本身就是整層/選房間的畫面，不需要再疊一個縮圖。
// 整層套用的接片用：每間房渲染完成的縮圖，以及「沿用了哪些設定」的說明
const batchThumbs = computed(() => Object.fromEntries(
  Object.entries(cadRoomSnapshots.value || {})
    .map(([id, snap]) => [id, snap?.lastGeneratedImage?.url || ''])
    .filter(([, url]) => url),
))
const batchSettings = computed(() => {
  const prompt = (extraPrompt.value || '').trim()
  return [
    `風格：${confirmedStyle.value?.style_name || result.value?.style_params?.style_profile_id || '自動'}`,
    `比例：${ASPECT_OPTIONS.find(o => o.value === outputAspect.value)?.label || outputAspect.value}`,
    prompt ? `描述：${prompt.slice(0, 16)}${prompt.length > 16 ? '…' : ''}` : '',
  ].filter(Boolean)
})

// 整層逐間設計的渲染是每間房各自的背景工作：只有「目前正在看的這間」還在渲染才蓋載入畫面，
// 切去別間就不會被卡住（見 render.js 的 submit3D）。
const activeRendering = computed(() =>
  flowPlanSource.value === 'cad' && !!cadActiveRoomId.value && !!cadRendering.value[cadActiveRoomId.value])

const MINIMAP_STEPS = new Set(['plan', 'result'])
// 有生成結果、右側要留給家具清單時，縮圖才改成頂部細列（要看平面圖按「放大平面圖」）；
// 還沒生成或正在渲染時維持右側縮圖
const showOverview = computed(
  () => planSource.value === 'cad' && cadOverview.value && currentStep.value === 'result',
)
const openOverview = () => { cadOverview.value = true }
// 批次生成跑完、而且整層都完成了：自動帶到總覽（只在批次剛結束時；重新載入已完成的進度不會跳）
watch(cadBatchRunning, (running, was) => {
  if (!was || running || currentStep.value !== 'result' || planSource.value !== 'cad') return
  const rooms = cadPlanResult.value?.rooms || []
  if (rooms.length && rooms.every(r => cadRoomStatus.value[r.id] === 'done')) cadOverview.value = true
})
const minimapCompact = computed(() => currentStep.value === 'result' && !!result.value)
const showCadMiniMap = computed(
  () => planSource.value === 'cad' && !!cadPlanResult.value && MINIMAP_STEPS.has(currentStep.value),
)

// 三個入口模式選錯了想換一個，只有在第一步才需要——後面幾步已經有資料，
// 「上一步」在流程列裡點就好，不用再提供這顆。
function backToModeSelect() {
  resetFlow()
  router.push('/start')
}

const STEP_COMPONENTS = {
  space:       StepSpaceSetup,
  photo:       StepPhotoUpload,
  planUpload:  StepPlanUpload,
  roomProgram: StepRoomProgram,
  roomPick:    StepRoomPick,
  plan:        StepFloorPlan,
  result:      StepResult,
}

/**
 * 可回頭點的最後一步。用「資料是否已備妥」推導，而不是記一個走過的最大值——
 * 使用者按了「重新規劃」把平面圖清掉之後，計數器會讓他跳回一個沒有資料的步驟。
 */
const maxReached = computed(() => {
  const keys = steps.value.map(s => s.key)
  const hasPlan   = editPlacements.value.length > 0 || !!floorPlanUrl.value
  const hasBase   = planSource.value === 'skip' || hasPlan || !!spacePhotoPath.value

  const hasRooms = detectedRooms.value.length > 0 || (cadPlanResult.value?.rooms?.length > 0)

  let reachable = 0
  keys.forEach((k, i) => {
    const ok =
      i === 0 ? true :
      k === 'roomPick' ? hasRooms :
      k === 'plan'   ? hasPlan :
      k === 'result' ? hasBase : false
    if (ok && i === reachable + 1) reachable = i
  })
  return reachable
})

// 停在風格選擇頁（result 步驟、還沒生成）時，後端先把生圖要用的條件圖算好，按生圖就不用再等
let prefetchTimer = null
watch(
  () => [currentStep.value, editPlacements.value, flow.roomW.value, flow.roomD.value, outputAspect.value, spacePhotoPath.value, result.value],
  ([step, placements, w, d, aspect, photo, res]) => {
    clearTimeout(prefetchTimer)
    if (step !== 'result' || res || photo || !placements?.length || !w || !d) return
    prefetchTimer = setTimeout(() => {
      jsonFetch('/api/prefetch-layout-conditions', {
        furniture_placements: placements, room_w: w, room_d: d, output_aspect: aspect,
      }).catch(() => {})
    }, 800)
  },
  { immediate: true, deep: true },
)

onMounted(() => {
  // 風格下拉選單的選項要先跟後端要；順便當作後端健康檢查
  if (flow.styleOptions.value.length <= 1) fetchStyleOptions()
  fetchStyleDemoImages()
  // 先把雲端 GPU 容器叫起來（是否動作由後端 .env 決定），使用者填完資料按生圖時就不用等冷啟動
  jsonFetch('/api/modal-warmup', {}).catch(() => {})
})
</script>

<template>
  <div class="db-scene studio" :style="{ '--db-scene-image': `url(${sceneBg})` }">
    <AppNav />

    <StepBar
      class="studio-steps"
      :steps="steps"
      :current="stepIndex"
      :max-reached="maxReached"
      @go="goStep"
    />

    <!-- 縮圖是卡片內部的第二欄（同一個白色框框），不是另外浮在旁邊的獨立卡片——
         那樣看起來像兩個框、主框框還會被擠到左邊。見 .studio-card.has-minimap 的 grid。 -->
    <div
      class="db-card studio-card"
      :class="{ 'has-minimap': showCadMiniMap && !minimapCompact, 'minimap-top': showCadMiniMap && minimapCompact }"
    >
      <div class="studio-main">
        <button
          v-if="stepIndex === 0 && !loading"
          type="button"
          class="mode-back-btn"
          @click="backToModeSelect"
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
            stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <polyline points="15 18 9 12 15 6" />
          </svg>
          重新選擇模式
        </button>

        <LoadingState v-if="loading || activeRendering" :title="loadingMsg.title" :sub="loadingMsg.sub" />
        <CadOverview v-else-if="showOverview" />
        <component :is="STEP_COMPONENTS[currentStep]" v-else />

        <p v-if="error && !loading" class="db-error studio-error">{{ error }}</p>
      </div>

      <CadRoomMiniMap
        v-if="showCadMiniMap"
        :compact="minimapCompact"
        :overview-active="showOverview"
        @overview="openOverview"
        :plan="cadPlanResult"
        :room-status="cadRoomStatus"
        :active-room-id="cadActiveRoomId"
        :active-placements="editPlacements"
        :batch="cadBatch"
        :batch-running="cadBatchRunning"
        :rendering="cadRendering"
        :thumbs="batchThumbs"
        :setting-labels="batchSettings"
        v-model:fengshui-rules="fengshuiRules"
        @select-room="jumpToCadRoom"
        @abandon="abandonCadRoom"
        @apply="applyToRooms"
        @cancel="cancelCadBatch"
      />
    </div>
  </div>
</template>

<style scoped>
.studio {
  display: flex;
  flex-direction: column;
  padding-bottom: 3rem;
}

.studio { --studio-w: min(1760px, calc(100vw - 2rem)); }   /* 白框與步驟列共用，左緣對齊 */
.studio-steps { width: var(--studio-w); margin: 0 auto; padding-left: 0.35rem; padding-right: 0.35rem; box-sizing: border-box; }

.studio-card {
  --pad: clamp(1.5rem, 3vw, 2.5rem);
  width: var(--studio-w);   /* 比預設 1192 寬 */
  padding: var(--pad) var(--pad) 0;
  position: relative;
}

/* 上一步 / 次要動作靠左、下一步 / 主要動作靠右，固定在卡片底部（捲動時黏在視窗底）。
   ponytail: 沿用各 step 的 .actions，不搬按鈕；只有一顆時靠右。 */
.studio-main :deep(.actions) {
  position: sticky;
  bottom: 0;
  z-index: 5;
  display: flex;
  flex-direction: row;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  margin: 1.5rem calc(-1 * var(--pad)) 0;
  padding: 1rem var(--pad);
  background: #fff;
  border-top: 1px solid #e8e6e1;
  border-radius: 0 0 var(--db-radius-card) var(--db-radius-card);
}
.studio-main :deep(.actions > :only-child) { margin-left: auto; }
.studio-main :deep(.actions .db-btn) { min-width: 0; }
/* 有縮圖時卡片內部變兩欄 grid：左邊主內容、右邊縮圖，同一個框框裡面，
   不是另外浮一個獨立的白卡在旁邊。 */
.studio-card.has-minimap {
  display: grid;
  grid-template-columns: 1fr clamp(300px, 26vw, 460px);   /* 整層進度縮圖：窄螢幕 300、寬螢幕最大 460 */
  align-items: start;
  gap: clamp(1.25rem, 2.5vw, 2rem);
}
.studio-main { min-width: 0; }
.studio-card.minimap-top { display: flex; flex-direction: column; }
.studio-card.minimap-top > .cad-minimap { order: -1; }

/* 原本是一行小灰字，太不顯眼，容易被當成裝飾文字而不是按鈕。
   改成有外框的實體按鈕，字級跟其他次要動作（例如「上一步」）看齊。 */
.mode-back-btn {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  margin-bottom: 1.5rem;
  padding: 0.5rem 1.1rem;
  border: 2px solid #dcdcdc;
  border-radius: var(--db-radius-pill);
  background: #fff;
  color: var(--db-text);
  font-family: var(--db-font-display);
  font-style: italic;
  font-weight: 500;
  font-size: 1rem;
  cursor: pointer;
  transition: border-color 0.16s, background 0.16s, transform 0.12s;
}
.mode-back-btn:hover {
  border-color: var(--db-accent);
  background: #f7f6f3;
  transform: translateX(-2px);
}
.mode-back-btn svg { flex-shrink: 0; }

@media (prefers-reduced-motion: reduce) {
  .mode-back-btn:hover { transform: none; }
}

.studio-error {
  margin: 1.25rem clamp(1.5rem, 3vw, 2.5rem) 0;
}

@media (max-width: 1100px) {
  .studio-card.has-minimap { grid-template-columns: 1fr; }
}
@media (max-width: 720px) {
  .studio-main :deep(.actions) { flex-direction: row; }
  .studio-main :deep(.actions .db-btn) { flex: 1; width: auto; }
}
/* 手機：底部操作列不再黏住（3 個子項疊起來會吃掉半個畫面），改成自然換行、按鈕滿寬 */
@media (max-width: 640px) {
  .studio-main :deep(.actions) { position: static; flex-wrap: wrap; gap: 0.6rem; }
  .studio-main :deep(.actions .db-btn) { flex: 1 1 140px; }
  .studio-main :deep(.actions p),
  .studio-main :deep(.actions .skip-btn) { flex: 1 1 100%; text-align: center; }
}
</style>
