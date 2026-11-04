<script setup>
/**
 * 線性精靈外殼（Figma frame 10/11/13/15/18/19/20 共用的版面）：
 * 滿版工具版面：導覽列 → 章節（流程）列 → 工作區（＋整層縮圖欄），工作區內容由當前步驟決定。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { jsonFetch } from '@/config/api'
import AppNav from '@/components/shell/AppNav.vue'
import ModeBackButton from '@/components/shell/ModeBackButton.vue'
import StepBar from '@/components/shell/StepBar.vue'
import LoadingState from '@/components/shell/LoadingState.vue'
import StepSpaceSetup from '@/components/steps/StepSpaceSetup.vue'
import StepPhotoUpload from '@/components/steps/StepPhotoUpload.vue'
import StepPhotoStudio from '@/components/steps/StepPhotoStudio.vue'
import StepPlanUpload from '@/components/steps/StepPlanUpload.vue'
import StepRoomProgram from '@/components/steps/StepRoomProgram.vue'
import StepRoomPick from '@/components/steps/StepRoomPick.vue'
import StepFloorPlan from '@/components/steps/StepFloorPlan.vue'
import StepResult from '@/components/steps/StepResult.vue'
import CadRoomMiniMap from '@/components/CadRoomMiniMap.vue'
import CadOverview from '@/components/CadOverview.vue'
import FengshuiReport from '@/components/FengshuiReport.vue'
import { useDesignFlow, ASPECT_OPTIONS } from '@/composables/useDesignFlow'

const flow = useDesignFlow()
const {
  steps, stepIndex, currentStep, goStep,
  loading, loadingMsg, error,
  editPlacements, floorPlanUrl, spacePhotoPath, planSource,
  detectedRooms, cadPlanResult, cadPlanSvg, cadRoomStatus, cadActiveRoomId, jumpToCadRoom, abandonCadRoom,
  cadBatch, cadBatchRunning, applyToRooms, cancelCadBatch,
  cadRoomSnapshots, cadRendering, planSource: flowPlanSource, confirmedStyle, result, outputAspect, extraPrompt,
  fengshuiRules, cadOverview,
  fengshuiEnabled, fengshuiReport, fengshuiReportLoading, fengshuiLastFix, fengshuiHighlight, applyFengshuiFix, undoFengshuiFix,
  roomW, roomD, layoutViewMode,
  fetchStyleOptions, fetchStyleDemoImages,
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
// 風水＋動線健檢放右欄（健檢排程在 StepFloorPlan）。有家具就先佔住右欄，
// 報告晚一點回來時畫布寬度不會突然縮一下。
const showFengshui = computed(
  () => currentStep.value === 'plan' && editPlacements.value.length > 0 && !loading.value && !activeRendering.value,
)
const showAside = computed(() => showCadMiniMap.value || showFengshui.value)

// 打開時順便把現有的違規家具推開；關掉只是不再套用，已經調整的位置不動
function onFengshuiToggle(on) {
  if (on) applyFengshuiFix()
  else fengshuiEnabled.value = false
}

// 健檢卡片的「定位」：切回 2D、在編輯器上圈出那件家具。家具一動就會重新健檢，圈圈跟著清掉
function locateFurniture(ids) {
  layoutViewMode.value = '2d'
  fengshuiHighlight.value = ids
}
watch([fengshuiReport, currentStep], () => { fengshuiHighlight.value = [] })

// 平面步驟右欄同時有整層縮圖和風水健檢：縮圖預設展開，想把空間讓給健檢可以收成一行（v-show，不卸載）
const minimapOpen = ref(true)
const minimapSummary = computed(() => {
  const rooms = cadPlanResult.value?.rooms || []
  const done = rooms.filter(r => cadRoomStatus.value[r.id] === 'done').length
  return `${done} / ${rooms.length} 間完成`
})
const minimapCollapsible = computed(() => showCadMiniMap.value && showFengshui.value)
// 縮圖下方標出正在編輯哪一間，縮圖和中間畫布的關係才看得出來
const activeRoomLabel = computed(
  () => (cadPlanResult.value?.rooms || []).find(r => r.id === cadActiveRoomId.value)?.label_zh || '',
)

const STEP_COMPONENTS = {
  space:       StepSpaceSetup,
  photo:       StepPhotoUpload,
  photoStudio: StepPhotoStudio,
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
  <div class="studio">
    <!-- 流程步驟放在導覽列中間，不另佔一排；只有一步（照片工作台）就不用流程列 -->
    <AppNav tone="paper" class="studio-nav">
      <StepBar
        v-if="steps.length > 1"
        class="studio-steps"
        :steps="steps"
        :current="stepIndex"
        :max-reached="maxReached"
        @go="goStep"
      />
    </AppNav>

    <!-- 滿版工作區：左邊主內容、右欄放全局資訊（整層縮圖、風水健檢），中間只有一條細線。
         右欄的米色底是 .has-aside::after 畫的。縮圖固定包在 .studio-aside 裡（頂部細列模式只是
         把整個右欄移到上方），父層不變，切換時不會被重新掛載。 -->
    <div
      class="studio-card"
      :class="{ 'has-aside': showAside && !(showCadMiniMap && minimapCompact), 'minimap-top': showCadMiniMap && minimapCompact }"
    >
      <div class="studio-main">
        <!-- 其他第一步把這顆放在底部操作列左邊；照片工作台沒有操作列，留在上方 -->
        <ModeBackButton v-if="currentStep === 'photoStudio' && !loading" class="mode-back-top" />

        <LoadingState v-if="loading || activeRendering" :title="loadingMsg.title" :sub="loadingMsg.sub" />
        <CadOverview v-else-if="showOverview" />
        <component :is="STEP_COMPONENTS[currentStep]" v-else />

        <p v-if="error && !loading" class="db-error studio-error">{{ error }}</p>
      </div>

      <aside v-if="showAside" class="studio-aside" :class="{ 'has-toggle': minimapCollapsible }">
      <button
        v-if="minimapCollapsible" type="button" class="minimap-toggle"
        :aria-expanded="minimapOpen" @click="minimapOpen = !minimapOpen"
      >
        <span class="minimap-toggle-title">整層進度</span>
        <span class="minimap-toggle-count">{{ minimapSummary }}</span>
        <span class="minimap-toggle-action">{{ minimapOpen ? '收合' : '展開' }}</span>
      </button>
      <CadRoomMiniMap
        v-if="showCadMiniMap"
        v-show="!minimapCollapsible || minimapOpen"
        :compact="minimapCompact"
        :overview-active="showOverview"
        @overview="openOverview"
        :plan="cadPlanResult"
        :svg-markup="cadPlanSvg"
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
      <p
        v-if="showCadMiniMap && !minimapCompact && activeRoomLabel"
        v-show="!minimapCollapsible || minimapOpen" class="minimap-current"
      >目前編輯：<strong>{{ activeRoomLabel }}</strong></p>
      <FengshuiReport
        v-if="showFengshui"
        :report="fengshuiReport"
        :placements="editPlacements"
        :room-w="roomW"
        :room-d="roomD"
        :enabled="fengshuiEnabled"
        :loading="fengshuiReportLoading"
        :last-fix="fengshuiLastFix"
        fixable
        toggleable
        locatable
        @locate="locateFurniture"
        @toggle="onFengshuiToggle"
        @enable="applyFengshuiFix"
        @fix="applyFengshuiFix"
        @undo="undoFengshuiFix"
      />
      </aside>
    </div>
  </div>
</template>

<style scoped>
/* 工作區是滿版工具版面（白色導覽列 → 米色章節列 → 白色工作區＋米色縮圖欄），
   各區只用 --db-line 細線分隔。不鋪室內照，也就沒有「白卡外面要墊什麼底」的問題；
   其他頁面仍是 db-scene 照片底 + 置中白卡。 */
.studio {
  --aside-w: clamp(300px, 26vw, 460px);   /* 整層進度縮圖：窄螢幕 300、寬螢幕最大 460 */
  display: flex;
  flex-direction: column;
  min-height: 100vh;
  background: var(--db-card);
  color: var(--db-text);
}

.studio-nav { border-bottom: 1px solid var(--db-line); }
/* 步驟在導覽列中間：不換行、不另外留上下內距（前面多一層 .studio-nav 才穩定蓋過 StepBar 自己的樣式） */
.studio-nav .studio-steps { flex-wrap: nowrap; padding: 0; }

.studio-card {
  --pad: clamp(1.5rem, 3vw, 2.5rem);
  flex: 1;
  position: relative;
  padding: var(--pad) var(--pad) 0;
  background: var(--db-card);
}

/* 上一步 / 次要動作靠左、下一步 / 主要動作靠右：整條固定在視窗最底部、橫跨整個畫面，
   「下一步」永遠在右下角。sticky 不行——主內容比右欄短時，操作列會停在主內容結尾、從右欄中間切過去。
   沿用各 step 的 .actions，不搬按鈕。前面多一個 .studio：各 step 自己的 .actions 也寫了置中，
   權重相同時誰贏看載入順序，這裡要穩定蓋過。 */
.studio { --actions-h: 5rem; }   /* 操作列的高度，內容底部要留這麼多空間 */
.studio .studio-main :deep(.actions) {
  position: fixed;
  left: 0;
  right: 0;
  bottom: 0;
  z-index: 50;
  display: flex;
  flex-direction: row;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  margin: 0;
  padding: 0.9rem var(--pad);
  background: var(--db-card);
  border-top: 1px solid var(--db-line);
}
.studio-card { padding-bottom: var(--actions-h); }
.studio-main :deep(.actions .db-btn) { min-width: 0; }
/* 主要動作（下一步）永遠在最右邊，只有它一顆時也一樣 */
.studio-main :deep(.actions > .db-btn:not(.db-btn--ghost):last-child) { margin-left: auto; }
/* 操作列在 .studio-main 裡；右欄（同樣 z-index 1、DOM 在後）不能蓋到它 */
.studio .has-aside > .studio-main { z-index: 2; }
/* 有右欄時變兩欄 grid：右欄貼齊視窗右緣、整欄米色底（::after 畫到工作區底部），
   右欄內容 sticky，捲動時一直看得到；內容比視窗高就在欄內捲動。 */
.studio-card.has-aside {
  display: grid;
  grid-template-columns: 1fr var(--aside-w);
  align-items: start;
  column-gap: calc(2 * var(--pad));
  padding-right: 0;
}
.studio-card.has-aside::after {
  content: '';
  position: absolute;
  top: 0;
  right: 0;
  bottom: 0;
  width: calc(var(--aside-w) + var(--pad));
  background: var(--db-paper);
  border-left: 1px solid var(--db-line);
}
.studio-card.has-aside > * { position: relative; z-index: 1; }
.studio-card.has-aside > .studio-aside {
  position: sticky;
  top: 0;
  max-height: calc(100vh - var(--actions-h));   /* 底部讓給固定的操作列 */
  overflow-y: auto;
  margin-top: calc(-1 * var(--pad));
  padding: var(--pad) var(--pad) var(--pad) 0;
}
/* 右欄本身就是米色面板，裡面的縮圖／報告不再各自包一層框 */
.has-aside .studio-aside > .cad-minimap:not(.is-compact-open) {
  position: static;
  padding: 0;
  border-radius: 0;
  background: none;
}
.studio-aside > .fs-report {
  margin: 0;
  padding: 0;
  border: none;
  background: none;
}
.minimap-current { margin: 0.6rem 0 0; color: var(--db-text-soft); font-size: 0.85rem; }
.minimap-current strong { color: var(--db-text); font-weight: 600; }
.studio-aside > .cad-minimap + .fs-report,
.studio-aside > .minimap-current + .fs-report {
  margin-top: 1.5rem;
  padding-top: 1.5rem;
  border-top: 1px solid var(--db-line);
}

/* 收合的整層縮圖：一行標題＋進度，點了展開 */
.minimap-toggle {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  width: 100%;
  margin-bottom: 1rem;
  padding: 0.6rem 0.85rem;
  border: 1px solid var(--db-line);
  border-radius: var(--db-radius-chip);
  background: var(--db-card);
  color: var(--db-text);
  font: inherit;
  cursor: pointer;
}
.minimap-toggle:hover { border-color: var(--db-accent-deep); }
.minimap-toggle-title { font-family: var(--db-font-display); font-style: italic; font-weight: 600; }
.minimap-toggle-count { color: var(--db-text-soft); font-size: 0.85rem; }
/* 收合列已經寫了「整層進度 N/M」，縮圖自己的標題列就不重複 */
.has-toggle :deep(.minimap-head) { display: none; }
.minimap-toggle-action { margin-left: auto; color: var(--db-accent-ink); font-size: 0.82rem; text-decoration: underline; text-underline-offset: 3px; }
.studio-main { min-width: 0; }
.studio-card.minimap-top { display: flex; flex-direction: column; }
.studio-card.minimap-top > .studio-aside { order: -1; }

.mode-back-top { margin-bottom: 1.5rem; }
/* 操作列裡的「重新選擇模式」吃掉左邊空間，其餘按鈕一起靠右 */
.studio-main :deep(.actions > .mode-back-btn) { margin-right: auto; }

.studio-error {
  margin: 1.25rem clamp(1.5rem, 3vw, 2.5rem) 0;
}

/* 窄螢幕：右欄疊到主內容下方，變成一塊米色小框 */
@media (max-width: 1100px) {
  .studio-card.has-aside { grid-template-columns: 1fr; padding-right: var(--pad); }
  .studio-card.has-aside::after { display: none; }
  .studio-card.has-aside > .studio-aside {
    position: static;
    max-height: none;
    overflow: visible;
    margin: 1.5rem 0 var(--pad);
    padding: 1.1rem;
    border-radius: var(--db-radius-chip);
    background: var(--db-paper);
  }
}
@media (max-width: 720px) {
  .studio .studio-main :deep(.actions) { flex-direction: row; }
  .studio-main :deep(.actions .db-btn) { flex: 1; width: auto; }
}
/* 手機：底部操作列不再固定（3 個子項疊起來會吃掉半個畫面），改成接在內容後面、自然換行、按鈕滿寬 */
@media (max-width: 640px) {
  .studio { --actions-h: 0px; }
  .studio .studio-main :deep(.actions) {
    position: static; flex-wrap: wrap; gap: 0.6rem;
    margin: 1.5rem calc(-1 * var(--pad)) 0;
  }
  .studio-main :deep(.actions .db-btn) { flex: 1 1 140px; }
  .studio-main :deep(.actions p),
  .studio-main :deep(.actions .skip-btn) { flex: 1 1 100%; text-align: center; }
}
</style>
