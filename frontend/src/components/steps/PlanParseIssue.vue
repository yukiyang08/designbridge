<script setup>
/**
 * 平面圖解析沒結果時的提示：讓使用者知道「沒解析出來」，再自己選重試或改走後備路徑，
 * 而不是被默默帶到下一步。上傳平面圖、選擇房間兩個步驟共用。
 */
import { computed } from 'vue'
import { useDesignFlow } from '@/composables/useDesignFlow'

const {
  planParseIssue, loading, retryPlanParse, parseAsSingleRoom, continueWithoutFurniture,
} = useDesignFlow()

const text = computed(() => {
  const i = planParseIssue.value
  if (!i) return null
  if (i.kind === 'rooms') {
    return i.reason === 'failed'
      ? { title: '房間辨識失敗', body: 'AI 服務這次沒有回應或回傳格式有誤，可以再試一次。' }
      : { title: '沒有辨識出任何房間', body: '這張圖可能太模糊、線條太淡，或不像平面圖。可以重試，或把整張圖當成一間房繼續。' }
  }
  return i.reason === 'failed'
    ? { title: '家具解析失敗', body: 'AI 服務這次沒有回應或回傳格式有誤，可以再試一次。' }
    : { title: '沒有從平面圖解析出家具', body: '圖上可能沒有畫家具，或家具符號 AI 認不出來。可以重試，或不排家具、只用平面圖當結構參考生成。' }
})
</script>

<template>
  <div v-if="text" class="parse-issue" role="alert">
    <p class="pi-title">⚠ {{ text.title }}</p>
    <p class="pi-body">{{ text.body }}</p>
    <div class="pi-actions">
      <button type="button" class="db-btn db-btn--sm" :disabled="loading" @click="retryPlanParse">重試</button>
      <button
        v-if="planParseIssue.kind === 'rooms'"
        type="button" class="db-btn db-btn--ghost db-btn--sm" :disabled="loading" @click="parseAsSingleRoom"
      >當作單一房間繼續</button>
      <button
        v-else
        type="button" class="db-btn db-btn--ghost db-btn--sm" :disabled="loading" @click="continueWithoutFurniture"
      >不排家具，直接繼續</button>
    </div>
  </div>
</template>

<style scoped>
.parse-issue {
  margin-top: 1.25rem;
  padding: 1rem 1.2rem;
  border: 1px solid #e8c9c4;
  border-radius: var(--db-radius-chip);
  background: var(--db-danger-soft);
}
.pi-title { margin: 0; font-weight: 600; color: var(--db-danger); }
.pi-body { margin: 0.35rem 0 0; color: var(--db-text-soft); font-size: 0.88rem; line-height: 1.6; }
.pi-actions { display: flex; flex-wrap: wrap; gap: 0.6rem; margin-top: 0.8rem; }
</style>
