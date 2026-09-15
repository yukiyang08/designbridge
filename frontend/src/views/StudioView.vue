<script setup>
/**
 * 線性精靈外殼（Figma frame 10/11/13/15/18/19/20 共用的版面）：
 * 滿版背景 → 導覽列 → 流程列 → 置中白卡，白卡內容由當前步驟決定。
 */
import { computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import AppNav from '@/components/shell/AppNav.vue'
import StepBar from '@/components/shell/StepBar.vue'
import LoadingState from '@/components/shell/LoadingState.vue'
import StepSpaceSetup from '@/components/steps/StepSpaceSetup.vue'
import StepPhotoUpload from '@/components/steps/StepPhotoUpload.vue'
import StepPlanUpload from '@/components/steps/StepPlanUpload.vue'
import StepFloorPlan from '@/components/steps/StepFloorPlan.vue'
import StepRender from '@/components/steps/StepRender.vue'
import StepRefine from '@/components/steps/StepRefine.vue'
import StepBudget from '@/components/steps/StepBudget.vue'
import { useDesignFlow } from '@/composables/useDesignFlow'
import sceneBg from '@/assets/figma/room-bg.png'

const router = useRouter()
const flow = useDesignFlow()
const {
  steps, stepIndex, currentStep, goStep,
  loading, loadingMsg, error,
  editPlacements, floorPlanUrl, spacePhotoPath, lastGeneratedImage, planSource,
  fetchStyleOptions, resetFlow,
} = flow

// 三個入口模式選錯了想換一個，只有在第一步才需要——後面幾步已經有資料，
// 「上一步」在流程列裡點就好，不用再提供這顆。
function backToModeSelect() {
  resetFlow()
  router.push('/start')
}

const STEP_COMPONENTS = {
  space:      StepSpaceSetup,
  photo:      StepPhotoUpload,
  planUpload: StepPlanUpload,
  plan:       StepFloorPlan,
  render:     StepRender,
  refine:     StepRefine,
  budget:     StepBudget,
}

/**
 * 可回頭點的最後一步。用「資料是否已備妥」推導，而不是記一個走過的最大值——
 * 使用者按了「重新規劃」把平面圖清掉之後，計數器會讓他跳回一個沒有資料的步驟。
 */
const maxReached = computed(() => {
  const keys = steps.value.map(s => s.key)
  const hasPlan   = editPlacements.value.length > 0 || !!floorPlanUrl.value
  const hasBase   = planSource.value === 'skip' || hasPlan || !!spacePhotoPath.value
  const hasRender = !!lastGeneratedImage.value

  let reachable = 0
  keys.forEach((k, i) => {
    const ok =
      i === 0 ? true :
      k === 'plan'   ? hasPlan :
      k === 'render' ? hasBase :
      k === 'refine' ? hasRender :
      k === 'budget' ? hasRender : false
    if (ok && i === reachable + 1) reachable = i
  })
  return reachable
})

onMounted(() => {
  // 風格下拉選單的選項要先跟後端要；順便當作後端健康檢查
  if (flow.styleOptions.value.length <= 1) fetchStyleOptions()
})
</script>

<template>
  <div class="db-scene studio" :style="{ '--db-scene-image': `url(${sceneBg})` }">
    <AppNav />

    <StepBar
      :steps="steps"
      :current="stepIndex"
      :max-reached="maxReached"
      @go="goStep"
    />

    <div class="db-card studio-card">
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

      <LoadingState v-if="loading" :title="loadingMsg.title" :sub="loadingMsg.sub" />
      <component :is="STEP_COMPONENTS[currentStep]" v-else />

      <p v-if="error && !loading" class="db-error studio-error">{{ error }}</p>
    </div>
  </div>
</template>

<style scoped>
.studio {
  display: flex;
  flex-direction: column;
  padding-bottom: 3rem;
}

.studio-card {
  padding: clamp(1.5rem, 3vw, 2.5rem);
  position: relative;
}

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
  background: #fbfaf6;
  transform: translateX(-2px);
}
.mode-back-btn svg { flex-shrink: 0; }

@media (prefers-reduced-motion: reduce) {
  .mode-back-btn:hover { transform: none; }
}

.studio-error {
  margin: 1.25rem clamp(1.5rem, 3vw, 2.5rem) 0;
}
</style>
